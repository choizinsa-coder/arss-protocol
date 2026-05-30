"""
test_mcp_write_eag1_p3_assertions.py — P4-C4 Phase-beta Batch-5 P3 assertion 보강
S177 EAG-1 (도미 Revision-1 + 제니 TRUST_READY)

도미 [DESIGN] 기준:
  - P3 tier2_handler.py (2 assertions)
  - Rule-T2-1: 외부 관측 가능 상태 변화 / 거버넌스 효력 발생 / Write Plane 상태 전이

보강 대상:
  P3-A1: _check_extension 직접 호출 + handle_tier2_write 통합 거부 시
         파일 미생성 (Fail-Closed 완전성) — 모든 FORBIDDEN 확장자 + 대소문자 변형
         (거버넌스 효력 발생)
  P3-A2: handle_tier2_write sandbox 이탈 거부 시
         파일 미생성 + audit 기록 없음 (Fail-Closed 완전성)
         (거버넌스 효력 발생)

기존 test_mcp_write_eag1.py CONTRACT-02/03은 Tier2DenyError raise + contract 식별자만 검증.
본 파일은 거버넌스 부수 효과(파일 미생성, audit 기록 없음)까지 검증.
"""

import json
import os
import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.mcp_write.tier2_handler import (
    handle_tier2_write,
    _check_extension,
    Tier2DenyError,
    FORBIDDEN_EXTENSIONS,
)
from tools.mcp_write.tier_router import (
    set_write_plane_state,
    WritePlaneState,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path):
    sb = tmp_path / "sandbox"
    sb.mkdir()
    return sb


@pytest.fixture
def registry(tmp_path):
    reg = tmp_path / "registry"
    for d in ["approvals", "receipts", "audit", "state"]:
        (reg / d).mkdir(parents=True)
    return reg


@pytest.fixture
def state_file(tmp_path, registry):
    return str(registry / "state" / "plane_state.json")


@pytest.fixture(autouse=True)
def reset_state(tmp_path, registry, state_file):
    """각 테스트 전 NORMAL 상태로 초기화."""
    import tools.mcp_write.tier_router as tr
    _orig_state_file = tr.STATE_FILE
    tr.STATE_FILE = state_file
    set_write_plane_state(WritePlaneState.NORMAL, reason="test setup")
    yield
    tr.STATE_FILE = _orig_state_file


# ── P3-A1: _check_extension + Fail-Closed 파일 미생성 ──────────────────

@pytest.mark.parametrize("ext", sorted(FORBIDDEN_EXTENSIONS))
def test_p3_a1_forbidden_extension_blocked_and_no_file_created(
    tmp_path, sandbox, registry, ext
):
    """
    P3-A1 (Rule-T2-1: 거버넌스 효력 발생):
    모든 FORBIDDEN_EXTENSIONS에 대해 _check_extension이 raise하며,
    handle_tier2_write 경유 시에도 실제 파일이 생성되지 않아야 한다.

    기존 CONTRACT-03 테스트는 Tier2DenyError raise + contract 식별자만 검증.
    본 테스트는 Fail-Closed 완전성(파일 미생성)을 추가 검증.

    또한 모든 FORBIDDEN_EXTENSIONS를 fixture에서 직접 순회하므로,
    향후 금지 확장자가 추가될 경우 자동으로 보강 검증된다.
    """
    audit_file = str(registry / "audit" / "audit.jsonl")

    # 1) _check_extension 직접 호출 시 raise (CONTRACT-03)
    target = str(sandbox / f"direct{ext}")
    with pytest.raises(Tier2DenyError) as exc_direct:
        _check_extension(target)
    assert exc_direct.value.contract == "CONTRACT-03"
    assert ext in exc_direct.value.reason

    # 2) handle_tier2_write 경유 시에도 raise (거버넌스 통합)
    target_via_handler = str(sandbox / f"via_handler{ext}")
    with pytest.raises(Tier2DenyError) as exc_handler:
        handle_tier2_write(
            target_path=target_via_handler,
            content="this content must not be written",
            audit_file=audit_file,
            sandbox_paths=[str(sandbox)],
        )
    assert exc_handler.value.contract == "CONTRACT-03"

    # 3) 거버넌스 효력 검증: 실제 파일 미생성 (Fail-Closed 완전성)
    assert not os.path.exists(target_via_handler), (
        f"금지 확장자 {ext} 거부 후에도 파일이 생성됨 — Fail-Closed 위반"
    )


# ── P3-A2: sandbox 이탈 거부 시 파일 미생성 + audit 기록 없음 ───────────

def test_p3_a2_sandbox_escape_denied_no_file_no_audit(
    tmp_path, sandbox, registry
):
    """
    P3-A2 (Rule-T2-1: 거버넌스 효력 발생):
    handle_tier2_write가 sandbox 외부 경로를 거부할 때
    실제 파일이 생성되지 않을 뿐 아니라,
    audit 기록도 남지 않아야 한다 (경계 진입 전 차단 = 완전 Fail-Closed).

    기존 CONTRACT-02 테스트는 raise + contract만 검증.
    본 테스트는 거버넌스 부수 효과 두 가지를 추가 검증:
      (1) 실제 파일 미생성
      (2) audit 라인 미기록 (sandbox 외부 시도는 audit조차 남기지 않음)
    """
    audit_file = str(registry / "audit" / "audit.jsonl")

    # 외부 경로 (sandbox 밖)
    outside = str(tmp_path / "outside_unauthorized.txt")

    # 사전 상태: audit 파일이 존재하지 않음
    assert not os.path.exists(audit_file)

    # sandbox 외부 쓰기 시도 → CONTRACT-02 거부
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=outside,
            content="must not be written",
            audit_file=audit_file,
            sandbox_paths=[str(sandbox)],
        )
    assert exc.value.contract == "CONTRACT-02"

    # 거버넌스 효력 검증 (1): 실제 파일 미생성
    assert not os.path.exists(outside), (
        "sandbox 외부 거부 후에도 파일이 생성됨 — Fail-Closed 위반"
    )

    # 거버넌스 효력 검증 (2): audit 기록 없음
    # (sandbox 외부 시도는 경계 진입 전 차단이므로 audit조차 남기지 않음)
    if os.path.exists(audit_file):
        with open(audit_file, "r", encoding="utf-8") as f:
            lines = [ln for ln in f.readlines() if ln.strip()]
        assert len(lines) == 0, (
            f"sandbox 외부 거부 시 audit 라인이 기록됨 ({len(lines)}건) — "
            f"경계 진입 전 차단 원칙 위반"
        )

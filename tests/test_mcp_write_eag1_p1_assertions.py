"""
test_mcp_write_eag1_p1_assertions.py — P4-C4 Phase-beta Batch-5 P1 assertion 보강
S177 EAG-1 (도미 Revision-1 + 제니 TRUST_READY)

도미 [DESIGN] 기준:
  - P1 tier1_handler.py (3 assertions)
  - Rule-T2-1: 외부 관측 가능 상태 변화 / 거버넌스 효력 발생 / Write Plane 상태 전이
              를 수반하는 failure-path만 보강

보강 대상:
  P1-A1: _verify_artifact artifact 무결성 실패
         (governance: 승인 위변조 차단 효력)
  P1-A2: _create_receipt 실패 → LOCKED_TIER1 Write Plane 상태 전이
         (Write Plane 상태 전이)
  P1-A3: _append_audit 실패 → LOCKED_TIER1 Write Plane 상태 전이
         (Write Plane 상태 전이)

기존 test_mcp_write_eag1.py의 CONTRACT-06/08/09는 raise/contract만 검증.
본 파일은 그 위에 Rule-T2-1 충족 항목(상태 전이 + 위변조 차단)을 추가 검증.
"""

import json
import os
import sys
import pytest
from unittest import mock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.mcp_write.issuer import issue_approval, compute_artifact_hash
from tools.mcp_write.tier_router import (
    get_write_plane_state,
    set_write_plane_state,
    WritePlaneState,
)
from tools.mcp_write.tier1_handler import handle_tier1_write, Tier1DenyError


# ── Fixtures (test_mcp_write_eag1.py와 동일 구조) ──────────────────────

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
    """각 테스트 전 상태 파일 초기화 (NORMAL)."""
    import tools.mcp_write.tier_router as tr
    _orig_state_file = tr.STATE_FILE
    tr.STATE_FILE = state_file
    # NORMAL 상태로 초기화
    set_write_plane_state(WritePlaneState.NORMAL, reason="test setup")
    yield
    tr.STATE_FILE = _orig_state_file


def _issue_approval_in_registry(registry, target, content):
    """헬퍼: registry 격리된 approval 발급."""
    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    try:
        artifact = issue_approval("Beo", target, content)
    finally:
        iss.APPROVALS_DIR = _orig_dir
    return artifact


# ── P1-A1: artifact 무결성 위변조 차단 (거버넌스 효력 발생) ─────────────

def test_p1_a1_artifact_hash_tampered_denied(tmp_path, sandbox, registry):
    """
    P1-A1 (Rule-T2-1: 거버넌스 효력 발생):
    artifact 본문이 위변조되어 verify_artifact_integrity가 실패할 경우,
    Tier1DenyError가 CONTRACT-06으로 발생해야 한다.

    기존 CONTRACT-06 테스트는 content_hash 불일치만 검증.
    본 테스트는 artifact_hash 자체의 위변조(승인 위변조) 차단을 검증.
    """
    target = str(sandbox / "tampered.md")
    content = "# 위변조 테스트"
    artifact = _issue_approval_in_registry(registry, target, content)

    # artifact 본문 위변조 — issuer를 거치지 않고 actor를 변경
    # (artifact_hash는 갱신하지 않음 → verify_artifact_integrity 실패)
    artifact_path = os.path.join(
        str(registry / "approvals"), f"{artifact['approval_id']}.json"
    )
    artifact["actor"] = "Attacker"  # 위변조
    # 의도적으로 artifact_hash는 그대로 두어 무결성 실패 유도
    with open(artifact_path, "w") as f:
        json.dump(artifact, f)

    with pytest.raises(Tier1DenyError) as exc:
        handle_tier1_write(
            approval_id=artifact["approval_id"],
            target_path=target,
            content=content,
            approvals_dir=str(registry / "approvals"),
            receipts_dir=str(registry / "receipts"),
            audit_file=str(registry / "audit" / "audit.jsonl"),
        )

    # 거버넌스 효력: 위변조 차단 발생 확인
    assert exc.value.contract == "CONTRACT-06"
    assert "무결성" in exc.value.reason or "artifact_hash" in exc.value.reason
    # 거버넌스 효력 검증: 실제 파일이 쓰이지 않았음 (Fail-Closed)
    assert not os.path.exists(target)


# ── P1-A2: receipt 생성 실패 시 Write Plane LOCKED_TIER1 전이 ──────────

def test_p1_a2_receipt_failure_triggers_locked_tier1(
    tmp_path, sandbox, registry, state_file
):
    """
    P1-A2 (Rule-T2-1: Write Plane 상태 전이):
    receipt 생성이 실패할 경우, Fail-Closed로 Write Plane이
    LOCKED_TIER1으로 전이되어야 한다 (CONTRACT-08).

    기존 CONTRACT-08 테스트는 Tier1DenyError raise만 검증.
    본 테스트는 실제 디스크 I/O 실패를 통해 LOCKED_TIER1 상태 전이를 검증.
    """
    import tools.mcp_write.tier_router as tr
    tr.STATE_FILE = state_file

    target = str(sandbox / "receipt_lock.md")
    content = "# receipt lock test"
    artifact = _issue_approval_in_registry(registry, target, content)

    # 사전 상태: NORMAL 확인
    assert get_write_plane_state() == WritePlaneState.NORMAL

    # receipt 디스크 쓰기를 실패시키기 위해 open을 mock으로 차단
    real_open = open
    receipts_dir = str(registry / "receipts")

    def selective_open(path, *args, **kwargs):
        # receipts_dir 내부 쓰기만 실패시킴
        if isinstance(path, str) and path.startswith(receipts_dir) and "w" in (args[0] if args else kwargs.get("mode", "")):
            raise OSError("simulated disk failure on receipt write")
        return real_open(path, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=selective_open):
        with pytest.raises(Tier1DenyError) as exc:
            handle_tier1_write(
                approval_id=artifact["approval_id"],
                target_path=target,
                content=content,
                approvals_dir=str(registry / "approvals"),
                receipts_dir=receipts_dir,
                audit_file=str(registry / "audit" / "audit.jsonl"),
            )

    # CONTRACT-08 확인
    assert exc.value.contract == "CONTRACT-08"

    # Write Plane 상태 전이 검증 (Rule-T2-1 핵심)
    final_state = get_write_plane_state()
    assert final_state == WritePlaneState.LOCKED_TIER1, (
        f"receipt 실패 시 LOCKED_TIER1 전이 누락: 현재 상태={final_state}"
    )


# ── P1-A3: audit 기록 실패 시 Write Plane LOCKED_TIER1 전이 ────────────

def test_p1_a3_audit_failure_triggers_locked_tier1(
    tmp_path, sandbox, registry, state_file
):
    """
    P1-A3 (Rule-T2-1: Write Plane 상태 전이):
    audit 기록이 실패할 경우, Fail-Closed로 Write Plane이
    LOCKED_TIER1으로 전이되어야 한다 (CONTRACT-09).

    기존 CONTRACT-09 테스트는 Tier1DenyError raise만 검증.
    본 테스트는 실제 디스크 I/O 실패를 통해 LOCKED_TIER1 상태 전이를 검증.
    """
    import tools.mcp_write.tier_router as tr
    tr.STATE_FILE = state_file

    target = str(sandbox / "audit_lock.md")
    content = "# audit lock test"
    artifact = _issue_approval_in_registry(registry, target, content)

    # 사전 상태: NORMAL 확인
    assert get_write_plane_state() == WritePlaneState.NORMAL

    audit_file = str(registry / "audit" / "audit.jsonl")
    real_open = open

    def selective_open(path, *args, **kwargs):
        # audit_file에 append("a") 모드 쓰기만 실패시킴
        mode = args[0] if args else kwargs.get("mode", "")
        if isinstance(path, str) and path == audit_file and "a" in mode:
            raise OSError("simulated disk failure on audit append")
        return real_open(path, *args, **kwargs)

    with mock.patch("builtins.open", side_effect=selective_open):
        with pytest.raises(Tier1DenyError) as exc:
            handle_tier1_write(
                approval_id=artifact["approval_id"],
                target_path=target,
                content=content,
                approvals_dir=str(registry / "approvals"),
                receipts_dir=str(registry / "receipts"),
                audit_file=audit_file,
            )

    # CONTRACT-09 확인
    assert exc.value.contract == "CONTRACT-09"

    # Write Plane 상태 전이 검증 (Rule-T2-1 핵심)
    final_state = get_write_plane_state()
    assert final_state == WritePlaneState.LOCKED_TIER1, (
        f"audit 실패 시 LOCKED_TIER1 전이 누락: 현재 상태={final_state}"
    )

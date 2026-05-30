"""
test_mcp_write_eag1_p2_assertions.py — P4-C4 Phase-beta Batch-5 P2 assertion 보강
S177 EAG-1 (도미 Revision-1 + 제니 TRUST_READY)

도미 [DESIGN] 기준:
  - P2 lifecycle_manager.py (3 assertions)
  - Rule-T2-1: 외부 관측 가능 상태 변화 / 거버넌스 효력 발생 / Write Plane 상태 전이
              를 수반하는 failure-path만 보강

보강 대상:
  P2-A1: mark_used non-ACTIVE 시 → LOCKED_TIER1 자동 전이 + LifecycleError
         (Write Plane 상태 전이 — Fail-Closed 단일 실패 지점)
  P2-A2: mark_expired 전이 시 외부 관측 가능 상태 변화 검증
         (status / revoked_at / revoke_reason / artifact_hash 갱신)
  P2-A3: mark_revoked non-ACTIVE 시 LifecycleError + 상태 보존
         (외부 관측 가능 상태 변화 차단 = 거버넌스 보호)

기존 test_mcp_write_eag1.py는 mark_used만 간접 검증 (CONTRACT-07 재사용 시점).
mark_expired / mark_revoked 직접 테스트는 부재.
"""

import json
import os
import sys
import pytest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.mcp_write.issuer import (
    issue_approval,
    load_approval,
    compute_artifact_hash,
)
from tools.mcp_write.lifecycle_manager import (
    mark_used,
    mark_expired,
    mark_revoked,
    check_and_expire,
    LifecycleError,
)
from tools.mcp_write.tier_router import (
    get_write_plane_state,
    set_write_plane_state,
    WritePlaneState,
)


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
    """각 테스트 전 NORMAL 상태로 초기화."""
    import tools.mcp_write.tier_router as tr
    _orig_state_file = tr.STATE_FILE
    tr.STATE_FILE = state_file
    set_write_plane_state(WritePlaneState.NORMAL, reason="test setup")
    yield
    tr.STATE_FILE = _orig_state_file


def _issue_approval_in_registry(registry, target, content, ttl_seconds=3600):
    """헬퍼: registry 격리된 approval 발급."""
    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    try:
        artifact = issue_approval("Beo", target, content, ttl_seconds=ttl_seconds)
    finally:
        iss.APPROVALS_DIR = _orig_dir
    return artifact


# ── P2-A1: mark_used non-ACTIVE → LOCKED_TIER1 자동 전이 ───────────────

def test_p2_a1_mark_used_non_active_triggers_locked_tier1(
    tmp_path, sandbox, registry, state_file
):
    """
    P2-A1 (Rule-T2-1: Write Plane 상태 전이):
    이미 USED 상태인 approval에 대해 mark_used를 다시 호출하면
    Fail-Closed 계약에 따라 Write Plane이 LOCKED_TIER1으로 자동 전이되어야 한다.

    근거: lifecycle_manager.py mark_used() Fail-Closed 분기
          (단일 실패 지점 — 제니 TRUST-CHECK-06 근거)

    기존 테스트(CONTRACT-07)는 handle_tier1_write 레벨에서 재사용 거부만 검증.
    본 테스트는 mark_used 직접 호출 시 LOCKED_TIER1 자동 전이를 직접 검증.
    """
    import tools.mcp_write.tier_router as tr
    tr.STATE_FILE = state_file

    target = str(sandbox / "p2_a1.md")
    content = "# P2-A1 test"
    artifact = _issue_approval_in_registry(registry, target, content)
    approvals_dir = str(registry / "approvals")

    # 1차 mark_used 정상 전이
    mark_used(artifact["approval_id"], approvals_dir)

    # 사전 상태: NORMAL 확인
    assert get_write_plane_state() == WritePlaneState.NORMAL

    # 2차 mark_used 호출 — USED 상태이므로 LifecycleError 발생
    with pytest.raises(LifecycleError) as exc:
        mark_used(artifact["approval_id"], approvals_dir)

    # Fail-Closed 메시지 확인
    assert "FAIL-CLOSED" in str(exc.value)
    assert "LOCKED_TIER1" in str(exc.value)

    # Write Plane 상태 전이 검증 (Rule-T2-1 핵심)
    final_state = get_write_plane_state()
    assert final_state == WritePlaneState.LOCKED_TIER1, (
        f"mark_used 재호출 시 LOCKED_TIER1 자동 전이 누락: 현재={final_state}"
    )


# ── P2-A2: mark_expired 외부 관측 가능 상태 변화 ──────────────────────

def test_p2_a2_mark_expired_observable_state_change(tmp_path, sandbox, registry):
    """
    P2-A2 (Rule-T2-1: 외부 관측 가능 상태 변화):
    mark_expired 호출 시 다음 4가지가 모두 외부에서 관측 가능해야 한다:
      - status: ACTIVE → EXPIRED
      - revoked_at: 타임스탬프 기록
      - revoke_reason: "TTL_EXPIRED"
      - artifact_hash: 새로운 본문에 맞춰 재계산됨

    기존 테스트는 check_and_expire 경유 만료만 간접 검증.
    본 테스트는 mark_expired 직접 호출 + 4가지 관측 가능 변화 모두 검증.
    """
    target = str(sandbox / "p2_a2.md")
    content = "# P2-A2 test"
    artifact = _issue_approval_in_registry(registry, target, content)
    approvals_dir = str(registry / "approvals")

    # 사전 상태 캡처
    before = load_approval(artifact["approval_id"], approvals_dir)
    before_hash = before["artifact_hash"]
    assert before["status"] == "ACTIVE"
    assert before.get("revoked_at") is None
    assert before.get("revoke_reason") is None

    # mark_expired 호출
    mark_expired(artifact["approval_id"], approvals_dir)

    # 외부 관측 가능 변화 4종 검증
    after = load_approval(artifact["approval_id"], approvals_dir)

    # (1) status 전이
    assert after["status"] == "EXPIRED", (
        f"status 전이 누락: {before['status']} → {after['status']}"
    )

    # (2) revoked_at 타임스탬프 기록
    assert after.get("revoked_at") is not None
    # ISO 형식 파싱 가능 여부 확인
    parsed = datetime.fromisoformat(after["revoked_at"])
    assert parsed.tzinfo is not None

    # (3) revoke_reason TTL_EXPIRED 명시
    assert after.get("revoke_reason") == "TTL_EXPIRED"

    # (4) artifact_hash 재계산 (본문 변경 반영)
    assert after["artifact_hash"] != before_hash, (
        "artifact_hash가 갱신되지 않음 (외부 위변조 탐지 불가)"
    )
    # 재계산된 hash가 실제 본문과 일치하는지 검증
    recomputed = compute_artifact_hash(after)
    assert after["artifact_hash"] == recomputed


# ── P2-A3: mark_revoked non-ACTIVE 차단 + 상태 보존 ────────────────────

def test_p2_a3_mark_revoked_non_active_rejected_state_preserved(
    tmp_path, sandbox, registry
):
    """
    P2-A3 (Rule-T2-1: 외부 관측 가능 상태 변화 차단 = 거버넌스 보호):
    이미 USED / EXPIRED / REVOKED 상태인 approval에 대해 mark_revoked 호출 시
    LifecycleError가 발생하고, 기존 상태가 변경되지 않아야 한다.

    근거: lifecycle_manager.py mark_revoked() 상태 검증 분기

    기존 테스트는 mark_revoked 직접 호출 검증이 부재.
    본 테스트는 3가지 non-ACTIVE 상태 모두에서 차단 + 상태 보존을 검증.
    """
    approvals_dir = str(registry / "approvals")

    # Case A: USED 상태에서 mark_revoked 거부
    target_a = str(sandbox / "p2_a3_used.md")
    artifact_a = _issue_approval_in_registry(registry, target_a, "# A")
    mark_used(artifact_a["approval_id"], approvals_dir)

    before_a = load_approval(artifact_a["approval_id"], approvals_dir)
    assert before_a["status"] == "USED"

    with pytest.raises(LifecycleError) as exc_a:
        mark_revoked(artifact_a["approval_id"], reason="should fail", approvals_dir=approvals_dir)
    assert "mark_revoked 불가" in str(exc_a.value)
    assert "USED" in str(exc_a.value)

    # 상태 보존 검증
    after_a = load_approval(artifact_a["approval_id"], approvals_dir)
    assert after_a["status"] == "USED"
    assert after_a.get("revoke_reason") is None, (
        "non-ACTIVE에서 mark_revoked 시도가 revoke_reason을 변경시킴"
    )

    # Case B: EXPIRED 상태에서 mark_revoked 거부
    target_b = str(sandbox / "p2_a3_expired.md")
    artifact_b = _issue_approval_in_registry(registry, target_b, "# B")
    mark_expired(artifact_b["approval_id"], approvals_dir)

    before_b = load_approval(artifact_b["approval_id"], approvals_dir)
    assert before_b["status"] == "EXPIRED"
    before_b_reason = before_b.get("revoke_reason")
    assert before_b_reason == "TTL_EXPIRED"

    with pytest.raises(LifecycleError) as exc_b:
        mark_revoked(artifact_b["approval_id"], reason="should fail", approvals_dir=approvals_dir)
    assert "EXPIRED" in str(exc_b.value)

    # 상태 보존 검증 (revoke_reason도 변경되지 않아야 함)
    after_b = load_approval(artifact_b["approval_id"], approvals_dir)
    assert after_b["status"] == "EXPIRED"
    assert after_b["revoke_reason"] == "TTL_EXPIRED", (
        "EXPIRED에서 mark_revoked 시도가 revoke_reason을 덮어씀"
    )

    # Case C: REVOKED 상태에서 mark_revoked 재호출 거부
    target_c = str(sandbox / "p2_a3_revoked.md")
    artifact_c = _issue_approval_in_registry(registry, target_c, "# C")
    mark_revoked(artifact_c["approval_id"], reason="first revoke", approvals_dir=approvals_dir)

    before_c = load_approval(artifact_c["approval_id"], approvals_dir)
    assert before_c["status"] == "REVOKED"
    assert before_c["revoke_reason"] == "first revoke"

    with pytest.raises(LifecycleError) as exc_c:
        mark_revoked(artifact_c["approval_id"], reason="second revoke", approvals_dir=approvals_dir)
    assert "REVOKED" in str(exc_c.value)

    after_c = load_approval(artifact_c["approval_id"], approvals_dir)
    assert after_c["status"] == "REVOKED"
    assert after_c["revoke_reason"] == "first revoke", (
        "REVOKED 재호출이 revoke_reason을 덮어씀"
    )

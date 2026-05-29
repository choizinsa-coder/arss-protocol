"""
lifecycle_manager.py — Approval Artifact Lifecycle Manager v1.0.0
EAG-1 (S164): Write Plane Restore

역할: approval artifact 상태 전이 전담
권한: 상태 변경 전용 (생성 / 삭제 금지)

상태 전이:
  ACTIVE → USED     : Tier1 write 성공 후 (mark_used)
  ACTIVE → EXPIRED  : TTL 초과 (mark_expired / check_and_expire)
  ACTIVE → REVOKED  : 수동 폐기 (mark_revoked)

Fail-Closed 계약:
  mark_used 실패 → set_write_plane_state(LOCKED_TIER1) 자동 진입
  (도미 설계 + 제니 TRUST-CHECK-02 PASS 근거)

Race Condition 방어:
  _lifecycle_lock으로 단일 스레드 전이 보장
  (제니 TRUST-ADVISORY: Lifecycle Manager 타이밍 갭 방어)
"""

import json
import os
import sys
import threading
from datetime import datetime, timezone

_ROOT = "/opt/arss/engine/arss-protocol"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.mcp_write.issuer import (
    APPROVALS_DIR,
    load_approval,
    compute_artifact_hash,
)
from tools.mcp_write.tier_router import set_write_plane_state, WritePlaneState

_lifecycle_lock = threading.Lock()


# ── 예외 ─────────────────────────────────────────────────────────────

class LifecycleError(Exception):
    """Lifecycle 전이 오류."""
    pass


# ── 내부 저장 헬퍼 ────────────────────────────────────────────────────

def _save_artifact(artifact: dict, approvals_dir: str = None) -> None:
    """artifact 변경 사항 저장. artifact_hash 자동 갱신."""
    artifact["artifact_hash"] = compute_artifact_hash(artifact)
    dir_ = approvals_dir or APPROVALS_DIR
    artifact_path = os.path.join(dir_, f"{artifact['approval_id']}.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)


# ── 공개 전이 API ─────────────────────────────────────────────────────

def mark_used(approval_id: str, approvals_dir: str = None) -> None:
    """
    ACTIVE → USED 전이.

    Fail-Closed: 전이 실패 시 Write Plane을 LOCKED_TIER1으로 자동 전환.
    (단일 실패 지점 방지 — 제니 TRUST-CHECK-06 근거)
    """
    with _lifecycle_lock:
        try:
            artifact = load_approval(approval_id, approvals_dir)
            if artifact["status"] != "ACTIVE":
                raise LifecycleError(
                    f"mark_used 불가: status={artifact['status']} (ACTIVE 필요)"
                )
            artifact["status"] = "USED"
            artifact["used_at"] = datetime.now(timezone.utc).isoformat()
            _save_artifact(artifact, approvals_dir)
        except Exception as e:
            # Fail-Closed: Lifecycle 갱신 실패 → LOCKED_TIER1 자동 진입
            try:
                set_write_plane_state(
                    WritePlaneState.LOCKED_TIER1,
                    reason=f"lifecycle mark_used failed: {e}",
                )
            except Exception:
                pass  # state 저장 실패 시에도 원래 예외 전파
            raise LifecycleError(
                f"FAIL-CLOSED: mark_used 실패 → LOCKED_TIER1 진입: {e}"
            ) from e


def mark_expired(approval_id: str, approvals_dir: str = None) -> None:
    """
    ACTIVE → EXPIRED 전이.
    TTL 만료 시 check_and_expire() 경유로 호출됨.
    """
    with _lifecycle_lock:
        artifact = load_approval(approval_id, approvals_dir)
        if artifact["status"] not in ("ACTIVE",):
            raise LifecycleError(
                f"mark_expired 불가: status={artifact['status']} (ACTIVE 필요)"
            )
        artifact["status"] = "EXPIRED"
        artifact["revoked_at"] = datetime.now(timezone.utc).isoformat()
        artifact["revoke_reason"] = "TTL_EXPIRED"
        _save_artifact(artifact, approvals_dir)


def mark_revoked(approval_id: str, reason: str = "", approvals_dir: str = None) -> None:
    """
    ACTIVE → REVOKED 전이.
    수동 폐기 경로 (비오님 직접 호출).
    """
    with _lifecycle_lock:
        artifact = load_approval(approval_id, approvals_dir)
        if artifact["status"] != "ACTIVE":
            raise LifecycleError(
                f"mark_revoked 불가: status={artifact['status']} (ACTIVE 필요)"
            )
        artifact["status"] = "REVOKED"
        artifact["revoked_at"] = datetime.now(timezone.utc).isoformat()
        artifact["revoke_reason"] = reason or "MANUAL_REVOKE"
        _save_artifact(artifact, approvals_dir)


def check_and_expire(approval_id: str, approvals_dir: str = None) -> bool:
    """
    TTL 확인 후 만료 처리.

    Returns:
        True  : 만료됨 (expires_at 초과 또는 이미 EXPIRED)
        False : 아직 유효
    """
    artifact = load_approval(approval_id, approvals_dir)
    if artifact["status"] == "EXPIRED":
        return True
    if artifact["status"] != "ACTIVE":
        return False

    expires_at_str = artifact.get("expires_at")
    if not expires_at_str:
        return False

    expires_at = datetime.fromisoformat(expires_at_str)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expires_at:
        mark_expired(approval_id, approvals_dir)
        return True
    return False

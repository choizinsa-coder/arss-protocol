"""
tier1_handler.py — Tier1 Write Handler v1.0.0
EAG-1 (S164): Write Plane Restore

역할: Tier1 전체 처리 흐름 담당
     (approval artifact 기반 — 비오 승인 필수)

처리 흐름:
  1. LOCK 상태 확인 (tier_router.route_request 경유)
  2. approval artifact 로드 (registry SSOT)
  3. 무결성 해시 검증 (artifact_hash)
  4. TTL 검증 (check_and_expire)
  5. single-use 검증 (status == ACTIVE)
  6. scope 검증 (target_path / content_hash)
  7. 파일 쓰기 (Fail-Closed)
  8. receipt 생성 (registry/mcp_write/receipts/)
  9. lifecycle_manager.mark_used 호출 (Fail-Closed → LOCKED_TIER1)
  10. audit 기록 (Fail-Closed)

거부 조건 (CONTRACT-04~09):
  - artifact 없음
  - TTL 만료
  - hash 불일치
  - scope 불일치
  - status != ACTIVE (재사용 시도)
  - receipt 생성 실패
  - audit 기록 실패
"""

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

_ROOT = "/opt/arss/engine/arss-protocol"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.mcp_write.issuer import load_approval, verify_artifact_integrity
from tools.mcp_write.lifecycle_manager import check_and_expire, mark_used, LifecycleError
from tools.mcp_write.tier_router import (
    set_write_plane_state,
    WritePlaneState,
    WritePlaneLockedError,
)

RECEIPTS_DIR = f"{_ROOT}/registry/mcp_write/receipts"
AUDIT_DIR = f"{_ROOT}/registry/mcp_write/audit"
AUDIT_FILE = f"{AUDIT_DIR}/mcp_write_audit.jsonl"


# ── 예외 ─────────────────────────────────────────────────────────────

class Tier1DenyError(Exception):
    """Tier1 처리 거부 — Fail-Closed."""
    def __init__(self, reason: str, contract: str = ""):
        self.reason = reason
        self.contract = contract
        super().__init__(f"TIER1 DENY [{contract}]: {reason}")


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _append_audit(event: dict, audit_file: str = None) -> None:
    """
    audit.jsonl에 이벤트 추가.
    Fail-Closed: 실패 시 LOCKED_TIER1 진입 + Tier1DenyError 발생.
    (CONTRACT-09)
    """
    target = audit_file or AUDIT_FILE
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        try:
            set_write_plane_state(
                WritePlaneState.LOCKED_TIER1,
                reason=f"tier1 audit append failed: {e}",
            )
        except Exception:
            pass
        raise Tier1DenyError(
            f"FAIL-CLOSED: audit 기록 실패 → write 실패 (CONTRACT-09): {e}",
            contract="CONTRACT-09",
        )


def _create_receipt(
    event_id: str,
    approval_id: str,
    target_path: str,
    result: str,
    failure_reason: str = None,
    receipts_dir: str = None,
) -> str:
    """
    receipt 생성 및 저장.
    Fail-Closed: 실패 시 LOCKED_TIER1 진입 + Tier1DenyError 발생.
    (CONTRACT-08)
    """
    dir_ = receipts_dir or RECEIPTS_DIR
    receipt_id = f"T1-RECEIPT-{uuid.uuid4().hex.upper()[:12]}"
    receipt = {
        "schema": "MCP_WRITE_RESULT_RECEIPT_v2",
        "receipt_id": receipt_id,
        "event_id": event_id,
        "approval_id": approval_id,
        "tier": "TIER1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "actor": "caddy",
        "target_path": os.path.abspath(target_path),
        "operation": "WRITE",
        "result": result,
        "status": "PENDING_BEO_REVIEW",
        "failure_reason": failure_reason,
    }
    os.makedirs(dir_, exist_ok=True)
    try:
        with open(os.path.join(dir_, f"{receipt_id}.json"), "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2, ensure_ascii=False)
    except Exception as e:
        try:
            set_write_plane_state(
                WritePlaneState.LOCKED_TIER1,
                reason=f"tier1 receipt creation failed: {e}",
            )
        except Exception:
            pass
        raise Tier1DenyError(
            f"FAIL-CLOSED: receipt 생성 실패 → write 실패 (CONTRACT-08): {e}",
            contract="CONTRACT-08",
        )
    return receipt_id


# ── 검증 단계 ─────────────────────────────────────────────────────────

def _verify_artifact(
    artifact: dict,
    target_path: str,
    content: str,
    approvals_dir: str = None,
) -> None:
    """
    approval artifact 전체 검증.
    CONTRACT-04~07 적용.
    """
    approval_id = artifact.get("approval_id", "UNKNOWN")

    # CONTRACT-04: artifact 존재 확인 (load_approval에서 이미 처리)

    # 무결성 해시 검증
    if not verify_artifact_integrity(artifact):
        raise Tier1DenyError(
            f"artifact_hash 무결성 실패: {approval_id}",
            contract="CONTRACT-06",
        )

    # CONTRACT-05: TTL 검증
    if check_and_expire(approval_id, approvals_dir):
        raise Tier1DenyError(
            f"approval TTL 만료: {approval_id}",
            contract="CONTRACT-05",
        )

    # CONTRACT-07: single-use 검증 (status == ACTIVE)
    if artifact.get("status") != "ACTIVE":
        raise Tier1DenyError(
            f"approval 재사용 시도: status={artifact.get('status')} (CONTRACT-07)",
            contract="CONTRACT-07",
        )

    # CONTRACT-06: scope 검증 — target_path
    scope = artifact.get("scope", {})
    artifact_path = os.path.abspath(scope.get("target_path", ""))
    request_path = os.path.abspath(target_path)
    if artifact_path != request_path:
        raise Tier1DenyError(
            f"scope target_path 불일치: artifact={artifact_path} request={request_path}",
            contract="CONTRACT-06",
        )

    # CONTRACT-06: scope 검증 — content_hash
    artifact_content_hash = scope.get("content_hash", "")
    request_content_hash = _content_hash(content)
    if artifact_content_hash != request_content_hash:
        raise Tier1DenyError(
            f"scope content_hash 불일치 (CONTRACT-06)",
            contract="CONTRACT-06",
        )


# ── 메인 처리 흐름 ────────────────────────────────────────────────────

def handle_tier1_write(
    approval_id: str,
    target_path: str,
    content: str,
    approvals_dir: str = None,
    receipts_dir: str = None,
    audit_file: str = None,
) -> dict:
    """
    Tier1 write 전체 흐름 실행.

    Args:
        approval_id  : approval artifact ID
        target_path  : 대상 파일 경로
        content      : 기록 내용
        approvals_dir: override (테스트용)
        receipts_dir : override (테스트용)
        audit_file   : override (테스트용)

    Returns:
        {ok: True, receipt_id, event_id, target_path}

    Raises:
        Tier1DenyError: 검증 실패 / Fail-Closed
        WritePlaneLockedError: 상태 잠금 (tier_router 경유)
        FileNotFoundError: artifact 없음 (CONTRACT-04)
    """
    event_id = uuid.uuid4().hex

    # CONTRACT-04: artifact 로드 (없으면 FileNotFoundError → 호출자가 Deny 처리)
    artifact = load_approval(approval_id, approvals_dir)

    # CONTRACT-04~07: 전체 검증
    _verify_artifact(artifact, target_path, content, approvals_dir)

    # 파일 쓰기 (Fail-Closed)
    try:
        parent = os.path.dirname(os.path.abspath(target_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        receipt_id = _create_receipt(
            event_id, approval_id, target_path,
            result="FAIL", failure_reason=str(e),
            receipts_dir=receipts_dir,
        )
        _append_audit({
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": "TIER1",
            "actor": "caddy",
            "operation": "WRITE",
            "target_path": os.path.abspath(target_path),
            "approval_id": approval_id,
            "result": "FAIL",
            "failure_reason": str(e),
            "receipt_id": receipt_id,
        }, audit_file)
        raise Tier1DenyError(f"파일 쓰기 실패: {e}")

    # CONTRACT-08: receipt 생성 (Fail-Closed)
    receipt_id = _create_receipt(
        event_id, approval_id, target_path,
        result="PASS",
        receipts_dir=receipts_dir,
    )

    # CONTRACT-07 집행: mark_used (Fail-Closed → LOCKED_TIER1)
    try:
        mark_used(approval_id, approvals_dir)
    except LifecycleError as e:
        # mark_used 내부에서 이미 LOCKED_TIER1 처리 완료
        _append_audit({
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": "TIER1",
            "actor": "caddy",
            "operation": "WRITE",
            "target_path": os.path.abspath(target_path),
            "approval_id": approval_id,
            "result": "PASS_BUT_LIFECYCLE_FAIL",
            "failure_reason": str(e),
            "receipt_id": receipt_id,
        }, audit_file)
        raise Tier1DenyError(str(e), contract="CONTRACT-07")

    # CONTRACT-09: audit 기록 (Fail-Closed)
    _append_audit({
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tier": "TIER1",
        "actor": "caddy",
        "operation": "WRITE",
        "target_path": os.path.abspath(target_path),
        "approval_id": approval_id,
        "result": "PASS",
        "failure_reason": None,
        "receipt_id": receipt_id,
    }, audit_file)

    return {
        "ok": True,
        "tier": "TIER1",
        "event_id": event_id,
        "receipt_id": receipt_id,
        "target_path": os.path.abspath(target_path),
    }

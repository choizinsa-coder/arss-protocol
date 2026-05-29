"""
issuer.py — Approval Artifact Issuer v1.0.0
EAG-1 (S164): Write Plane Restore

역할: approval artifact ACTIVE 상태로 생성 + registry/mcp_write/approvals/ 저장
권한: 생성 전용 (수정 / 삭제 금지 — 수정은 lifecycle_manager 전담)
Authority of Record: registry/mcp_write/approvals/{approval_id}.json

Artifact 계약:
  approval_id   : 고유 식별자
  issued_by     : 발급 요청자 (원칙상 "Beo")
  issued_at     : 발급 시각 (ISO 8601 UTC)
  expires_at    : 만료 시각
  scope         : target_path / content_hash / operation
  status        : ACTIVE (발급 직후)
  artifact_hash : 무결성 해시 (artifact_hash 필드 제외 후 SHA-256)
"""

import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

_ROOT = "/opt/arss/engine/arss-protocol"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

APPROVALS_DIR = f"{_ROOT}/registry/mcp_write/approvals"
DEFAULT_TTL_SECONDS = 600  # 10분


# ── 무결성 해시 ───────────────────────────────────────────────────────

def compute_artifact_hash(artifact: dict) -> str:
    """
    artifact_hash 필드를 제외한 artifact 전체의 SHA-256 해시 계산.
    Write Server는 이 함수로만 무결성 검증 수행.
    """
    body = {k: v for k, v in artifact.items() if k != "artifact_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# ── Artifact 생성 ─────────────────────────────────────────────────────

def issue_approval(
    issued_by: str,
    target_path: str,
    content: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict:
    """
    Approval Artifact 생성 및 registry 저장.

    Args:
        issued_by   : 발급 요청자 (원칙상 "Beo")
        target_path : 대상 파일 경로 (절대 경로로 정규화)
        content     : 기록할 내용 (content_hash 봉인용)
        ttl_seconds : TTL (초, 기본 600)

    Returns:
        생성된 approval artifact dict

    Raises:
        OSError: registry 쓰기 실패
    """
    approval_id = f"APPROVAL-{uuid.uuid4().hex.upper()[:16]}"
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(seconds=ttl_seconds)

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

    artifact = {
        "schema": "MCP_WRITE_APPROVAL_ARTIFACT_v1",
        "approval_id": approval_id,
        "issued_by": issued_by,
        "issued_at": issued_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": ttl_seconds,
        "scope": {
            "target_path": os.path.abspath(target_path),
            "content_hash": content_hash,
            "operation": "WRITE",
        },
        "status": "ACTIVE",
        "used_at": None,
        "revoked_at": None,
        "revoke_reason": None,
    }
    artifact["artifact_hash"] = compute_artifact_hash(artifact)

    os.makedirs(APPROVALS_DIR, exist_ok=True)
    artifact_path = os.path.join(APPROVALS_DIR, f"{approval_id}.json")
    with open(artifact_path, "w", encoding="utf-8") as f:
        json.dump(artifact, f, indent=2, ensure_ascii=False)

    return artifact


# ── Artifact 로드 ─────────────────────────────────────────────────────

def load_approval(approval_id: str, approvals_dir: str = None) -> dict:
    """
    Registry에서 approval artifact 로드.

    Raises:
        FileNotFoundError: artifact 없음 (= 미승인 상태)
        json.JSONDecodeError: artifact 손상
    """
    dir_ = approvals_dir or APPROVALS_DIR
    artifact_path = os.path.join(dir_, f"{approval_id}.json")
    if not os.path.exists(artifact_path):
        raise FileNotFoundError(
            f"approval artifact not found: {approval_id} — 미승인 상태"
        )
    with open(artifact_path, encoding="utf-8") as f:
        return json.load(f)


# ── 무결성 검증 ───────────────────────────────────────────────────────

def verify_artifact_integrity(artifact: dict) -> bool:
    """
    artifact_hash 무결성 검증.
    Returns: True if intact, False if tampered
    """
    stored_hash = artifact.get("artifact_hash")
    if not stored_hash:
        return False
    return compute_artifact_hash(artifact) == stored_hash

"""
mcp_approval_authority.py — Independent Approval Authority Module v1.0.0
PT-S136-MCP-WRITE-GATEKEEPER

[IMPORTANT] 비오(Beo)만 직접 실행 가능.
캐디(Caddy), 도미(Domi), 제니(Jeni), MCP Write Tool, Gatekeeper는 이 모듈로 approval artifact를 생성할 수 없음.

Usage (비오 직접 실행):
  python mcp_approval_authority.py --path <target_path> --ext <.md|.json|.txt> [--operation WRITE]
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# 공유 상수
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_config import (
    APPROVALS_DIR,
    ALLOWED_SANDBOX_PATHS,
    ALLOWED_EXTENSIONS,
    FORBIDDEN_PATH_PREFIXES,
    TOKEN_TTL,
)

MODULE_VERSION = "1.0.0"


def validate_path(target_path: str, allowed_paths: list = None) -> bool:
    """경로가 sandbox zone 내에 있는지 확인. forbidden 경로는 우선 차단."""
    if allowed_paths is None:
        allowed_paths = ALLOWED_SANDBOX_PATHS
    abs_path = os.path.abspath(target_path)
    # forbidden 우선
    for forbidden in FORBIDDEN_PATH_PREFIXES:
        if abs_path.startswith(os.path.abspath(forbidden)):
            return False
    # allowed 확인
    for allowed in allowed_paths:
        if abs_path.startswith(os.path.abspath(allowed)):
            return True
    return False


def validate_extension(target_path: str, ext: str) -> bool:
    """확장자가 허용 목록에 있는지 확인."""
    return ext in ALLOWED_EXTENSIONS and target_path.endswith(ext)


def compute_approval_hash(approval_body: dict) -> str:
    """approval artifact의 SHA-256 해시 계산 (approval_hash 필드 제외)."""
    body_without_hash = {k: v for k, v in approval_body.items() if k != "approval_hash"}
    body_str = json.dumps(body_without_hash, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body_str.encode("utf-8")).hexdigest()


def generate_approval(
    target_path: str,
    ext: str,
    operation: str = "WRITE",
    allowed_paths: list = None,
) -> dict:
    """
    EAG_WRITE_APPROVAL artifact 생성.
    approval_hash는 Independent Approval Authority Module이 계산.
    """
    approval_id = (
        f"EAG-WRITE-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
        f"{uuid.uuid4().hex[:8].upper()}"
    )
    approved_at = datetime.now(timezone.utc).isoformat()

    approval_body = {
        "type": "EAG_WRITE_APPROVAL",
        "approval_id": approval_id,
        "approved_by": "Beo",
        "approved_at": approved_at,
        "scope": {
            "target_path": os.path.abspath(target_path),
            "operation": operation,
            "extension": ext,
        },
        "ttl_seconds": TOKEN_TTL,
    }

    approval_body["approval_hash"] = compute_approval_hash(approval_body)
    return approval_body


def save_approval(approval: dict, approvals_dir: str = None) -> str:
    """approval artifact를 WRITE_APPROVAL_REGISTRY에 저장."""
    if approvals_dir is None:
        approvals_dir = APPROVALS_DIR
    os.makedirs(approvals_dir, exist_ok=True)
    approval_id = approval["approval_id"]
    file_path = os.path.join(approvals_dir, f"{approval_id}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(approval, f, indent=2, ensure_ascii=False)
    return file_path


def main():
    parser = argparse.ArgumentParser(
        description="MCP Write Approval Authority v{} — Beo only".format(MODULE_VERSION)
    )
    parser.add_argument("--path", required=True, help="Target file path (sandbox zone only)")
    parser.add_argument("--ext", required=True, help="File extension (.md, .json, .txt)")
    parser.add_argument("--operation", default="WRITE", help="Operation type (default: WRITE)")
    args = parser.parse_args()

    # 경로 검증
    if not validate_path(args.path):
        print(
            f"[APPROVAL_AUTHORITY] DENIED: path not in sandbox zone: {args.path}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 확장자 검증
    if not validate_extension(args.path, args.ext):
        print(
            f"[APPROVAL_AUTHORITY] DENIED: extension not allowed: {args.ext}",
            file=sys.stderr,
        )
        sys.exit(1)

    approval = generate_approval(args.path, args.ext, args.operation)
    file_path = save_approval(approval)

    print(f"[APPROVAL_AUTHORITY] ISSUED:        {approval['approval_id']}")
    print(f"[APPROVAL_AUTHORITY] STORED:        {file_path}")
    print(f"[APPROVAL_AUTHORITY] TTL:           {TOKEN_TTL}s (10 minutes)")
    print(f"[APPROVAL_AUTHORITY] approval_hash: {approval['approval_hash']}")
    print()
    print(json.dumps(approval, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

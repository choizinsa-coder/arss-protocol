"""
mcp_approval_authority.py — Independent Approval Authority Module v1.1.0
PT-S136-MCP-WRITE-GATEKEEPER

v1.1.0:
  - --content-file 필수 파라미터 추가 (expected_content_hash 자동 계산)
  - --previous-receipt-id 파라미터 추가 (unconfirmed receipt 확인 내재화)
  - unconfirmed receipt 존재 시 신규 approval 발급 거부

[IMPORTANT] 비오(Beo)만 직접 실행 가능.
캐디, 도미, 제니, MCP Write Tool, Gatekeeper는 approval artifact 생성 불가.

Usage:
  # 최초 approval 발급
  python mcp_approval_authority.py \\
    --path /opt/arss/engine/arss-protocol/tools/sandbox/report.md \\
    --ext .md \\
    --content-file /opt/arss/engine/arss-protocol/registry/mcp_write/intake/report.md

  # 이전 receipt 확인 포함 approval 발급
  python mcp_approval_authority.py \\
    --path /opt/arss/engine/arss-protocol/tools/sandbox/report.md \\
    --ext .md \\
    --content-file /opt/arss/engine/arss-protocol/registry/mcp_write/intake/report.md \\
    --previous-receipt-id MCP-WRITE-RECEIPT-XXXX
"""

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_config import (
    APPROVALS_DIR,
    RECEIPTS_DIR,
    ALLOWED_SANDBOX_PATHS,
    ALLOWED_EXTENSIONS,
    FORBIDDEN_PATH_PREFIXES,
    TOKEN_TTL,
)

MODULE_VERSION = "1.1.0"


# ── Path / Extension Validation ───────────────────────────────────────

def validate_path(target_path: str, allowed_paths: list = None) -> bool:
    if allowed_paths is None:
        allowed_paths = ALLOWED_SANDBOX_PATHS
    abs_path = os.path.abspath(target_path)
    for forbidden in FORBIDDEN_PATH_PREFIXES:
        if abs_path.startswith(os.path.abspath(forbidden)):
            return False
    for allowed in allowed_paths:
        if abs_path.startswith(os.path.abspath(allowed)):
            return True
    return False


def validate_extension(target_path: str, ext: str) -> bool:
    return ext in ALLOWED_EXTENSIONS and target_path.endswith(ext)


# ── Hash Utilities ────────────────────────────────────────────────────

def compute_approval_hash(approval_body: dict) -> str:
    body = {k: v for k, v in approval_body.items() if k != "approval_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def compute_file_hash(file_path: str) -> tuple:
    """파일 SHA-256 해시 및 크기 반환."""
    h = hashlib.sha256()
    size = 0
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def compute_receipt_hash(receipt_path: str) -> str:
    """receipt 파일 전체 바이트 SHA-256."""
    with open(receipt_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── Receipt Management ────────────────────────────────────────────────

def find_unconfirmed_receipts(receipts_dir: str = None) -> list:
    """PENDING_BEO_REVIEW 상태 receipt 목록 반환."""
    if receipts_dir is None:
        receipts_dir = RECEIPTS_DIR
    if not os.path.exists(receipts_dir):
        return []
    unconfirmed = []
    for fname in sorted(os.listdir(receipts_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(receipts_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                receipt = json.load(f)
            if receipt.get("status") == "PENDING_BEO_REVIEW":
                receipt["_file_path"] = fpath
                unconfirmed.append(receipt)
        except Exception:
            continue
    return unconfirmed


def build_receipt_confirmation(
    receipt_id: str, receipts_dir: str = None
) -> dict:
    """previous_receipt_confirmation 블록 생성."""
    if receipts_dir is None:
        receipts_dir = RECEIPTS_DIR
    receipt_file = os.path.join(receipts_dir, f"{receipt_id}.json")
    if not os.path.exists(receipt_file):
        raise FileNotFoundError(f"receipt file not found: {receipt_file}")
    receipt_hash = compute_receipt_hash(receipt_file)
    return {
        "previous_receipt_id": receipt_id,
        "previous_receipt_hash": receipt_hash,
        "confirmed_by": "Beo",
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "confirmation_meaning": (
            "previous write receipt reviewed and accepted "
            "before issuing this approval"
        ),
    }


# ── Approval Generation ───────────────────────────────────────────────

def generate_approval(
    target_path: str,
    ext: str,
    operation: str = "WRITE",
    allowed_paths: list = None,
    content_bytes: bytes = None,
    previous_receipt_id: str = None,
    receipts_dir: str = None,
) -> dict:
    """
    EAG_WRITE_APPROVAL artifact 생성.
    content_bytes 제공 시 expected_content_hash 포함.
    previous_receipt_id 제공 시 previous_receipt_confirmation 포함.
    """
    approval_id = (
        f"EAG-WRITE-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-"
        f"{uuid.uuid4().hex[:8].upper()}"
    )

    # content hash 계산
    expected_content_hash = None
    content_size_bytes = None
    if content_bytes is not None:
        expected_content_hash = hashlib.sha256(content_bytes).hexdigest()
        content_size_bytes = len(content_bytes)

    scope = {
        "target_path": os.path.abspath(target_path),
        "operation": operation,
        "extension": ext,
        "content_hash_algorithm": "SHA-256",
        "expected_content_hash": expected_content_hash,
        "content_size_bytes": content_size_bytes,
    }

    approval_body = {
        "type": "EAG_WRITE_APPROVAL",
        "approval_id": approval_id,
        "approved_by": "Beo",
        "approved_at": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "ttl_seconds": TOKEN_TTL,
    }

    # previous_receipt_confirmation 포함
    if previous_receipt_id:
        approval_body["previous_receipt_confirmation"] = build_receipt_confirmation(
            previous_receipt_id, receipts_dir
        )

    approval_body["approval_hash"] = compute_approval_hash(approval_body)
    return approval_body


def save_approval(approval: dict, approvals_dir: str = None) -> str:
    if approvals_dir is None:
        approvals_dir = APPROVALS_DIR
    os.makedirs(approvals_dir, exist_ok=True)
    file_path = os.path.join(approvals_dir, f"{approval['approval_id']}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(approval, f, indent=2, ensure_ascii=False)
    return file_path


# ── CLI Entry Point ───────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=f"MCP Write Approval Authority v{MODULE_VERSION} — Beo only"
    )
    parser.add_argument("--path", required=True, help="Target file path (sandbox zone only)")
    parser.add_argument("--ext", required=True, help="File extension (.md, .json, .txt)")
    parser.add_argument("--content-file", required=True, help="intake/ 경로의 content 파일")
    parser.add_argument("--operation", default="WRITE")
    parser.add_argument("--previous-receipt-id", default=None,
                        help="이전 unconfirmed receipt ID (확인 내재화용)")
    args = parser.parse_args()

    # 경로 검증
    if not validate_path(args.path):
        print(f"[APPROVAL_AUTHORITY] DENIED: path not in sandbox zone: {args.path}", file=sys.stderr)
        sys.exit(1)

    # 확장자 검증
    if not validate_extension(args.path, args.ext):
        print(f"[APPROVAL_AUTHORITY] DENIED: extension not allowed: {args.ext}", file=sys.stderr)
        sys.exit(1)

    # content-file 존재 확인
    if not os.path.exists(args.content_file):
        print(f"[APPROVAL_AUTHORITY] DENIED: content-file not found: {args.content_file}", file=sys.stderr)
        sys.exit(1)

    # unconfirmed receipt 확인
    unconfirmed = find_unconfirmed_receipts()
    if unconfirmed and not args.previous_receipt_id:
        print(
            f"[APPROVAL_AUTHORITY] DENIED: {len(unconfirmed)} unconfirmed receipt(s) exist.",
            file=sys.stderr,
        )
        for r in unconfirmed:
            print(f"  PENDING: {r['receipt_id']}", file=sys.stderr)
        print("  → --previous-receipt-id 로 직전 receipt ID를 제공하여 확인하십시오.", file=sys.stderr)
        sys.exit(1)

    # content hash 계산
    expected_hash, size = compute_file_hash(args.content_file)

    # approval 생성
    with open(args.content_file, "rb") as f:
        content_bytes = f.read()

    approval = generate_approval(
        target_path=args.path,
        ext=args.ext,
        operation=args.operation,
        content_bytes=content_bytes,
        previous_receipt_id=args.previous_receipt_id,
    )

    file_path = save_approval(approval)

    print(f"[APPROVAL_AUTHORITY] ISSUED:               {approval['approval_id']}")
    print(f"[APPROVAL_AUTHORITY] STORED:               {file_path}")
    print(f"[APPROVAL_AUTHORITY] TTL:                  {TOKEN_TTL}s (10 min hard / 8 min soft)")
    print(f"[APPROVAL_AUTHORITY] expected_content_hash:{expected_hash}")
    print(f"[APPROVAL_AUTHORITY] content_size_bytes:   {size}")
    if args.previous_receipt_id:
        print(f"[APPROVAL_AUTHORITY] CONFIRMED_RECEIPT:    {args.previous_receipt_id}")
    print()
    print(json.dumps(approval, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

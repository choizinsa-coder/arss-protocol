"""
setup_context_gateway.py
Context Gateway Phase A — 운영 전환 스크립트
SESSION_CONTEXT_POINTER.json + SESSION_CONTEXT_STALE_MANIFEST.json 신규 생성

실행: python3 setup_context_gateway.py
위치: /opt/arss/engine/arss-protocol/
"""

import sys
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.context_gateway.pointer_manager import (
    create_pointer,
    save_pointer,
    get_pointer_hash,
    validate_pointer,
)
from tools.context_gateway.manifest_manager import (
    build_fresh_manifest,
    save_manifest,
    validate_manifest,
    verify_close_bundle_consistency,
)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
KST = timezone(timedelta(hours=9))

# ── Step 1: canonical SESSION_CONTEXT 파일 확인 ────────────────────────────

SESSION = 150
FILE_ID = f"SESSION_CONTEXT_S{SESSION}_FINAL.json"
CTX_PATH = VPS_ROOT / FILE_ID

print(f"[1/5] canonical 파일 확인: {CTX_PATH}")
if not CTX_PATH.exists():
    print(f"  ERROR: {FILE_ID} 없음 — 배포 확인 필요")
    sys.exit(1)
print(f"  OK: {FILE_ID} 존재")

# ── Step 2: context_hash 계산 ─────────────────────────────────────────────

print("[2/5] context_hash 계산")
ctx_bytes = CTX_PATH.read_bytes()
context_hash = hashlib.sha256(ctx_bytes).hexdigest()
print(f"  context_hash: {context_hash}")

# ── Step 3: Pointer 생성 ──────────────────────────────────────────────────

print("[3/5] SESSION_CONTEXT_POINTER.json 생성")
pointer = create_pointer(
    session=SESSION,
    file_id=FILE_ID,
    context_path=CTX_PATH,
    updated_by="caddy",
    previous_pointer=None,  # 최초 생성 → GENESIS
)

is_valid, errors = validate_pointer(pointer)
if not is_valid:
    print(f"  ERROR: Pointer 검증 실패: {errors}")
    sys.exit(1)

pointer_path = save_pointer(pointer)
pointer_hash = get_pointer_hash(pointer)
print(f"  저장: {pointer_path}")
print(f"  pointer_hash: {pointer_hash}")

# ── Step 4: Manifest 생성 ─────────────────────────────────────────────────

print("[4/5] SESSION_CONTEXT_STALE_MANIFEST.json 생성")
manifest = build_fresh_manifest(
    session=SESSION,
    context_hash=context_hash,
    pointer_hash=pointer_hash,
)

# timestamp 동기화 (Close Bundle 3-way 일치)
pointer["updated_at"] = manifest["generated_at"]

# Pointer 재저장 (timestamp 동기화 반영)
pointer_path = save_pointer(pointer)

# Manifest pointer_hash 재계산 (timestamp 반영 후)
pointer_hash_final = get_pointer_hash(pointer)
manifest["pointer_hash"] = pointer_hash_final

is_valid, errors = validate_manifest(manifest)
if not is_valid:
    print(f"  ERROR: Manifest 검증 실패: {errors}")
    sys.exit(1)

manifest_path = save_manifest(manifest)
print(f"  저장: {manifest_path}")

# ── Step 5: Close Bundle 3-way 일치 검증 ─────────────────────────────────

print("[5/5] Close Bundle 3-way 일치 검증")
is_ok, errors = verify_close_bundle_consistency(
    session_count=SESSION,
    context_hash=context_hash,
    updated_at=pointer["updated_at"],
    pointer=pointer,
    manifest=manifest,
)

if not is_ok:
    print(f"  ERROR: Close Bundle 불일치: {errors}")
    sys.exit(1)

print("  3-way 일치 PASS")
print()
print("=" * 60)
print("Context Gateway Phase A 운영 전환 완료")
print(f"  SESSION_CONTEXT_POINTER.json  → {pointer_path}")
print(f"  SESSION_CONTEXT_STALE_MANIFEST.json → {manifest_path}")
print(f"  canonical: {FILE_ID}")
print(f"  context_hash: {context_hash[:16]}...")
print(f"  previous_pointer_hash: GENESIS")
print("=" * 60)

"""
_integrity.py
AIBA Context Gateway — Shared Integrity Utilities (IAPG-III 그룹 C)
SSOT: Domi 그룹 C Design / Jeni TRUST_READY / EAG-S355-IAPG-GROUPC-PHASE1-IMPL-001

역할:
  - final_file / SESSION_CONTEXT 정규화 hash 계산의 단일 기준(SSOT)
  - generator(쓰기전 검증)와 projection_builder(읽기후 검증)가 동일 정규화 사용
  - 계약 10/13: context_hash 필드 제외 + sort_keys=True + ensure_ascii=False -> SHA256
    (pointer_manager._compute_context_hash와 byte 동치)
  - 계약 13: fsync 보장 후 무결성 검증
"""
import json
import hashlib
import os
from pathlib import Path
from typing import Optional


def compute_normalized_hash(path: Path) -> Optional[str]:
    """
    계약 10/13 정규화 hash. pointer_manager._compute_context_hash와 byte 동치.
    JSON 파싱 -> context_hash 필드 제외 -> json.dumps(sort_keys=True, ensure_ascii=False) -> SHA256.
    파일 없거나 파싱 실패 시 None.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = {k: v for k, v in data.items() if k != "context_hash"}
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(serialized).hexdigest()
    except Exception:
        return None


def fsync_path(path: Path) -> bool:
    """계약 13: 파일 fsync 보장. 성공 True, 실패 False(비치명)."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def verify_final_file_integrity(final_path: Path, expected_hash: str) -> str:
    """
    계약 13: final_file 존재 + fsync + 정규화 hash 대조.
    반환: "INTEGRITY_OK" | "MISSING" | "HASH_MISMATCH"
    """
    if not final_path.exists():
        return "MISSING"
    fsync_path(final_path)
    actual = compute_normalized_hash(final_path)
    if actual is None:
        return "MISSING"
    if actual != expected_hash:
        return "HASH_MISMATCH"
    return "INTEGRITY_OK"

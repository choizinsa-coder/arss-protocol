"""
pointer_manager.py
AIBA Context Gateway — Pointer Manager
SSOT: Domi Phase A Design / EAG-1 Approved (S151)

역할:
  - SESSION_CONTEXT_POINTER.json 생성 / 갱신 / 검증 / 로드
  - canonical SESSION_CONTEXT 파일 결정 권위
  - glob/mtime 방식 대체
"""

import logging as _logging
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
POINTER_FILENAME = "SESSION_CONTEXT_POINTER.json"
POINTER_PATH = VPS_ROOT / POINTER_FILENAME

KST = timezone(timedelta(hours=9))

REQUIRED_POINTER_FIELDS = {
    "current_session",
    "current_file_id",
    "session_count",
    "context_hash",
    "updated_at",
    "updated_by",
    "previous_pointer_hash",
}


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _compute_hash(data: dict) -> str:
    """dict를 정렬된 JSON으로 직렬화 후 SHA256 반환"""
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(serialized).hexdigest()


def _compute_file_hash(path: Path) -> str:
    """파일 내용 SHA256 반환"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_context_hash(session_context_path: Path) -> Optional[str]:
    """SESSION_CONTEXT 파일 SHA256 반환. 파일 없으면 None."""
    try:
        return _compute_file_hash(session_context_path)
    except Exception:
        return None


# ── 공개 API ───────────────────────────────────────────────────────────────

def load_pointer() -> Optional[dict]:
    """
    POINTER_PATH에서 SESSION_CONTEXT_POINTER.json 로드.
    파일 없음 또는 파싱 실패 시 None 반환 (glob fallback 트리거).
    """
    if not POINTER_PATH.exists():
        return None
    try:
        with open(POINTER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_pointer(pointer: dict) -> tuple[bool, list[str]]:
    """
    Pointer 구조 검증.
    반환: (is_valid: bool, errors: list[str])
    """
    errors = []

    # 필수 필드 존재 여부
    for field in REQUIRED_POINTER_FIELDS:
        if field not in pointer:
            errors.append(f"MISSING_FIELD: {field}")

    if errors:
        return False, errors

    # current_session / session_count 일치 여부
    if pointer["current_session"] != pointer["session_count"]:
        errors.append(
            f"SESSION_MISMATCH: current_session={pointer['current_session']} "
            f"!= session_count={pointer['session_count']}"
        )

    # current_file_id 형식 확인
    file_id = pointer.get("current_file_id", "")
    if not file_id.startswith("SESSION_CONTEXT_S") or not file_id.endswith("_FINAL.json"):
        errors.append(f"INVALID_FILE_ID: {file_id}")

    return len(errors) == 0, errors


def verify_pointer_chain(pointer: dict) -> tuple[bool, str]:
    """
    previous_pointer_hash 체인 검증.
    이전 Pointer가 없으면 GENESIS로 허용.
    반환: (is_valid: bool, reason: str)
    """
    prev_hash = pointer.get("previous_pointer_hash", "")

    if prev_hash == "GENESIS":
        return True, "GENESIS_POINTER"

    # previous_pointer_hash가 있으면 실제 검증은 caller 책임
    # (이전 Pointer 파일을 별도 보존하는 구조가 필요하므로 현재는 형식만 검증)
    if not prev_hash or len(prev_hash) != 64:
        return False, f"INVALID_PREV_HASH: {prev_hash!r}"

    return True, "CHAIN_FORMAT_OK"


def resolve_canonical_path(pointer: dict) -> Optional[Path]:
    """
    Pointer에서 canonical SESSION_CONTEXT 파일 경로 반환.
    파일이 실제 존재하는지 확인.
    """
    file_id = pointer.get("current_file_id", "")
    candidate = VPS_ROOT / file_id
    if candidate.exists():
        return candidate
    return None


def verify_context_hash(pointer: dict, context_path: Path) -> tuple[bool, str]:
    """
    Pointer의 context_hash와 실제 파일 hash 일치 여부 검증.
    반환: (is_match: bool, reason: str)
    """
    expected = pointer.get("context_hash", "")
    actual = _compute_context_hash(context_path)
    if actual is None:
        return False, "CONTEXT_FILE_UNREADABLE"
    if expected != actual:
        return False, f"CONTEXT_HASH_MISMATCH: expected={expected[:8]}... actual={actual[:8]}..."
    return True, "CONTEXT_HASH_OK"


def create_pointer(
    session: int,
    file_id: str,
    context_path: Path,
    updated_by: str = "caddy",
    previous_pointer: Optional[dict] = None,
) -> dict:
    """
    신규 SESSION_CONTEXT_POINTER 생성.
    previous_pointer가 있으면 previous_pointer_hash 체인 연결.
    """
    context_hash = _compute_context_hash(context_path)
    if context_hash is None:
        raise FileNotFoundError(f"SESSION_CONTEXT 파일 없음: {context_path}")

    if previous_pointer is not None:
        prev_hash = _compute_hash(previous_pointer)
    else:
        prev_hash = "GENESIS"

    pointer = {
        "current_session": session,
        "current_file_id": file_id,
        "session_count": session,
        "context_hash": context_hash,
        "updated_at": datetime.now(KST).isoformat(),
        "updated_by": updated_by,
        "previous_pointer_hash": prev_hash,
    }
    return pointer


def save_pointer(pointer: dict) -> Path:
    """
    POINTER_PATH에 Pointer 저장.
    반환: 저장된 파일 경로
    """
    with open(POINTER_PATH, "w", encoding="utf-8") as f:
        json.dump(pointer, f, ensure_ascii=False, indent=2)
    return POINTER_PATH


def get_pointer_hash(pointer: dict) -> str:
    """Pointer dict SHA256 반환 (Manifest 연결용)"""
    return _compute_hash(pointer)


def load_canonical_context(fallback_glob: bool = True) -> tuple[Optional[dict], str]:
    """
    Pointer-first canonical SESSION_CONTEXT 로드.
    반환: (context_dict, source)
      source: "POINTER" | "GLOB_FALLBACK" | "NONE"

    1. POINTER 로드 시도
    2. POINTER 없으면 fallback_glob=True 시 기존 glob+mtime 방식
    3. 둘 다 실패 시 (None, "NONE")
    """
    pointer = load_pointer()

    if pointer is not None:
        is_valid, errors = validate_pointer(pointer)
        if is_valid:
            context_path = resolve_canonical_path(pointer)
            if context_path is not None:
                hash_ok, _ = verify_context_hash(pointer, context_path)
                if hash_ok:
                    try:
                        with open(context_path, "r", encoding="utf-8") as f:
                            return json.load(f), "POINTER"
                    except Exception as _rule6_e:
                        _logging.debug("RULE6 pointer_manager: %s", _rule6_e)

    # Pointer 실패 → glob fallback
    if fallback_glob:
        try:
            candidates = sorted(
                VPS_ROOT.glob("SESSION_CONTEXT_S*_FINAL.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                with open(candidates[0], "r", encoding="utf-8") as f:
                    return json.load(f), "GLOB_FALLBACK"
        except Exception as _rule6_e:
            _logging.debug("RULE6 pointer_manager: %s", _rule6_e)

    return None, "NONE"

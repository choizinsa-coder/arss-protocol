"""
pointer_manager.py
AIBA Context Gateway — Pointer Manager
SSOT: Domi Phase A Design / EAG-1 Approved (S151)
IAPG â¢ 정합: EAG-S351-IAPG-PROJECTION-INTEGRITY-001

역할:
  - SESSION_CONTEXT_POINTER.json 생성 / 갱신 / 검증 / 로드
  - canonical SESSION_CONTEXT 파일 결정 권위
  - 계약 17: reader(validate_pointer)를 실제 writer schema(4.0)에 정합
  - 계약 16: silent GLOB_FALLBACK(mtime 최신)의 canonical 채택 폐쇄
  - 계약 3: 원천 결정 실패를 명시적 failure source로 반환 (silent fallback 금지)
"""

import logging as _logging
import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from tools.context_gateway._integrity import fsync_path  # 계약13(그룹C)

# ── 상수 ───────────────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
POINTER_FILENAME = "SESSION_CONTEXT_POINTER.json"
POINTER_PATH = VPS_ROOT / POINTER_FILENAME

KST = timezone(timedelta(hours=9))

# 계약 17: reader→writer schema 정합.
# 실제 writer(SESSION CLOSE 생성기)가 산출하는 canonical schema = 4.0.
POINTER_SCHEMA_VERSION = "4.0"
MIN_COMPATIBLE_SCHEMA_VERSION = "4.0"

REQUIRED_POINTER_FIELDS = {
    "current_session",
    "canonical_file",
    "final_file",
    "chain_tip",
    "prev_tip",
    "context_hash",
    "generated_at",
    "schema_version",
}

# 계약 17: canonical seal 대상 필드 (POINTER 무결성 seal 조합).
POINTER_SEAL_FIELDS = ("context_hash", "current_session", "chain_tip", "prev_tip")


class PointerFailureClass:
    """계약 7: 원천 결정 실패 분류. silent fallback 금지 — 명시적 failure source로 반환."""
    POINTER_MISSING = "NONE_POINTER_MISSING"
    SCHEMA_INCOMPATIBLE = "NONE_SCHEMA_INCOMPATIBLE"
    POINTER_INVALID = "NONE_POINTER_INVALID"
    SOURCE_RESOLUTION_FAILURE = "NONE_SOURCE_RESOLUTION_FAILURE"
    HASH_MISMATCH = "NONE_HASH_MISMATCH"
    READ_ERROR = "NONE_READ_ERROR"
    TIMESTAMP_DESYNC = "NONE_TIMESTAMP_DESYNC"


# 계약 16: silent GLOB_FALLBACK로 canonical Authority를 채택하지 않는다.
# 정상 source(POINTER)만 canonical. 그 외에는 명시적 failure source.
CANONICAL_SOURCE_POINTER = "POINTER"


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _compute_hash(data: dict) -> str:
    """dict를 정렬된 JSON으로 직렬화 후 SHA256 반환"""
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(serialized).hexdigest()


def _compute_file_hash(path: Path) -> str:
    """\ud30c\uc77c \ub0b4\uc6a9 SHA256 \ubc18\ud658"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_context_hash(session_context_path: Path) -> Optional[str]:
    """
    SESSION_CONTEXT 파일 context_hash 계산.
    계약 10 / item 8.2: writer(session_close_generator)와 동일 방식.
      - JSON 파싱 → context_hash 필드 제외(자기 해시필드 self-ref 방지, adr_store 패턴 동일)
      - json.dumps(sort_keys=True, ensure_ascii=False) → SHA256.
    파일 없거나 파싱 실패 시 None.
    """
    try:
        with open(session_context_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = {k: v for k, v in data.items() if k != "context_hash"}
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(serialized).hexdigest()
    except Exception:
        return None


def _schema_compatible(schema_version) -> bool:
    """
    계약 17(C): schema_version이 MIN_COMPATIBLE_SCHEMA_VERSION 이상인지 (버전 진화 안전 처리).
    문자열 사전식 비교가 아닌 튜플 수치 비교. 파싱 실패 시 비호환.
    """
    try:
        cur = tuple(int(x) for x in str(schema_version).split("."))
        minv = tuple(int(x) for x in MIN_COMPATIBLE_SCHEMA_VERSION.split("."))
        return cur >= minv
    except Exception:
        return False


def _seal_verify(pointer: dict) -> bool:
    """계약 2(그룹 C): canonical seal 4필드 형식 무결성.
    context_hash=64 hex / current_session=int>0 / chain_tip=hex|GENESIS / prev_tip=hex|GENESIS."""
    ch = pointer.get("context_hash")
    if not isinstance(ch, str) or len(ch) != 64 or not all(c in "0123456789abcdef" for c in ch.lower()):
        return False
    cs = pointer.get("current_session")
    if not isinstance(cs, int) or isinstance(cs, bool) or cs <= 0:
        return False
    for _f in ("chain_tip", "prev_tip"):
        _v = pointer.get(_f)
        if _v == "GENESIS":
            continue
        if not isinstance(_v, str) or not _v.strip() or not all(c in "0123456789abcdef" for c in _v.lower()):
            return False
    return True


# ── 공개 API ───────────────────────────────────────────────────────────────────

def load_pointer() -> Optional[dict]:
    """
    POINTER_PATH에서 SESSION_CONTEXT_POINTER.json 로드.
    파일 없음 또는 파싱 실패 시 None 반환.
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
    Pointer 구조 검증 (계약 17: 실제 writer schema 4.0 기준).
    silent compatibility fallback 없음 — 불일치는 명시적 오류.
    반환: (is_valid: bool, errors: list[str])
    """
    errors = []

    # 필수 필드 존재 여부 (4.0 schema)
    for field in REQUIRED_POINTER_FIELDS:
        if field not in pointer:
            errors.append(f"MISSING_FIELD: {field}")

    if errors:
        return False, errors

    # 계약 17(C): schema_version 호환성 확인
    schema_version = pointer.get("schema_version", "")
    if not _schema_compatible(schema_version):
        errors.append(
            f"SCHEMA_INCOMPATIBLE: schema_version={schema_version!r} "
            f"< MIN {MIN_COMPATIBLE_SCHEMA_VERSION}"
        )

    # final_file 형식 확인 (canonical SESSION_CONTEXT_S..._FINAL.json)
    final_file = pointer.get("final_file", "")
    if not (isinstance(final_file, str)
            and final_file.startswith("SESSION_CONTEXT_S")
            and final_file.endswith("_FINAL.json")):
        errors.append(f"INVALID_FINAL_FILE: {final_file}")

    return len(errors) == 0, errors


def verify_pointer_chain(pointer: dict) -> tuple[bool, str]:
    """
    previous_pointer_hash 체인 검증 (레거시 헬퍼, canonical 로드 경로 미사용 — 무변경 유지).
    이전 Pointer가 없으면 GENESIS로 허용.
    반환: (is_valid: bool, reason: str)
    """
    prev_hash = pointer.get("previous_pointer_hash", "")

    if prev_hash == "GENESIS":
        return True, "GENESIS_POINTER"

    if not prev_hash or len(prev_hash) != 64:
        return False, f"INVALID_PREV_HASH: {prev_hash!r}"

    return True, "CHAIN_FORMAT_OK"


def resolve_canonical_path(pointer: dict) -> Optional[Path]:
    """
    Pointer에서 canonical SESSION_CONTEXT 파일 경로 반환 (계약 17: final_file 사용).
    파일이 실제 존재하는지 확인.
    """
    final_file = pointer.get("final_file", "")
    if not final_file:
        return None
    candidate = VPS_ROOT / final_file
    if candidate.exists():
        return candidate
    return None


def verify_context_hash(pointer: dict, context_path: Path) -> tuple[bool, str]:
    """
    Pointer의 context_hash와 SC_FINAL 무결성 지문 일치 여부 검증.
    계약 17(reader→writer 정합) + 계약 10(hash 패턴): writer와 동일 방식으로 재계산 후 대조.
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
    chain_tip: str = "GENESIS",
    prev_tip: str = "GENESIS",
) -> dict:
    """
    신규 SESSION_CONTEXT_POINTER 생성 (계약 17: 4.0 schema 산출).
    previous_pointer가 있으면 prev_tip을 이전 pointer hash로 연결.
    """
    context_hash = _compute_context_hash(context_path)
    if context_hash is None:
        raise FileNotFoundError(f"SESSION_CONTEXT 파일 없음: {context_path}")

    if previous_pointer is not None:
        prev_tip = _compute_hash(previous_pointer)

    pointer = {
        "current_session": session,
        "canonical_file": "SESSION_CONTEXT.json",
        "final_file": file_id,
        "chain_tip": chain_tip,
        "prev_tip": prev_tip,
        "context_hash": context_hash,
        "generated_at": datetime.now(KST).isoformat(),
        "schema_version": POINTER_SCHEMA_VERSION,
        "updated_by": updated_by,
    }
    return pointer


def save_pointer(pointer: dict) -> Path:
    """POINTER_PATH에 Pointer 저장. 반환: 저장된 파일 경로"""
    with open(POINTER_PATH, "w", encoding="utf-8") as f:
        json.dump(pointer, f, ensure_ascii=False, indent=2)
    return POINTER_PATH


def get_pointer_hash(pointer: dict) -> str:
    """Pointer dict SHA256 반환 (Manifest 연결용)"""
    return _compute_hash(pointer)


def diagnostic_glob_candidates() -> list:
    """
    계약 16: 진단·관측 목적의 glob 후보 목록.
    ⚠️ 이 결과를 canonical Authority로 채택하는 것은 금지된다(silent fallback 폐쇄).
    """
    try:
        return sorted(
            (str(p) for p in VPS_ROOT.glob("SESSION_CONTEXT_S*_FINAL.json")),
            reverse=True,
        )
    except Exception:
        return []


def load_canonical_context(fallback_glob: bool = True) -> tuple[Optional[dict], str]:
    """
    Pointer-first canonical SESSION_CONTEXT 로드.

    계약 3/16/17: silent GLOB_FALLBACK 폐쇄.
      - POINTER 결정 실패(부재/schema 비호환/무효/경로해상/hash 불일치)는
        mtime 최신 파일을 canonical로 조용히 채택하지 않고,
        명시적 failure source(NONE_*)를 반환한다.
      - fallback_glob 인자는 하위호환을 위해 유지되나,
        GLOB 결과를 canonical Authority로 채택하지 않는다(진단 전용).

    반환: (context_dict, source)
      source: "POINTER"
            | "NONE_POINTER_MISSING"
            | "NONE_SCHEMA_INCOMPATIBLE"
            | "NONE_POINTER_INVALID"
            | "NONE_SOURCE_RESOLUTION_FAILURE"
            | "NONE_HASH_MISMATCH"
            | "NONE_READ_ERROR"
    """
    pointer = load_pointer()
    if pointer is None:
        return None, PointerFailureClass.POINTER_MISSING

    is_valid, errors = validate_pointer(pointer)
    if not is_valid:
        if any(e.startswith("SCHEMA_INCOMPATIBLE") for e in errors):
            return None, PointerFailureClass.SCHEMA_INCOMPATIBLE
        return None, PointerFailureClass.POINTER_INVALID

    # 계약 2(그룹 C): canonical seal 4필드 형식 무결성
    if not _seal_verify(pointer):
        return None, PointerFailureClass.POINTER_INVALID

    # 계약 9: prev_tip 형식 검증 (git 짧은 해시 hex 또는 GENESIS)
    # 순방향 일관성은 WRITER(create_pointer)+CLOSE측 위임 — LOAD는 형식/존재만
    prev_tip = pointer.get("prev_tip")
    if prev_tip != "GENESIS":
        if (not isinstance(prev_tip, str) or not prev_tip.strip()
                or not all(c in "0123456789abcdef" for c in prev_tip.lower())):
            return None, PointerFailureClass.POINTER_INVALID

    context_path = resolve_canonical_path(pointer)
    if context_path is None:
        return None, PointerFailureClass.SOURCE_RESOLUTION_FAILURE

    # 계약 13(그룹 C): hash 검증 전 fsync 보장
    fsync_path(context_path)

    hash_ok, _ = verify_context_hash(pointer, context_path)
    if not hash_ok:
        return None, PointerFailureClass.HASH_MISMATCH

    try:
        with open(context_path, "r", encoding="utf-8") as f:
            return json.load(f), CANONICAL_SOURCE_POINTER
    except Exception as _rule6_e:
        _logging.debug("RULE6 pointer_manager: %s", _rule6_e)
        return None, PointerFailureClass.READ_ERROR

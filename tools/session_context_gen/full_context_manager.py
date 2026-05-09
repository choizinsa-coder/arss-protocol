ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
full_context_manager.py — Full Context Read/Write Manager
PT-S56-001 | AIBA Global Project
"""

import json
import shutil
from pathlib import Path
from typing import Any, Optional
from tools.session_context_gen.hash_utils import compute_hash, normalize_json

# ── Section Whitelist (하드코딩) ───────────────────────────────────────────────
# retrieval_engine.py ALLOWED_SECTIONS와 반드시 동기화
SECTION_WHITELIST = {
    "chain",
    "canonical_rules",
    "session_reentry",
    "agent_focus",
    "pending_tasks",
    "decisions",
    "automation_roadmap",
    "sync_metadata",
    "scp_standard_path",
    "wf_structure_confirmed",
}

# emergency full-load 플래그 — True 시 whitelist 우회 허용
_EMERGENCY_FULL_LOAD: bool = False


def set_emergency_full_load(flag: bool):
    """비오(Joshua) 명시적 승인 시에만 호출 허용."""
    global _EMERGENCY_FULL_LOAD
    _EMERGENCY_FULL_LOAD = flag


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────
def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: dict):
    path.write_text(normalize_json(data), encoding="utf-8")


# ── 공개 API ──────────────────────────────────────────────────────────────────
def read_section(full_ctx_path: Path, section: str) -> dict:
    """
    단일 섹션 읽기.
    반환: {"ok": True, "section": str, "data": Any}
          {"ok": False, "section": str, "error": str}
    """
    if section not in SECTION_WHITELIST and not _EMERGENCY_FULL_LOAD:
        return {
            "ok": False,
            "section": section,
            "error": f"SECTION_NOT_IN_WHITELIST: {section}",
        }

    ctx = _load_json(full_ctx_path)
    data = ctx.get(section)
    if data is None:
        return {
            "ok": False,
            "section": section,
            "error": f"SECTION_NOT_FOUND: {section}",
        }
    return {"ok": True, "section": section, "data": data}


def read_full(full_ctx_path: Path) -> dict:
    """
    전체 컨텍스트 로드.
    emergency_full_load 플래그 필요 또는 whitelist 전체 섹션만 반환.
    """
    ctx = _load_json(full_ctx_path)
    if _EMERGENCY_FULL_LOAD:
        return {"ok": True, "data": ctx, "mode": "emergency_full"}

    # 정상 모드: whitelist 섹션만 반환
    filtered = {k: v for k, v in ctx.items() if k in SECTION_WHITELIST}
    return {"ok": True, "data": filtered, "mode": "whitelist_filtered"}


def write_delta_merge(full_ctx_path: Path, delta: dict, backup: bool = True) -> dict:
    """
    delta를 full_ctx에 병합 후 저장.
    - backup=True: 수정 전 .bak 생성
    - delta 키는 SECTION_WHITELIST 내 항목만 허용
    - 반환: {"ok": True, "written_keys": [...], "artifact_hash": str}
             {"ok": False, "error": str}
    """
    # whitelist 검증
    forbidden = [k for k in delta if k not in SECTION_WHITELIST and not _EMERGENCY_FULL_LOAD]
    if forbidden:
        return {
            "ok": False,
            "error": f"DELTA_KEYS_NOT_IN_WHITELIST: {forbidden}",
        }

    ctx = _load_json(full_ctx_path)

    # 백업
    if backup:
        bak_path = full_ctx_path.with_suffix(".bak")
        shutil.copy2(full_ctx_path, bak_path)

    # 병합
    for k, v in delta.items():
        ctx[k] = v

    # 저장
    _save_json(full_ctx_path, ctx)

    artifact_hash = compute_hash(ctx)
    return {
        "ok": True,
        "written_keys": list(delta.keys()),
        "artifact_hash": artifact_hash,
        "backup_created": backup,
    }


def verify_integrity(full_ctx_path: Path, expected_hash: Optional[str] = None) -> dict:
    """
    full_ctx 파일 무결성 확인.
    expected_hash 제공 시 비교 검증.
    """
    try:
        ctx = _load_json(full_ctx_path)
    except Exception as e:
        return {"ok": False, "error": f"LOAD_FAILED: {e}"}

    actual_hash = compute_hash(ctx)
    result = {
        "ok": True,
        "artifact_hash": actual_hash,
        "path": str(full_ctx_path),
    }

    if expected_hash is not None:
        match = actual_hash == expected_hash
        result["hash_match"] = match
        if not match:
            result["ok"] = False
            result["error"] = f"HASH_MISMATCH: expected={expected_hash}, actual={actual_hash}"

    return result

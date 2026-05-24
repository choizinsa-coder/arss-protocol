"""
test_context_gateway_pointer.py
AIBA Context Gateway — pointer_manager 단위 테스트
PT-S150-CONTEXT-GATEWAY-ORCHESTRATION Phase A
"""

import sys
import json
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.context_gateway.pointer_manager import (
    validate_pointer,
    verify_pointer_chain,
    create_pointer,
    get_pointer_hash,
    verify_context_hash,
    load_canonical_context,
    REQUIRED_POINTER_FIELDS,
)


# ── 픽스처 헬퍼 ────────────────────────────────────────────────────────────

def _make_valid_pointer(session: int = 151, prev_hash: str = "GENESIS") -> dict:
    return {
        "current_session": session,
        "current_file_id": f"SESSION_CONTEXT_S{session}_FINAL.json",
        "session_count": session,
        "context_hash": "a" * 64,
        "updated_at": "2026-05-24T00:00:00+09:00",
        "updated_by": "caddy",
        "previous_pointer_hash": prev_hash,
    }


# ── T-1: 필수 필드 전체 존재 시 validate_pointer PASS ─────────────────────

def test_T1_validate_pointer_all_fields_pass():
    pointer = _make_valid_pointer()
    is_valid, errors = validate_pointer(pointer)
    assert is_valid, f"Expected PASS, errors={errors}"
    assert errors == []


# ── T-2: 필수 필드 누락 시 validate_pointer FAIL ──────────────────────────

def test_T2_validate_pointer_missing_field_fail():
    pointer = _make_valid_pointer()
    del pointer["context_hash"]
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("MISSING_FIELD" in e for e in errors)


# ── T-3: current_session != session_count 시 FAIL ─────────────────────────

def test_T3_validate_pointer_session_mismatch_fail():
    pointer = _make_valid_pointer()
    pointer["session_count"] = 999
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("SESSION_MISMATCH" in e for e in errors)


# ── T-4: current_file_id 형식 오류 시 FAIL ────────────────────────────────

def test_T4_validate_pointer_invalid_file_id_fail():
    pointer = _make_valid_pointer()
    pointer["current_file_id"] = "bad_file.json"
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("INVALID_FILE_ID" in e for e in errors)


# ── T-5: GENESIS previous_pointer_hash → chain PASS ──────────────────────

def test_T5_verify_pointer_chain_genesis_pass():
    pointer = _make_valid_pointer(prev_hash="GENESIS")
    is_valid, reason = verify_pointer_chain(pointer)
    assert is_valid
    assert reason == "GENESIS_POINTER"


# ── T-6: 유효한 64자 hex previous_pointer_hash → chain PASS ──────────────

def test_T6_verify_pointer_chain_valid_hash_pass():
    pointer = _make_valid_pointer(prev_hash="b" * 64)
    is_valid, reason = verify_pointer_chain(pointer)
    assert is_valid
    assert reason == "CHAIN_FORMAT_OK"


# ── T-7: 짧은 previous_pointer_hash → chain FAIL ─────────────────────────

def test_T7_verify_pointer_chain_short_hash_fail():
    pointer = _make_valid_pointer(prev_hash="abc")
    is_valid, reason = verify_pointer_chain(pointer)
    assert not is_valid
    assert "INVALID_PREV_HASH" in reason


# ── T-8: create_pointer GENESIS 생성 정상 ─────────────────────────────────

def test_T8_create_pointer_genesis():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"session_count": 151, "test": True}, f)
        tmp_path = Path(f.name)

    try:
        pointer = create_pointer(
            session=151,
            file_id="SESSION_CONTEXT_S151_FINAL.json",
            context_path=tmp_path,
            updated_by="caddy",
            previous_pointer=None,
        )
        assert pointer["current_session"] == 151
        assert pointer["previous_pointer_hash"] == "GENESIS"
        assert len(pointer["context_hash"]) == 64
        is_valid, errors = validate_pointer(pointer)
        assert is_valid, f"Pointer not valid: {errors}"
    finally:
        tmp_path.unlink(missing_ok=True)


# ── T-9: create_pointer 체인 연결 정상 ────────────────────────────────────

def test_T9_create_pointer_chain_link():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"session_count": 152}, f)
        tmp_path = Path(f.name)

    try:
        prev_pointer = _make_valid_pointer(session=151)
        pointer = create_pointer(
            session=152,
            file_id="SESSION_CONTEXT_S152_FINAL.json",
            context_path=tmp_path,
            previous_pointer=prev_pointer,
        )
        expected_prev_hash = get_pointer_hash(prev_pointer)
        assert pointer["previous_pointer_hash"] == expected_prev_hash
    finally:
        tmp_path.unlink(missing_ok=True)


# ── T-10: verify_context_hash 일치 → PASS ────────────────────────────────

def test_T10_verify_context_hash_match_pass():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        content = {"session_count": 151}
        json.dump(content, f)
        tmp_path = Path(f.name)

    try:
        actual_hash = hashlib.sha256(tmp_path.read_bytes()).hexdigest()
        pointer = _make_valid_pointer()
        pointer["context_hash"] = actual_hash
        is_match, reason = verify_context_hash(pointer, tmp_path)
        assert is_match, reason
    finally:
        tmp_path.unlink(missing_ok=True)


# ── T-11: verify_context_hash 불일치 → FAIL ──────────────────────────────

def test_T11_verify_context_hash_mismatch_fail():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"session_count": 151}, f)
        tmp_path = Path(f.name)

    try:
        pointer = _make_valid_pointer()
        pointer["context_hash"] = "c" * 64  # 의도적 불일치
        is_match, reason = verify_context_hash(pointer, tmp_path)
        assert not is_match
        assert "CONTEXT_HASH_MISMATCH" in reason
    finally:
        tmp_path.unlink(missing_ok=True)


# ── T-12: load_canonical_context Pointer 방식 성공 ────────────────────────

def test_T12_load_canonical_context_pointer_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        ctx_file = tmp_root / "SESSION_CONTEXT_S151_FINAL.json"
        ctx_content = {"session_count": 151, "system_name": "AIBA"}
        ctx_file.write_text(json.dumps(ctx_content), encoding="utf-8")

        ctx_hash = hashlib.sha256(ctx_file.read_bytes()).hexdigest()
        pointer = {
            "current_session": 151,
            "current_file_id": "SESSION_CONTEXT_S151_FINAL.json",
            "session_count": 151,
            "context_hash": ctx_hash,
            "updated_at": "2026-05-24T00:00:00+09:00",
            "updated_by": "caddy",
            "previous_pointer_hash": "GENESIS",
        }
        pointer_file = tmp_root / "SESSION_CONTEXT_POINTER.json"
        pointer_file.write_text(json.dumps(pointer), encoding="utf-8")

        with patch(
            "tools.context_gateway.pointer_manager.POINTER_PATH", pointer_file
        ), patch(
            "tools.context_gateway.pointer_manager.VPS_ROOT", tmp_root
        ):
            ctx, source = load_canonical_context(fallback_glob=False)

        assert source == "POINTER"
        assert ctx is not None
        assert ctx["session_count"] == 151


# ── T-13: Pointer 없을 때 glob fallback 동작 ─────────────────────────────

def test_T13_load_canonical_context_glob_fallback():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        ctx_file = tmp_root / "SESSION_CONTEXT_S151_FINAL.json"
        ctx_file.write_text(json.dumps({"session_count": 151}), encoding="utf-8")

        pointer_file = tmp_root / "SESSION_CONTEXT_POINTER.json"
        # Pointer 파일 미생성 (glob fallback 유도)

        with patch(
            "tools.context_gateway.pointer_manager.POINTER_PATH", pointer_file
        ), patch(
            "tools.context_gateway.pointer_manager.VPS_ROOT", tmp_root
        ):
            ctx, source = load_canonical_context(fallback_glob=True)

        assert source == "GLOB_FALLBACK"
        assert ctx is not None

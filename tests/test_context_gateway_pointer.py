"""
test_context_gateway_pointer.py
AIBA Context Gateway — pointer_manager 단위 테스트
PT-S150-CONTEXT-GATEWAY-ORCHESTRATION Phase A
IAPG â¢ 정합: EAG-S351-IAPG-PROJECTION-INTEGRITY-001 (계약 3/16/17)
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
    PointerFailureClass,
    POINTER_SCHEMA_VERSION,
)


def _make_valid_pointer(session: int = 151, prev_hash: str = "GENESIS") -> dict:
    return {
        "current_session": session,
        "canonical_file": "SESSION_CONTEXT.json",
        "final_file": f"SESSION_CONTEXT_S{session}_FINAL.json",
        "chain_tip": "5c7bf65",
        "prev_tip": "6e25072",
        "context_hash": "a" * 64,
        "generated_at": "2026-05-24T00:00:00+09:00",
        "schema_version": POINTER_SCHEMA_VERSION,
        "updated_by": "caddy",
        "previous_pointer_hash": prev_hash,
    }


def test_T1_validate_pointer_all_fields_pass():
    pointer = _make_valid_pointer()
    is_valid, errors = validate_pointer(pointer)
    assert is_valid, f"Expected PASS, errors={errors}"
    assert errors == []


def test_T2_validate_pointer_missing_field_fail():
    pointer = _make_valid_pointer()
    del pointer["context_hash"]
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("MISSING_FIELD" in e for e in errors)


def test_T3_validate_pointer_schema_incompatible_fail():
    pointer = _make_valid_pointer()
    pointer["schema_version"] = "3.0"
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("SCHEMA_INCOMPATIBLE" in e for e in errors)


def test_T4_validate_pointer_invalid_final_file_fail():
    pointer = _make_valid_pointer()
    pointer["final_file"] = "bad_file.json"
    is_valid, errors = validate_pointer(pointer)
    assert not is_valid
    assert any("INVALID_FINAL_FILE" in e for e in errors)


def test_T5_verify_pointer_chain_genesis_pass():
    pointer = _make_valid_pointer(prev_hash="GENESIS")
    is_valid, reason = verify_pointer_chain(pointer)
    assert is_valid
    assert reason == "GENESIS_POINTER"


def test_T6_verify_pointer_chain_valid_hash_pass():
    pointer = _make_valid_pointer(prev_hash="b" * 64)
    is_valid, reason = verify_pointer_chain(pointer)
    assert is_valid
    assert reason == "CHAIN_FORMAT_OK"


def test_T7_verify_pointer_chain_short_hash_fail():
    pointer = _make_valid_pointer(prev_hash="abc")
    is_valid, reason = verify_pointer_chain(pointer)
    assert not is_valid
    assert "INVALID_PREV_HASH" in reason


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
        assert pointer["prev_tip"] == "GENESIS"
        assert pointer["schema_version"] == POINTER_SCHEMA_VERSION
        assert len(pointer["context_hash"]) == 64
        is_valid, errors = validate_pointer(pointer)
        assert is_valid, f"Pointer not valid: {errors}"
    finally:
        tmp_path.unlink(missing_ok=True)


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
        expected_prev = get_pointer_hash(prev_pointer)
        assert pointer["prev_tip"] == expected_prev
    finally:
        tmp_path.unlink(missing_ok=True)


def test_T10_verify_context_hash_match_pass():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        content = {"session_count": 151}
        json.dump(content, f)
        tmp_path = Path(f.name)
    try:
        payload = {k: v for k, v in content.items() if k != "context_hash"}
        expected = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        pointer = _make_valid_pointer()
        pointer["context_hash"] = expected
        is_match, reason = verify_context_hash(pointer, tmp_path)
        assert is_match, reason
    finally:
        tmp_path.unlink(missing_ok=True)


def test_T11_verify_context_hash_mismatch_fail():
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"session_count": 151}, f)
        tmp_path = Path(f.name)
    try:
        pointer = _make_valid_pointer()
        pointer["context_hash"] = "c" * 64
        is_match, reason = verify_context_hash(pointer, tmp_path)
        assert not is_match
        assert "CONTEXT_HASH_MISMATCH" in reason
    finally:
        tmp_path.unlink(missing_ok=True)


def test_T12_load_canonical_context_pointer_success():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        ctx_file = tmp_root / "SESSION_CONTEXT_S151_FINAL.json"
        ctx_content = {"session_count": 151, "system_name": "AIBA"}
        ctx_file.write_text(json.dumps(ctx_content), encoding="utf-8")
        _ctx_data = json.loads(ctx_file.read_bytes().decode("utf-8"))
        _payload = {k: v for k, v in _ctx_data.items() if k != "context_hash"}
        ctx_hash = hashlib.sha256(
            json.dumps(_payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        pointer = {
            "current_session": 151,
            "canonical_file": "SESSION_CONTEXT.json",
            "final_file": "SESSION_CONTEXT_S151_FINAL.json",
            "chain_tip": "5c7bf65",
            "prev_tip": "6e25072",
            "context_hash": ctx_hash,
            "generated_at": "2026-05-24T00:00:00+09:00",
            "schema_version": POINTER_SCHEMA_VERSION,
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


def test_T13_load_canonical_context_no_silent_glob():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        ctx_file = tmp_root / "SESSION_CONTEXT_S151_FINAL.json"
        ctx_file.write_text(json.dumps({"session_count": 151}), encoding="utf-8")
        pointer_file = tmp_root / "SESSION_CONTEXT_POINTER.json"
        with patch(
            "tools.context_gateway.pointer_manager.POINTER_PATH", pointer_file
        ), patch(
            "tools.context_gateway.pointer_manager.VPS_ROOT", tmp_root
        ):
            ctx, source = load_canonical_context(fallback_glob=True)
        assert ctx is None
        assert source == PointerFailureClass.POINTER_MISSING
        assert source == "NONE_POINTER_MISSING"

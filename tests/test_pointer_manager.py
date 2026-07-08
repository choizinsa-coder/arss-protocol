import pytest
import json
from pathlib import Path
from unittest.mock import patch
from tools.context_gateway.pointer_manager import (
    validate_pointer,
    verify_pointer_chain,
    create_pointer,
    verify_context_hash,
    load_canonical_context,
    get_pointer_hash,
    REQUIRED_POINTER_FIELDS,
    PointerFailureClass,
    POINTER_SCHEMA_VERSION,
)


def _valid_pointer(session=100, file_id="SESSION_CONTEXT_S100_FINAL.json"):
    return {
        "current_session": session,
        "canonical_file": "SESSION_CONTEXT.json",
        "final_file": file_id,
        "chain_tip": "5c7bf65",
        "prev_tip": "6e25072",
        "context_hash": "a" * 64,
        "generated_at": "2026-05-30T10:00:00+09:00",
        "schema_version": POINTER_SCHEMA_VERSION,
        "updated_by": "caddy",
        "previous_pointer_hash": "GENESIS",
    }


def test_validate_pointer_valid():
    ok, errors = validate_pointer(_valid_pointer())
    assert ok is True
    assert errors == []


def test_validate_pointer_missing_field():
    p = _valid_pointer()
    del p["context_hash"]
    ok, errors = validate_pointer(p)
    assert ok is False
    assert any("context_hash" in e for e in errors)


def test_validate_pointer_schema_incompatible():
    p = _valid_pointer()
    p["schema_version"] = "3.0"
    ok, errors = validate_pointer(p)
    assert ok is False
    assert any("SCHEMA_INCOMPATIBLE" in e for e in errors)


def test_validate_pointer_invalid_final_file():
    p = _valid_pointer(file_id="bad_name.json")
    ok, errors = validate_pointer(p)
    assert ok is False
    assert any("INVALID_FINAL_FILE" in e for e in errors)


def test_verify_chain_genesis():
    p = _valid_pointer()
    ok, reason = verify_pointer_chain(p)
    assert ok is True
    assert "GENESIS" in reason


def test_verify_chain_valid_64char_hash():
    p = _valid_pointer()
    p["previous_pointer_hash"] = "b" * 64
    ok, reason = verify_pointer_chain(p)
    assert ok is True
    assert "CHAIN_FORMAT_OK" in reason


def test_verify_chain_invalid_short_hash():
    p = _valid_pointer()
    p["previous_pointer_hash"] = "tooshort"
    ok, reason = verify_pointer_chain(p)
    assert ok is False
    assert "INVALID_PREV_HASH" in reason


def test_verify_chain_empty_hash():
    p = _valid_pointer()
    p["previous_pointer_hash"] = ""
    ok, reason = verify_pointer_chain(p)
    assert ok is False


def test_create_pointer_success(tmp_path):
    f = tmp_path / "SESSION_CONTEXT_S100_FINAL.json"
    f.write_text('{"session_count": 100}', encoding="utf-8")
    p = create_pointer(100, "SESSION_CONTEXT_S100_FINAL.json", f)
    assert p["current_session"] == 100
    assert p["prev_tip"] == "GENESIS"
    assert p["schema_version"] == POINTER_SCHEMA_VERSION
    assert len(p["context_hash"]) == 64
    ok, errors = validate_pointer(p)
    assert ok is True, f"created pointer invalid: {errors}"


def test_create_pointer_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        create_pointer(100, "SESSION_CONTEXT_S100_FINAL.json",
                       tmp_path / "nonexistent.json")


def test_create_pointer_with_previous(tmp_path):
    f = tmp_path / "SESSION_CONTEXT_S100_FINAL.json"
    f.write_text('{"session_count": 100}', encoding="utf-8")
    prev = _valid_pointer()
    p = create_pointer(100, "SESSION_CONTEXT_S100_FINAL.json", f,
                       previous_pointer=prev)
    assert p["prev_tip"] != "GENESIS"
    assert p["prev_tip"] == get_pointer_hash(prev)


def test_verify_context_hash_match(tmp_path):
    import hashlib
    import json as _json
    ctx = {"test": True, "session_count": 100}
    f = tmp_path / "ctx.json"
    f.write_text(_json.dumps(ctx), encoding="utf-8")
    payload = {k: v for k, v in ctx.items() if k != "context_hash"}
    expected_hash = hashlib.sha256(
        _json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    p = _valid_pointer()
    p["context_hash"] = expected_hash
    ok, reason = verify_context_hash(p, f)
    assert ok is True
    assert "OK" in reason


def test_verify_context_hash_mismatch(tmp_path):
    import json as _json
    f = tmp_path / "ctx.json"
    f.write_text(_json.dumps({"test": True}), encoding="utf-8")
    p = _valid_pointer()
    p["context_hash"] = "wrong" + "0" * 59
    ok, reason = verify_context_hash(p, f)
    assert ok is False
    assert "MISMATCH" in reason


def test_verify_context_hash_file_missing(tmp_path):
    p = _valid_pointer()
    ok, reason = verify_context_hash(p, tmp_path / "no_file.json")
    assert ok is False
    assert "UNREADABLE" in reason


def test_get_pointer_hash_deterministic():
    p = _valid_pointer()
    h1 = get_pointer_hash(p)
    h2 = get_pointer_hash(p)
    assert h1 == h2
    assert len(h1) == 64


def test_load_canonical_context_returns_none_when_no_files():
    with patch("tools.context_gateway.pointer_manager.POINTER_PATH") as mock_p:
        mock_p.exists.return_value = False
        result, source = load_canonical_context(fallback_glob=True)
    assert result is None
    assert source == PointerFailureClass.POINTER_MISSING
    assert source == "NONE_POINTER_MISSING"

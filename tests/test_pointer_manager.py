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
)


def _valid_pointer(session=100, file_id="SESSION_CONTEXT_S100_FINAL.json"):
    return {
        "current_session": session,
        "current_file_id": file_id,
        "session_count": session,
        "context_hash": "a" * 64,
        "updated_at": "2026-05-30T10:00:00+09:00",
        "updated_by": "caddy",
        "previous_pointer_hash": "GENESIS",
    }


# ── validate_pointer ───────────────────────────────────────────
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


def test_validate_pointer_session_mismatch():
    p = _valid_pointer()
    p["session_count"] = 999   # current_session=100 != session_count=999
    ok, errors = validate_pointer(p)
    assert ok is False
    assert any("SESSION_MISMATCH" in e for e in errors)


def test_validate_pointer_invalid_file_id():
    p = _valid_pointer(file_id="bad_name.json")
    ok, errors = validate_pointer(p)
    assert ok is False
    assert any("INVALID_FILE_ID" in e for e in errors)


# ── verify_pointer_chain ───────────────────────────────────────
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


# ── create_pointer ─────────────────────────────────────────────
def test_create_pointer_success(tmp_path):
    f = tmp_path / "SESSION_CONTEXT_S100_FINAL.json"
    f.write_text('{"session_count": 100}', encoding="utf-8")
    p = create_pointer(100, "SESSION_CONTEXT_S100_FINAL.json", f)
    assert p["current_session"] == 100
    assert p["previous_pointer_hash"] == "GENESIS"
    assert len(p["context_hash"]) == 64


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
    assert p["previous_pointer_hash"] != "GENESIS"
    assert len(p["previous_pointer_hash"]) == 64


# ── verify_context_hash ────────────────────────────────────────
def test_verify_context_hash_match(tmp_path):
    import hashlib
    content = b'{"test": true}'
    f = tmp_path / "ctx.json"
    f.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()
    p = _valid_pointer()
    p["context_hash"] = expected_hash
    ok, reason = verify_context_hash(p, f)
    assert ok is True
    assert "OK" in reason


def test_verify_context_hash_mismatch(tmp_path):
    f = tmp_path / "ctx.json"
    f.write_bytes(b'{"test": true}')
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


# ── get_pointer_hash ───────────────────────────────────────────
def test_get_pointer_hash_deterministic():
    p = _valid_pointer()
    h1 = get_pointer_hash(p)
    h2 = get_pointer_hash(p)
    assert h1 == h2
    assert len(h1) == 64


# ── load_canonical_context ─────────────────────────────────────
def test_load_canonical_context_returns_none_when_no_files():
    with patch("tools.context_gateway.pointer_manager.POINTER_PATH") as mock_p:
        mock_p.exists.return_value = False
        with patch("tools.context_gateway.pointer_manager.VPS_ROOT") as mock_root:
            mock_root.glob.return_value = []
            result, source = load_canonical_context(fallback_glob=False)
    assert result is None
    assert source == "NONE"

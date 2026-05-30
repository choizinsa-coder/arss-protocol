import pytest
import time
from unittest.mock import patch
from tools.projection_builder import (
    check_ttl,
    invalidate_cache,
    get_stale_output,
    get_projection,
    _strip_forbidden,
    FORBIDDEN_FIELDS,
    TTL_SECONDS,
)


# ── _strip_forbidden ───────────────────────────────────────────
def test_strip_forbidden_removes_chain():
    data = {"session_count": 100, "chain": {"tip": "abc"}}
    result = _strip_forbidden(data)
    assert "chain" not in result
    assert result["session_count"] == 100


def test_strip_forbidden_removes_nested_hmac():
    data = {"outer": {"hmac": "secret", "value": 1}}
    result = _strip_forbidden(data)
    assert "hmac" not in result["outer"]
    assert result["outer"]["value"] == 1


def test_strip_forbidden_keeps_safe_keys():
    data = {"system_name": "AIBA", "session_count": 175}
    result = _strip_forbidden(data)
    assert result == data


def test_strip_forbidden_handles_list_of_dicts():
    data = {"items": [{"chain": "x", "id": 1}, {"id": 2}]}
    result = _strip_forbidden(data)
    assert "chain" not in result["items"][0]
    assert result["items"][0]["id"] == 1
    assert result["items"][1]["id"] == 2


def test_strip_forbidden_non_dict_passthrough():
    assert _strip_forbidden("string") == "string"


# ── check_ttl ─────────────────────────────────────────────────
def test_check_ttl_stale_flag():
    proj = {"stale": True, "generated_at": "2026-05-30T10:00:00+09:00"}
    assert check_ttl(proj) is True


def test_check_ttl_missing_generated_at():
    assert check_ttl({"stale": False}) is True


def test_check_ttl_malformed_timestamp():
    proj = {"stale": False, "generated_at": "not-a-date"}
    assert check_ttl(proj) is True


def test_check_ttl_fresh_projection():
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst).isoformat()
    proj = {"stale": False, "generated_at": now_kst}
    assert check_ttl(proj) is False


# ── invalidate_cache ───────────────────────────────────────────
def test_invalidate_cache_resets_state():
    from tools.projection_builder import _cache
    invalidate_cache()
    assert _cache["projection"] is None
    assert _cache["stale"] is True
    assert _cache["built_at_epoch"] == 0.0


# ── get_stale_output ───────────────────────────────────────────
def test_get_stale_output_returns_string():
    s = get_stale_output()
    assert isinstance(s, str)
    assert "STALE" in s


# ── get_projection — failure paths (mocked) ───────────────────
def test_get_projection_manifest_blocking():
    """Manifest blocking_flags 활성화 → blocked=True 응답"""
    with patch("tools.projection_builder._check_manifest_blocking",
               return_value=(True, "MANIFEST_BLOCKING: ['STALE_PROJECTION']")):
        proj, is_stale = get_projection()
    assert is_stale is True
    assert proj.get("blocked") is True
    assert proj.get("execution_allowed") is False


def test_get_projection_load_failure_returns_stale():
    """SESSION_CONTEXT 로드 실패 → stale 응답"""
    invalidate_cache()
    with patch("tools.projection_builder._check_manifest_blocking",
               return_value=(False, "MANIFEST_OK")):
        with patch("tools.projection_builder.load_canonical_context",
                   return_value=(None, "NONE")):
            proj, is_stale = get_projection()
    assert is_stale is True
    assert proj.get("projection_refresh_failed") is True


def test_get_projection_success():
    """정상 로드 → stale=False, data 존재"""
    invalidate_cache()
    raw = {"session_count": 175, "system_name": "AIBA"}
    with patch("tools.projection_builder._check_manifest_blocking",
               return_value=(False, "MANIFEST_OK")):
        with patch("tools.projection_builder.load_canonical_context",
                   return_value=(raw, "POINTER")):
            proj, is_stale = get_projection()
    assert is_stale is False
    assert proj.get("stale") is False
    assert proj.get("execution_allowed") is False
    assert "data" in proj


def test_get_projection_role_domi():
    """domi role → role 필드 확인"""
    invalidate_cache()
    raw = {"session_count": 175, "system_name": "AIBA", "agent_focus": {}}
    with patch("tools.projection_builder._check_manifest_blocking",
               return_value=(False, "MANIFEST_OK")):
        with patch("tools.projection_builder.load_canonical_context",
                   return_value=(raw, "POINTER")):
            proj, _ = get_projection(role="domi")
    assert proj.get("role") == "domi"

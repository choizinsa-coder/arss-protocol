import pytest
from tools.context_gateway.manifest_manager import (
    validate_manifest,
    create_manifest,
    is_blocking,
    get_blocking_flags,
    verify_close_bundle_consistency,
    build_fresh_manifest,
    build_stale_manifest,
    get_manifest_hash,
    FLAG_STALE_PROJECTION,
    VALID_PROJECTION_STATUSES,
)


def _valid_manifest(session=100, projection_status="fresh", blocking_flags=None):
    return {
        "manifest_session": session,
        "context_hash": "a" * 64,
        "pointer_hash": "b" * 64,
        "generated_at": "2026-05-30T10:00:00+09:00",
        "generated_by": "caddy",
        "projection_status": projection_status,
        "shard_status_summary": {},
        "role_projection_status": {"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        "blocking_flags": blocking_flags or [],
    }


# ── validate_manifest ──────────────────────────────────────────
def test_validate_manifest_valid():
    ok, errors = validate_manifest(_valid_manifest())
    assert ok is True
    assert errors == []


def test_validate_manifest_missing_field():
    m = _valid_manifest()
    del m["context_hash"]
    ok, errors = validate_manifest(m)
    assert ok is False
    assert any("context_hash" in e for e in errors)


def test_validate_manifest_invalid_projection_status():
    m = _valid_manifest(projection_status="INVALID_STATUS")
    ok, errors = validate_manifest(m)
    assert ok is False
    assert any("INVALID_PROJECTION_STATUS" in e for e in errors)


def test_validate_manifest_unknown_agent():
    m = _valid_manifest()
    m["role_projection_status"]["unknown_bot"] = "fresh"
    ok, errors = validate_manifest(m)
    assert ok is False
    assert any("UNKNOWN_AGENT" in e for e in errors)


def test_validate_manifest_blocking_flags_not_list():
    m = _valid_manifest()
    m["blocking_flags"] = "not_a_list"
    ok, errors = validate_manifest(m)
    assert ok is False
    assert any("blocking_flags" in e for e in errors)


# ── create_manifest ────────────────────────────────────────────
def test_create_manifest_success():
    m = create_manifest(
        session=100,
        context_hash="a" * 64,
        pointer_hash="b" * 64,
        projection_status="fresh",
        shard_status_summary={},
        role_projection_status={"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        blocking_flags=[],
    )
    assert m["manifest_session"] == 100
    assert m["write_back_allowed"] is False   # Phase A 불변 제약


def test_create_manifest_invalid_status_raises():
    with pytest.raises(ValueError, match="Invalid projection_status"):
        create_manifest(
            session=100, context_hash="a" * 64, pointer_hash="b" * 64,
            projection_status="BAD_STATUS",
            shard_status_summary={}, role_projection_status={},
            blocking_flags=[],
        )


def test_create_manifest_unknown_agent_raises():
    with pytest.raises(ValueError, match="Unknown agent"):
        create_manifest(
            session=100, context_hash="a" * 64, pointer_hash="b" * 64,
            projection_status="fresh",
            shard_status_summary={},
            role_projection_status={"hacker": "fresh"},
            blocking_flags=[],
        )


# ── is_blocking / get_blocking_flags ──────────────────────────
def test_is_blocking_false_when_empty():
    assert is_blocking(_valid_manifest()) is False


def test_is_blocking_true_when_flagged():
    m = _valid_manifest(blocking_flags=[FLAG_STALE_PROJECTION])
    assert is_blocking(m) is True


def test_get_blocking_flags_empty():
    assert get_blocking_flags(_valid_manifest()) == []


def test_get_blocking_flags_returns_list():
    m = _valid_manifest(blocking_flags=[FLAG_STALE_PROJECTION])
    flags = get_blocking_flags(m)
    assert FLAG_STALE_PROJECTION in flags


# ── verify_close_bundle_consistency ───────────────────────────
def _make_pointer(session=100, context_hash="a" * 64, updated_at="2026-05-30T10:00:00+09:00"):
    return {
        "current_session": session,
        "context_hash": context_hash,
        "updated_at": updated_at,
    }


def test_close_bundle_consistent():
    ts = "2026-05-30T10:00:00+09:00"
    ptr = _make_pointer(100, "a" * 64, ts)
    mft = _valid_manifest(100)
    mft["context_hash"] = "a" * 64
    mft["generated_at"] = ts
    ok, errors = verify_close_bundle_consistency(100, "a" * 64, ts, ptr, mft)
    assert ok is True
    assert errors == []


def test_close_bundle_session_mismatch():
    ts = "2026-05-30T10:00:00+09:00"
    ptr = _make_pointer(999, "a" * 64, ts)  # pointer session=999
    mft = _valid_manifest(100)
    mft["generated_at"] = ts
    ok, errors = verify_close_bundle_consistency(100, "a" * 64, ts, ptr, mft)
    assert ok is False
    assert any("SESSION_COUNT_MISMATCH" in e for e in errors)


def test_close_bundle_hash_mismatch():
    ts = "2026-05-30T10:00:00+09:00"
    ptr = _make_pointer(100, "wrong" * 12 + "0000", ts)
    mft = _valid_manifest(100)
    mft["context_hash"] = "a" * 64
    mft["generated_at"] = ts
    ok, errors = verify_close_bundle_consistency(100, "a" * 64, ts, ptr, mft)
    assert ok is False
    assert any("CONTEXT_HASH_MISMATCH" in e for e in errors)


# ── build helpers ──────────────────────────────────────────────
def test_build_fresh_manifest_no_blocking():
    m = build_fresh_manifest(100, "a" * 64, "b" * 64)
    assert m["projection_status"] == "fresh"
    assert m["blocking_flags"] == []
    assert is_blocking(m) is False


def test_build_stale_manifest_has_blocking_flag():
    m = build_stale_manifest(100, "a" * 64, "b" * 64, reason="test stale")
    assert m["projection_status"] == "stale"
    assert FLAG_STALE_PROJECTION in m["blocking_flags"]
    assert is_blocking(m) is True


# ── get_manifest_hash ──────────────────────────────────────────
def test_get_manifest_hash_deterministic():
    m = _valid_manifest()
    h1 = get_manifest_hash(m)
    h2 = get_manifest_hash(m)
    assert h1 == h2
    assert len(h1) == 64

import pytest
from tools.context_gateway.manifest_manager import (
    validate_manifest,
    create_manifest,
    is_blocking,
    get_blocking_flags,
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
    assert m["write_back_allowed"] is False


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


def test_get_manifest_hash_deterministic():
    m = _valid_manifest()
    h1 = get_manifest_hash(m)
    h2 = get_manifest_hash(m)
    assert h1 == h2
    assert len(h1) == 64

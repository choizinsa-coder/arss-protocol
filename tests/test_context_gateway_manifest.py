"""
test_context_gateway_manifest.py
AIBA Context Gateway - manifest_manager
[S356] verify_close_bundle_consistency tests removed (Q7 deprecate)
"""
import logging as _logging
import sys
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.context_gateway.manifest_manager import (
    validate_manifest,
    create_manifest,
    build_fresh_manifest,
    build_stale_manifest,
    is_blocking,
    get_blocking_flags,
    FLAG_STALE_PROJECTION,
    STALE_BLOCKED_ACTIONS,
)


def _make_valid_manifest(session=151, status="fresh"):
    return {
        "manifest_session": session,
        "context_hash": "a" * 64,
        "pointer_hash": "b" * 64,
        "generated_at": "2026-05-24T00:00:00+09:00",
        "generated_by": "caddy",
        "projection_status": status,
        "shard_status_summary": {"overall": status},
        "role_projection_status": {"domi": status, "jeni": status, "caddy": "fresh"},
        "blocking_flags": [],
        "stale_blocked_actions": [],
        "phase": "A",
        "write_back_allowed": False,
    }


def test_T1_validate_manifest_all_fields_pass():
    manifest = _make_valid_manifest()
    is_valid, errors = validate_manifest(manifest)
    assert is_valid, f"Expected PASS, errors={errors}"


def test_T2_validate_manifest_missing_field_fail():
    manifest = _make_valid_manifest()
    del manifest["projection_status"]
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("MISSING_FIELD" in e for e in errors)


def test_T3_validate_manifest_invalid_status_fail():
    manifest = _make_valid_manifest()
    manifest["projection_status"] = "INVALID_VALUE"
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("INVALID_PROJECTION_STATUS" in e for e in errors)


def test_T4_validate_manifest_unknown_agent_fail():
    manifest = _make_valid_manifest()
    manifest["role_projection_status"]["unknown_agent"] = "fresh"
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("UNKNOWN_AGENT" in e for e in errors)


def test_T5_create_manifest_write_back_forbidden():
    manifest = create_manifest(
        session=151, context_hash="a"*64, pointer_hash="b"*64,
        projection_status="fresh", shard_status_summary={},
        role_projection_status={"domi":"fresh","jeni":"fresh","caddy":"fresh"},
        blocking_flags=[],
    )
    assert manifest["write_back_allowed"] is False
    assert manifest["phase"] == "A"


def test_T6_build_fresh_manifest_no_blocking():
    manifest = build_fresh_manifest(session=151, context_hash="a"*64, pointer_hash="b"*64)
    assert manifest["blocking_flags"] == []
    assert not is_blocking(manifest)
    assert manifest["projection_status"] == "fresh"


def test_T7_build_stale_manifest_blocking_flags():
    manifest = build_stale_manifest(
        session=151, context_hash="a"*64, pointer_hash="b"*64,
        reason="context_hash mismatch"
    )
    assert is_blocking(manifest)
    assert FLAG_STALE_PROJECTION in get_blocking_flags(manifest)
    assert manifest["projection_status"] == "stale"
    assert STALE_BLOCKED_ACTIONS == manifest["stale_blocked_actions"]


def test_T8_build_stale_manifest_role_status():
    manifest = build_stale_manifest(
        session=151, context_hash="a"*64, pointer_hash="b"*64,
        reason="test", stale_agents=["domi","jeni"]
    )
    rps = manifest["role_projection_status"]
    assert rps["domi"] == "stale"
    assert rps["jeni"] == "stale"
    assert rps["caddy"] == "fresh"


def test_T13_create_manifest_invalid_status_raises():
    try:
        create_manifest(
            session=151, context_hash="a"*64, pointer_hash="b"*64,
            projection_status="INVALID", shard_status_summary={},
            role_projection_status={"domi":"fresh","jeni":"fresh","caddy":"fresh"},
            blocking_flags=[],
        )
        assert False, "Expected ValueError"
    except ValueError as e:
        _logging.debug("RULE6: %s", e)

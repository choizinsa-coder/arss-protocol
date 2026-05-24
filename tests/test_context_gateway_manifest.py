"""
test_context_gateway_manifest.py
AIBA Context Gateway — manifest_manager 단위 테스트
PT-S150-CONTEXT-GATEWAY-ORCHESTRATION Phase A
"""

import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.context_gateway.manifest_manager import (
    validate_manifest,
    create_manifest,
    build_fresh_manifest,
    build_stale_manifest,
    verify_close_bundle_consistency,
    is_blocking,
    get_blocking_flags,
    FLAG_STALE_PROJECTION,
    STALE_BLOCKED_ACTIONS,
)


# ── 픽스처 헬퍼 ────────────────────────────────────────────────────────────

def _make_valid_manifest(session: int = 151, status: str = "fresh") -> dict:
    return {
        "manifest_session": session,
        "context_hash": "a" * 64,
        "pointer_hash": "b" * 64,
        "generated_at": "2026-05-24T00:00:00+09:00",
        "generated_by": "caddy",
        "projection_status": status,
        "shard_status_summary": {"overall": status},
        "role_projection_status": {
            "domi": status,
            "jeni": status,
            "caddy": "fresh",
        },
        "blocking_flags": [],
        "stale_blocked_actions": [],
        "phase": "A",
        "write_back_allowed": False,
    }


# ── T-1: 필수 필드 전체 존재 시 validate_manifest PASS ───────────────────

def test_T1_validate_manifest_all_fields_pass():
    manifest = _make_valid_manifest()
    is_valid, errors = validate_manifest(manifest)
    assert is_valid, f"Expected PASS, errors={errors}"


# ── T-2: 필수 필드 누락 시 FAIL ───────────────────────────────────────────

def test_T2_validate_manifest_missing_field_fail():
    manifest = _make_valid_manifest()
    del manifest["projection_status"]
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("MISSING_FIELD" in e for e in errors)


# ── T-3: 허용되지 않은 projection_status 값 FAIL ─────────────────────────

def test_T3_validate_manifest_invalid_status_fail():
    manifest = _make_valid_manifest()
    manifest["projection_status"] = "INVALID_VALUE"
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("INVALID_PROJECTION_STATUS" in e for e in errors)


# ── T-4: 알 수 없는 에이전트 키 FAIL ─────────────────────────────────────

def test_T4_validate_manifest_unknown_agent_fail():
    manifest = _make_valid_manifest()
    manifest["role_projection_status"]["unknown_agent"] = "fresh"
    is_valid, errors = validate_manifest(manifest)
    assert not is_valid
    assert any("UNKNOWN_AGENT" in e for e in errors)


# ── T-5: write_back_allowed = False 불변 확인 ────────────────────────────

def test_T5_create_manifest_write_back_forbidden():
    manifest = create_manifest(
        session=151,
        context_hash="a" * 64,
        pointer_hash="b" * 64,
        projection_status="fresh",
        shard_status_summary={},
        role_projection_status={"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        blocking_flags=[],
    )
    assert manifest["write_back_allowed"] is False
    assert manifest["phase"] == "A"


# ── T-6: build_fresh_manifest blocking_flags 비어있음 ────────────────────

def test_T6_build_fresh_manifest_no_blocking():
    manifest = build_fresh_manifest(
        session=151,
        context_hash="a" * 64,
        pointer_hash="b" * 64,
    )
    assert manifest["blocking_flags"] == []
    assert not is_blocking(manifest)
    assert manifest["projection_status"] == "fresh"


# ── T-7: build_stale_manifest blocking_flags 존재 ────────────────────────

def test_T7_build_stale_manifest_blocking_flags():
    manifest = build_stale_manifest(
        session=151,
        context_hash="a" * 64,
        pointer_hash="b" * 64,
        reason="context_hash mismatch",
    )
    assert is_blocking(manifest)
    assert FLAG_STALE_PROJECTION in get_blocking_flags(manifest)
    assert manifest["projection_status"] == "stale"
    assert STALE_BLOCKED_ACTIONS == manifest["stale_blocked_actions"]


# ── T-8: build_stale_manifest 도미·제니 stale, 캐디 fresh ────────────────

def test_T8_build_stale_manifest_role_status():
    manifest = build_stale_manifest(
        session=151,
        context_hash="a" * 64,
        pointer_hash="b" * 64,
        reason="test",
        stale_agents=["domi", "jeni"],
    )
    rps = manifest["role_projection_status"]
    assert rps["domi"] == "stale"
    assert rps["jeni"] == "stale"
    assert rps["caddy"] == "fresh"


# ── T-9: Close Bundle 3-way 일치 PASS ────────────────────────────────────

def test_T9_verify_close_bundle_consistency_pass():
    ctx_hash = "a" * 64
    ptr_hash = "b" * 64
    ts = "2026-05-24T00:00:00+09:00"

    pointer = {
        "current_session": 151,
        "context_hash": ctx_hash,
        "updated_at": ts,
    }
    manifest = {
        "manifest_session": 151,
        "context_hash": ctx_hash,
        "generated_at": ts,
    }
    is_ok, errors = verify_close_bundle_consistency(
        session_count=151,
        context_hash=ctx_hash,
        updated_at=ts,
        pointer=pointer,
        manifest=manifest,
    )
    assert is_ok, f"Expected PASS, errors={errors}"


# ── T-10: Close Bundle session_count 불일치 FAIL ─────────────────────────

def test_T10_verify_close_bundle_session_mismatch_fail():
    ctx_hash = "a" * 64
    ts = "2026-05-24T00:00:00+09:00"
    pointer = {"current_session": 999, "context_hash": ctx_hash, "updated_at": ts}
    manifest = {"manifest_session": 151, "context_hash": ctx_hash, "generated_at": ts}
    is_ok, errors = verify_close_bundle_consistency(
        session_count=151,
        context_hash=ctx_hash,
        updated_at=ts,
        pointer=pointer,
        manifest=manifest,
    )
    assert not is_ok
    assert any("SESSION_COUNT_MISMATCH" in e for e in errors)


# ── T-11: Close Bundle context_hash 불일치 FAIL ───────────────────────────

def test_T11_verify_close_bundle_hash_mismatch_fail():
    ts = "2026-05-24T00:00:00+09:00"
    pointer = {"current_session": 151, "context_hash": "a" * 64, "updated_at": ts}
    manifest = {"manifest_session": 151, "context_hash": "b" * 64, "generated_at": ts}
    is_ok, errors = verify_close_bundle_consistency(
        session_count=151,
        context_hash="a" * 64,
        updated_at=ts,
        pointer=pointer,
        manifest=manifest,
    )
    assert not is_ok
    assert any("CONTEXT_HASH_MISMATCH" in e for e in errors)


# ── T-12: Close Bundle timestamp 불일치 FAIL ─────────────────────────────

def test_T12_verify_close_bundle_timestamp_mismatch_fail():
    ctx_hash = "a" * 64
    pointer = {"current_session": 151, "context_hash": ctx_hash, "updated_at": "2026-05-24T00:00:00+09:00"}
    manifest = {"manifest_session": 151, "context_hash": ctx_hash, "generated_at": "2026-05-24T01:00:00+09:00"}
    is_ok, errors = verify_close_bundle_consistency(
        session_count=151,
        context_hash=ctx_hash,
        updated_at="2026-05-24T00:00:00+09:00",
        pointer=pointer,
        manifest=manifest,
    )
    assert not is_ok
    assert any("TIMESTAMP_MISMATCH" in e for e in errors)


# ── T-13: invalid projection_status로 create_manifest 호출 시 ValueError ─

def test_T13_create_manifest_invalid_status_raises():
    try:
        create_manifest(
            session=151,
            context_hash="a" * 64,
            pointer_hash="b" * 64,
            projection_status="INVALID",
            shard_status_summary={},
            role_projection_status={"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
            blocking_flags=[],
        )
        assert False, "Expected ValueError"
    except ValueError:
        pass

# RULE-8 ASSERTION — S181 Batch-12A
# Module: mcp_containment_state
# Task: P4-C4 Phase-beta Batch-12A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import json
import os
import tempfile
import pytest


def _get_module():
    from tools.mcp import mcp_containment_state as m
    return m


def test_cs_load_state_file_missing_returns_fail_closed():
    """CS-1: 파일 없음 → containment_active=True (FAIL_CLOSED)."""
    m = _get_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_path = os.path.join(tmpdir, "nonexistent.json")
        state = m.load_state(missing_path)
    assert state["containment_active"] is True


def test_cs_load_state_parse_error_returns_fail_closed():
    """CS-2: JSON parse 오류 → containment_active=True (FAIL_CLOSED)."""
    m = _get_module()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False) as f:
        f.write("{ invalid json !!!")
        tmp_path = f.name
    try:
        state = m.load_state(tmp_path)
        assert state["containment_active"] is True
    finally:
        os.unlink(tmp_path)


def test_cs_load_state_missing_required_keys_returns_fail_closed():
    """CS-3: 필수 키 누락 → containment_active=True (FAIL_CLOSED)."""
    m = _get_module()
    incomplete = {"containment_active": False}  # 필수 키 다수 누락
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False) as f:
        json.dump(incomplete, f)
        tmp_path = f.name
    try:
        state = m.load_state(tmp_path)
        assert state["containment_active"] is True
    finally:
        os.unlink(tmp_path)


def test_cs_enter_containment_invalid_trigger_normalized_to_unknown():
    """CS-4: VALID_TRIGGER_IDS 외 trigger_id → 'UNKNOWN'으로 정규화."""
    m = _get_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = os.path.join(tmpdir, "state.json")
        result = m.enter_containment("HC-T-INVALID_999", path=tmp_path)
    assert result["trigger_id"] == "UNKNOWN"
    assert result["containment_active"] is True


def test_cs_is_active_file_missing_returns_true():
    """CS-5: 파일 없음 → is_active=True (FAIL_CLOSED 보장)."""
    m = _get_module()
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_path = os.path.join(tmpdir, "nonexistent.json")
        result = m.is_active(missing_path)
    assert result is True

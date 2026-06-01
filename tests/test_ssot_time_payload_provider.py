# tests/test_ssot_time_payload_provider.py
# RULE-8 Batch-13A — S182
# 설계: 도미 BRIEFING-CADDY-S182-BATCH13-DOMI-DESIGN-1
# EAG: EAG-S182-BATCH13A (비오 승인)
# 대상: tools/delta_context/ssot_time_payload_provider.py
#
# Assertion 우선순위: Guard Condition → Contract Integrity → State Result → Happy Path

import json
import pytest
from unittest.mock import patch, MagicMock
import urllib.error

from tools.delta_context.ssot_time_payload_provider import (
    _validate_response,
    provide,
    REQUIRED_SOURCE,
    REQUIRED_TIMEZONE,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def valid_response():
    return {
        "ok": True,
        "source": REQUIRED_SOURCE,
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "2026-06-01T12:00:00+09:00",
        "epoch_ms": 1748739600000,
    }


# ── P1: Guard Condition ────────────────────────────────────────────────────

def test_validate_response_ok_false_raises():
    """ok=False → SYSTEM_TIME_ENDPOINT_MISSING ValueError"""
    data = {
        "ok": False,
        "error_code": "CLOCK_UNAVAILABLE",
        "source": REQUIRED_SOURCE,
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "2026-06-01T12:00:00+09:00",
        "epoch_ms": 1748739600000,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_ENDPOINT_MISSING"):
        _validate_response(data)


def test_validate_response_source_mismatch_raises():
    """source 불일치 → SYSTEM_TIME_SOURCE_MISMATCH ValueError"""
    data = {
        "ok": True,
        "source": "WRONG_SOURCE",
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "2026-06-01T12:00:00+09:00",
        "epoch_ms": 1748739600000,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_SOURCE_MISMATCH"):
        _validate_response(data)


def test_validate_response_timezone_mismatch_raises():
    """timezone 불일치 → SYSTEM_TIME_TIMEZONE_MISMATCH ValueError"""
    data = {
        "ok": True,
        "source": REQUIRED_SOURCE,
        "timezone": "UTC",
        "timestamp": "2026-06-01T12:00:00+09:00",
        "epoch_ms": 1748739600000,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_TIMEZONE_MISMATCH"):
        _validate_response(data)


def test_validate_response_timestamp_missing_raises():
    """timestamp 누락 → SYSTEM_TIME_INVALID_TIMESTAMP ValueError"""
    data = {
        "ok": True,
        "source": REQUIRED_SOURCE,
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "",
        "epoch_ms": 1748739600000,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_INVALID_TIMESTAMP"):
        _validate_response(data)


def test_validate_response_timestamp_no_tz_marker_raises():
    """+09:00 / Z 미포함 timestamp → SYSTEM_TIME_INVALID_TIMESTAMP ValueError"""
    data = {
        "ok": True,
        "source": REQUIRED_SOURCE,
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "2026-06-01T12:00:00",
        "epoch_ms": 1748739600000,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_INVALID_TIMESTAMP"):
        _validate_response(data)


def test_validate_response_epoch_ms_invalid_raises():
    """epoch_ms 비정수 → SYSTEM_TIME_EPOCH_INVALID ValueError"""
    data = {
        "ok": True,
        "source": REQUIRED_SOURCE,
        "timezone": REQUIRED_TIMEZONE,
        "timestamp": "2026-06-01T12:00:00+09:00",
        "epoch_ms": -1,
    }
    with pytest.raises(ValueError, match="SYSTEM_TIME_EPOCH_INVALID"):
        _validate_response(data)


# ── P2: Contract Integrity ─────────────────────────────────────────────────

def test_provide_endpoint_unreachable_raises(valid_response):
    """endpoint 미응답 → RuntimeError: SYSTEM_TIME_ENDPOINT_MISSING"""
    with patch(
        "tools.delta_context.ssot_time_payload_provider.urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(RuntimeError, match="SYSTEM_TIME_ENDPOINT_MISSING"):
            provide()


def test_provide_returns_session_time_lock_shape(valid_response):
    """정상 응답 → session_time_lock 키 및 필수 필드 반환"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(valid_response).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch(
        "tools.delta_context.ssot_time_payload_provider.urllib.request.urlopen",
        return_value=mock_resp,
    ):
        result = provide()

    assert "session_time_lock" in result
    stl = result["session_time_lock"]
    assert stl["source"] == REQUIRED_SOURCE
    assert stl["timezone"] == REQUIRED_TIMEZONE
    assert stl["epoch_ms"] == valid_response["epoch_ms"]
    assert stl["generated_at"] == valid_response["timestamp"]
    assert stl["observed_at"] == valid_response["timestamp"]

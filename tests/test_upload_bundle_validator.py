"""
test_upload_bundle_validator.py
PT-S81-ARCH-001 Phase 2 Step 8 — pytest

Test cases:
TC-1: normal bundle (BOOT + RUNTIME) → PASS
TC-2: FULL present in bundle → FAIL
TC-3: BOOT missing → FAIL
TC-4: RUNTIME missing → FAIL
TC-5: both BOOT and RUNTIME missing → FAIL
TC-6: FULL + BOOT + RUNTIME → FAIL (FULL forbidden)
TC-7: empty bundle → FAIL
TC-8: extra unknown key allowed if required present, FULL absent → PASS
TC-9: FULL only → FAIL (missing required + forbidden present)
TC-10: BOOT + RUNTIME + extra_key (no FULL) → PASS
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.upload_bundle_validator import validate_upload_bundle


# TC-1: 정상 번들 — BOOT + RUNTIME → PASS
def test_tc1_normal_bundle_pass():
    bundle = {
        "SESSION_BOOT": {"session_count": 90},
        "SESSION_STATE_RUNTIME": {"chain": {"tip": "abc123"}},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is True
    assert result["errors"] == []
    assert result["missing_required"] == []
    assert result["forbidden_found"] == []


# TC-2: FULL present → FAIL
def test_tc2_full_present_fail():
    bundle = {
        "SESSION_BOOT": {},
        "SESSION_STATE_RUNTIME": {},
        "SESSION_CONTEXT_FULL": {"everything": True},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_CONTEXT_FULL" in result["forbidden_found"]
    assert any("forbidden" in e for e in result["errors"])


# TC-3: BOOT missing → FAIL
def test_tc3_boot_missing_fail():
    bundle = {
        "SESSION_STATE_RUNTIME": {},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_BOOT" in result["missing_required"]


# TC-4: RUNTIME missing → FAIL
def test_tc4_runtime_missing_fail():
    bundle = {
        "SESSION_BOOT": {},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_STATE_RUNTIME" in result["missing_required"]


# TC-5: 둘 다 missing → FAIL
def test_tc5_both_missing_fail():
    bundle = {"OTHER_KEY": {}}
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_BOOT" in result["missing_required"]
    assert "SESSION_STATE_RUNTIME" in result["missing_required"]


# TC-6: FULL + BOOT + RUNTIME → FAIL (FULL forbidden)
def test_tc6_full_with_required_still_fail():
    bundle = {
        "SESSION_BOOT": {},
        "SESSION_STATE_RUNTIME": {},
        "SESSION_CONTEXT_FULL": {},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_CONTEXT_FULL" in result["forbidden_found"]
    assert result["missing_required"] == []


# TC-7: 빈 번들 → FAIL
def test_tc7_empty_bundle_fail():
    bundle = {}
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_BOOT" in result["missing_required"]
    assert "SESSION_STATE_RUNTIME" in result["missing_required"]


# TC-8: 추가 키 허용 (FULL 없음) → PASS
def test_tc8_extra_key_allowed_pass():
    bundle = {
        "SESSION_BOOT": {},
        "SESSION_STATE_RUNTIME": {},
        "SESSION_LOG_ARCHIVE": {},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is True
    assert result["errors"] == []


# TC-9: FULL only → FAIL (missing required + forbidden)
def test_tc9_full_only_fail():
    bundle = {
        "SESSION_CONTEXT_FULL": {},
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is False
    assert "SESSION_BOOT" in result["missing_required"]
    assert "SESSION_STATE_RUNTIME" in result["missing_required"]
    assert "SESSION_CONTEXT_FULL" in result["forbidden_found"]


# TC-10: BOOT + RUNTIME + extra (no FULL) → PASS
def test_tc10_boot_runtime_extra_pass():
    bundle = {
        "SESSION_BOOT": {"session_count": 90},
        "SESSION_STATE_RUNTIME": {"chain": {"tip": "eeffbe71"}},
        "SESSION_DELTA": [],
    }
    result = validate_upload_bundle(bundle)
    assert result["pass"] is True
    assert result["forbidden_found"] == []
    assert result["missing_required"] == []

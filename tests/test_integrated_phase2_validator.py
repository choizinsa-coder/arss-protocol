"""
test_integrated_phase2_validator.py
PT-S81-ARCH-001 Phase 2 Step 10 — pytest

TC-1: 전체 validator PASS + extra checks PASS → PASS / commit_allowed=true
TC-2: validator 하나 FAIL → commit_allowed=false
TC-3: validator 하나 MISSING → FAIL
TC-4: extra check FAIL → commit_allowed=false
TC-5: extra check MISSING → FAIL
TC-6: 전체 FAIL → commit_allowed=false
TC-7: runtime_pair_hash_match=false → FAIL
TC-8: no_circular_hash_binding=false → FAIL
TC-9: no_full_in_normal_upload_bundle=false → FAIL
TC-10: runtime_first_generation=false → FAIL
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.integrated_phase2_validator import validate_integrated


def _all_pass_validators():
    return {
        "generation_pipeline": {"pass": True},
        "pair_validator": {"pass": True},
        "boundary_enforcement_validator": {"pass": True},
        "upload_bundle_validator": {"pass": True},
        "agent_injection_manifest": {"pass": True},
    }


def _all_pass_checks():
    return {
        "runtime_first_generation": True,
        "runtime_pair_hash_match": True,
        "no_circular_hash_binding": True,
        "no_full_in_normal_upload_bundle": True,
    }


# TC-1: 전체 PASS → PASS / commit_allowed=true
def test_tc1_all_pass():
    result = validate_integrated(_all_pass_validators(), _all_pass_checks())
    assert result["pass"] is True
    assert result["commit_allowed"] is True
    assert result["errors"] == []


# TC-2: validator 하나 FAIL → commit_allowed=false
def test_tc2_one_validator_fail():
    v = _all_pass_validators()
    v["pair_validator"] = {"pass": False}
    result = validate_integrated(v, _all_pass_checks())
    assert result["pass"] is False
    assert result["commit_allowed"] is False
    assert any("pair_validator" in e for e in result["errors"])


# TC-3: validator MISSING → FAIL
def test_tc3_validator_missing():
    v = _all_pass_validators()
    del v["upload_bundle_validator"]
    result = validate_integrated(v, _all_pass_checks())
    assert result["pass"] is False
    assert result["commit_allowed"] is False
    assert any("upload_bundle_validator" in e for e in result["errors"])


# TC-4: extra check FAIL → commit_allowed=false
def test_tc4_extra_check_fail():
    c = _all_pass_checks()
    c["runtime_first_generation"] = False
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-5: extra check MISSING → FAIL
def test_tc5_extra_check_missing():
    c = _all_pass_checks()
    del c["no_circular_hash_binding"]
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert result["commit_allowed"] is False
    assert any("no_circular_hash_binding" in e for e in result["errors"])


# TC-6: 전체 FAIL → commit_allowed=false
def test_tc6_all_fail():
    v = {k: {"pass": False} for k in _all_pass_validators()}
    c = {k: False for k in _all_pass_checks()}
    result = validate_integrated(v, c)
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-7: runtime_pair_hash_match=false → FAIL
def test_tc7_runtime_pair_hash_fail():
    c = _all_pass_checks()
    c["runtime_pair_hash_match"] = False
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert any("runtime_pair_hash_match" in e for e in result["errors"])


# TC-8: no_circular_hash_binding=false → FAIL
def test_tc8_circular_hash_fail():
    c = _all_pass_checks()
    c["no_circular_hash_binding"] = False
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert any("no_circular_hash_binding" in e for e in result["errors"])


# TC-9: no_full_in_normal_upload_bundle=false → FAIL
def test_tc9_full_in_bundle_fail():
    c = _all_pass_checks()
    c["no_full_in_normal_upload_bundle"] = False
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert any("no_full_in_normal_upload_bundle" in e for e in result["errors"])


# TC-10: runtime_first_generation=false → FAIL
def test_tc10_runtime_first_fail():
    c = _all_pass_checks()
    c["runtime_first_generation"] = False
    result = validate_integrated(_all_pass_validators(), c)
    assert result["pass"] is False
    assert any("runtime_first_generation" in e for e in result["errors"])

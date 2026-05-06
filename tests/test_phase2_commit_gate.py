"""
test_phase2_commit_gate.py
PT-S81-ARCH-001 Phase 2 Step 11 — pytest

TC-1: 통합 검증 ALL PASS → commit_allowed=true
TC-2: integrated pass=false → commit_allowed=false
TC-3: commit_allowed=false → gate FAIL
TC-4: results에 MISSING 항목 → gate FAIL
TC-5: results에 FAIL 항목 → gate FAIL
TC-6: validator 키 누락(results 없음) → gate FAIL
TC-7: 잘못된 validator 출처 → gate FAIL
TC-8: 부분 결과(일부 validator 누락) → gate FAIL
TC-9: integrated_result가 dict 아닌 경우 → gate FAIL
TC-10: 전체 results PASS + pass/commit_allowed=true → gate PASS
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.integrated_phase2_validator import validate_integrated
from tools.session_context_gen.phase2_commit_gate import check_commit_gate


def _full_pass_integrated():
    validators = {
        "generation_pipeline": {"pass": True},
        "pair_validator": {"pass": True},
        "boundary_enforcement_validator": {"pass": True},
        "upload_bundle_validator": {"pass": True},
        "agent_injection_manifest": {"pass": True},
    }
    checks = {
        "runtime_first_generation": True,
        "runtime_pair_hash_match": True,
        "no_circular_hash_binding": True,
        "no_full_in_normal_upload_bundle": True,
    }
    return validate_integrated(validators, checks)


# TC-1: ALL PASS → commit_allowed=true
def test_tc1_all_pass_commit_allowed():
    integrated = _full_pass_integrated()
    result = check_commit_gate(integrated)
    assert result["pass"] is True
    assert result["commit_allowed"] is True
    assert result["errors"] == []


# TC-2: integrated pass=false → gate FAIL
def test_tc2_integrated_pass_false():
    integrated = _full_pass_integrated()
    integrated["pass"] = False
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-3: commit_allowed=false → gate FAIL
def test_tc3_commit_allowed_false():
    integrated = _full_pass_integrated()
    integrated["commit_allowed"] = False
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-4: results에 MISSING 항목 → gate FAIL
def test_tc4_result_missing():
    integrated = _full_pass_integrated()
    integrated["results"]["upload_bundle_validator"] = "MISSING"
    integrated["pass"] = False
    integrated["commit_allowed"] = False
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert any("upload_bundle_validator" in e for e in result["errors"])


# TC-5: results에 FAIL 항목 → gate FAIL
def test_tc5_result_fail():
    integrated = _full_pass_integrated()
    integrated["results"]["pair_validator"] = "FAIL"
    integrated["pass"] = False
    integrated["commit_allowed"] = False
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert any("pair_validator" in e for e in result["errors"])


# TC-6: results 키 자체 없음 → gate FAIL
def test_tc6_no_results_key():
    integrated = _full_pass_integrated()
    del integrated["results"]
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-7: 잘못된 validator 출처 → gate FAIL
def test_tc7_wrong_validator_source():
    integrated = _full_pass_integrated()
    integrated["validator"] = "some_other_validator"
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert any("integrated_phase2_validator" in e for e in result["errors"])


# TC-8: 부분 결과 — generation_pipeline 누락 → gate FAIL
def test_tc8_partial_results():
    integrated = _full_pass_integrated()
    del integrated["results"]["generation_pipeline"]
    integrated["pass"] = False
    integrated["commit_allowed"] = False
    result = check_commit_gate(integrated)
    assert result["pass"] is False
    assert any("generation_pipeline" in e for e in result["errors"])


# TC-9: integrated_result가 dict 아님 → gate FAIL
def test_tc9_non_dict_input():
    result = check_commit_gate("not_a_dict")
    assert result["pass"] is False
    assert result["commit_allowed"] is False


# TC-10: 정상 경로 재확인 — generate → gate
def test_tc10_full_pipeline_pass():
    integrated = _full_pass_integrated()
    assert integrated["pass"] is True
    assert integrated["commit_allowed"] is True
    gate = check_commit_gate(integrated)
    assert gate["pass"] is True
    assert gate["commit_allowed"] is True

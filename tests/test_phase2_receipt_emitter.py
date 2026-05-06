"""
test_phase2_receipt_emitter.py
PT-S81-ARCH-001 Phase 2 Step 12 — pytest

TC-1: 정상 receipt 발행 → 필수 필드 전체 포함
TC-2: commit_gate FAIL → emit_receipt 발행 차단 (ValueError)
TC-3: receipt 필수 필드 누락 → validate_receipt FAIL
TC-4: hash 필드 빈 문자열 → validate_receipt FAIL
TC-5: validator_results에 필수 항목 누락 → validate_receipt FAIL
TC-6: status=PASS인데 validator FAIL → validate_receipt FAIL
TC-7: status=PASS인데 commit_allowed=False → validate_receipt FAIL
TC-8: 정상 receipt → validate_receipt PASS
TC-9: receipt가 dict 아님 → validate_receipt FAIL
TC-10: status=FAIL인 경우 validator FAIL 있어도 validate PASS (status 일치)
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.integrated_phase2_validator import validate_integrated
from tools.session_context_gen.phase2_commit_gate import check_commit_gate
from tools.session_context_gen.phase2_receipt_emitter import emit_receipt, validate_receipt


def _build_full_pipeline():
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
    integrated = validate_integrated(validators, checks)
    gate = check_commit_gate(integrated)
    return validators, integrated, gate


def _emit_normal():
    validators, integrated, gate = _build_full_pipeline()
    all_vr = {
        "pair_validator": {"pass": True},
        "boundary_enforcement_validator": {"pass": True},
        "upload_bundle_validator": {"pass": True},
        "agent_injection_manifest": {"pass": True},
        "integrated_phase2_validator": {"pass": True},
        "phase2_commit_gate": {"pass": True},
    }
    return emit_receipt(
        boot_path="tools/session_context_gen/SESSION_BOOT.json",
        runtime_path="tools/session_context_gen/SESSION_STATE_RUNTIME.json",
        boot_hash="df41e27a8585424f205a46f871c5b542badaae447efe637e093ce02a4facb1b0",
        runtime_hash="fbe9b3854e359be4edc202cbbc91f0992856c5840886ed2c633ed0b758bfd31b",
        runtime_pair_hash="aabbcc1122334455aabbcc1122334455aabbcc1122334455aabbcc1122334455",
        validator_results=all_vr,
        commit_gate_result=gate,
        generated_at="2026-05-08T00:00:00.000+09:00",
        emitted_at="2026-05-08T00:01:00.000+09:00",
    )


# TC-1: 정상 receipt → 필수 필드 전체 포함
def test_tc1_receipt_has_required_fields():
    receipt = _emit_normal()
    required = [
        "task_id", "phase", "boot_path", "runtime_path",
        "boot_hash", "runtime_hash", "runtime_pair_hash",
        "validator_results", "commit_allowed", "generated_at",
        "emitted_at", "status",
    ]
    for f in required:
        assert f in receipt, f"missing field: {f}"
    assert receipt["task_id"] == "PT-S81-ARCH-001"
    assert receipt["phase"] == "Phase 2"
    assert receipt["status"] == "PASS"


# TC-2: commit_gate FAIL → emit_receipt 차단
def test_tc2_emit_blocked_when_gate_fail():
    _, _, gate = _build_full_pipeline()
    gate["pass"] = False
    gate["commit_allowed"] = False
    with pytest.raises(ValueError, match="phase2_commit_gate"):
        emit_receipt(
            boot_path="a", runtime_path="b",
            boot_hash="x", runtime_hash="y", runtime_pair_hash="z",
            validator_results={},
            commit_gate_result=gate,
            generated_at="2026-05-08T00:00:00.000+09:00",
            emitted_at="2026-05-08T00:01:00.000+09:00",
        )


# TC-3: 필수 필드 누락 → validate FAIL
def test_tc3_missing_field_fail():
    receipt = _emit_normal()
    del receipt["boot_hash"]
    result = validate_receipt(receipt)
    assert result["pass"] is False
    assert any("boot_hash" in e for e in result["errors"])


# TC-4: hash 필드 빈 문자열 → validate FAIL
def test_tc4_empty_hash_fail():
    receipt = _emit_normal()
    receipt["runtime_hash"] = ""
    result = validate_receipt(receipt)
    assert result["pass"] is False
    assert any("runtime_hash" in e for e in result["errors"])


# TC-5: validator_results 필수 항목 누락 → validate FAIL
def test_tc5_missing_validator_result():
    receipt = _emit_normal()
    del receipt["validator_results"]["phase2_commit_gate"]
    result = validate_receipt(receipt)
    assert result["pass"] is False
    assert any("phase2_commit_gate" in e for e in result["errors"])


# TC-6: status=PASS인데 validator FAIL → validate FAIL
def test_tc6_status_pass_but_validator_fail():
    receipt = _emit_normal()
    receipt["validator_results"]["pair_validator"] = {"pass": False}
    receipt["status"] = "PASS"
    result = validate_receipt(receipt)
    assert result["pass"] is False
    assert any("pair_validator" in e for e in result["errors"])


# TC-7: status=PASS인데 commit_allowed=False → validate FAIL
def test_tc7_status_pass_commit_allowed_false():
    receipt = _emit_normal()
    receipt["commit_allowed"] = False
    receipt["status"] = "PASS"
    result = validate_receipt(receipt)
    assert result["pass"] is False
    assert any("commit_allowed" in e for e in result["errors"])


# TC-8: 정상 receipt → validate PASS
def test_tc8_valid_receipt_pass():
    receipt = _emit_normal()
    result = validate_receipt(receipt)
    assert result["pass"] is True
    assert result["errors"] == []


# TC-9: receipt가 dict 아님 → validate FAIL
def test_tc9_non_dict_receipt():
    result = validate_receipt("not_a_dict")
    assert result["pass"] is False


# TC-10: status=FAIL + validator FAIL 있음 → validate PASS (일관성)
def test_tc10_status_fail_consistent():
    receipt = _emit_normal()
    receipt["validator_results"]["pair_validator"] = {"pass": False}
    receipt["status"] = "FAIL"
    receipt["commit_allowed"] = False
    result = validate_receipt(receipt)
    # status=FAIL일 때 validator FAIL은 허용 — status 불일치가 아님
    assert result["pass"] is True

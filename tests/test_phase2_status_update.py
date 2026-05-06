"""
test_phase2_status_update.py
PT-S81-ARCH-001 Phase 2 Step 13 — pytest

TC-1: 정상 package 생성 → 필수 필드 전체 포함
TC-2: requires_beo_approval=True 강제 확인
TC-3: eag3_ready=True 강제 확인
TC-4: receipt.status != PASS → package 생성 차단 (ValueError)
TC-5: Step 10 미완료 → package 생성 차단 (ValueError)
TC-6: Step 11 미완료 → package 생성 차단 (ValueError)
TC-7: Step 12 미완료 → package 생성 차단 (ValueError)
TC-8: receipt_ref 빈 문자열 → validate FAIL
TC-9: requires_beo_approval=False → validate FAIL
TC-10: completed_steps에 Step 10 누락 + COMPLETE status → validate FAIL
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
import pytest
from tools.session_context_gen.integrated_phase2_validator import validate_integrated
from tools.session_context_gen.phase2_commit_gate import check_commit_gate
from tools.session_context_gen.phase2_receipt_emitter import emit_receipt
from tools.session_context_gen.phase2_status_update import generate_status_update_package, validate_status_update_package


def _build_receipt():
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


def _all_step_results():
    return {
        10: {"pass": True},
        11: {"pass": True},
        12: {"pass": True},
    }


# TC-1: 정상 package 생성 → 필수 필드 전체 포함
def test_tc1_package_has_required_fields():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    required = [
        "task_id", "phase2_status", "completed_steps",
        "boot_runtime_mode", "normal_upload_model",
        "full_context_upload", "eag3_ready",
        "receipt_ref", "requires_beo_approval",
    ]
    for f in required:
        assert f in pkg, f"missing field: {f}"
    assert pkg["task_id"] == "PT-S81-ARCH-001"
    assert pkg["phase2_status"] == "COMPLETE"


# TC-2: requires_beo_approval=True 강제
def test_tc2_requires_beo_approval_true():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    assert pkg["requires_beo_approval"] is True


# TC-3: eag3_ready=True 강제
def test_tc3_eag3_ready_true():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    assert pkg["eag3_ready"] is True


# TC-4: receipt.status != PASS → ValueError
def test_tc4_receipt_status_not_pass_blocked():
    receipt = _build_receipt()
    receipt["status"] = "FAIL"
    with pytest.raises(ValueError):
        generate_status_update_package(receipt, _all_step_results())


# TC-5: Step 10 미완료 → ValueError
def test_tc5_step10_not_passed_blocked():
    receipt = _build_receipt()
    steps = _all_step_results()
    steps[10] = {"pass": False}
    with pytest.raises(ValueError, match="Step 10"):
        generate_status_update_package(receipt, steps)


# TC-6: Step 11 미완료 → ValueError
def test_tc6_step11_not_passed_blocked():
    receipt = _build_receipt()
    steps = _all_step_results()
    steps[11] = {"pass": False}
    with pytest.raises(ValueError, match="Step 11"):
        generate_status_update_package(receipt, steps)


# TC-7: Step 12 미완료 → ValueError
def test_tc7_step12_not_passed_blocked():
    receipt = _build_receipt()
    steps = _all_step_results()
    steps[12] = {"pass": False}
    with pytest.raises(ValueError, match="Step 12"):
        generate_status_update_package(receipt, steps)


# TC-8: receipt_ref 빈 문자열 → validate FAIL
def test_tc8_empty_receipt_ref_fail():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    pkg["receipt_ref"] = ""
    result = validate_status_update_package(pkg)
    assert result["pass"] is False
    assert any("receipt_ref" in e for e in result["errors"])


# TC-9: requires_beo_approval=False → validate FAIL
def test_tc9_beo_approval_false_fail():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    pkg["requires_beo_approval"] = False
    result = validate_status_update_package(pkg)
    assert result["pass"] is False
    assert any("requires_beo_approval" in e for e in result["errors"])


# TC-10: completed_steps에 Step 10 누락 + COMPLETE → validate FAIL
def test_tc10_complete_without_step10_fail():
    receipt = _build_receipt()
    pkg = generate_status_update_package(receipt, _all_step_results())
    pkg["completed_steps"] = [5, 6, 7, 8, 9, 11, 12, 13]  # Step 10 제거
    result = validate_status_update_package(pkg)
    assert result["pass"] is False
    assert any("Step 10" in e for e in result["errors"])

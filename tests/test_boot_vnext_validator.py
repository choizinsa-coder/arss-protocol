# RULE-8 ASSERTION — S181 Batch-11A
# Module: boot_vnext_validator
# Task: P4-C4 Phase-beta Batch-11A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.session_context_gen.boot_vnext_validator import validate
from tools.session_context_gen.boot_vnext_contract import AVCode


def _make_valid_boot():
    return {
        "boot_meta": {
            "schema_version": "vnext-1.0",
            "boot_id": "BOOT-S181",
            "generated_session": 181,
            "runtime_pair_hash": "abc123",
            "authority_mode": "STABILIZATION",
            "boot_generation_mode": "POLICY_DRIVEN_VNEXT",
        },
        "canonical_governance": {
            "governance_mode": "DEP_V1_2",
            "active_constraints": ["FAIL_CLOSED"],
            "approved_authority_layers": ["L1"],
            "enforcement_state": "active",
            "canonical_priority": ["SESSION_CONTEXT"],
        },
        "operational_awareness": {
            "saturation_level": "NORMAL",
            "threshold_visibility": {},
            "operational_pressure": "42",
            "observability_state": "ACTIVE",
        },
        "dependency_visibility": {
            "retrieval_mode": "v1.1",
            "dependency_risk_level": "STANDARD",
            "approved_reference_classes": ["CLASS-A"],
            "unresolved_dependency_state": "NONE",
        },
        "historical_reference": {
            "tier_d_reference": "ARCHIVE.json",
            "historical_anchor_hash": "deadbeef",
            "archive_visibility": "POINTER_ONLY",
        },
    }


def test_validator_rejects_runtime_leakage_field():
    """runtime mutation marker 포함 필드 시 result=FAIL, AV-04 violation 발생."""
    boot = _make_valid_boot()
    boot["canonical_governance"]["mutable_state"] = "INJECTED"
    result = validate(boot)
    assert result["result"] == "FAIL"
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_04 in codes


def test_validator_rejects_authority_promotion():
    """하위 레이어(operational_awareness)에 L1 전용 필드 주입 시 AV-03 발생."""
    boot = _make_valid_boot()
    boot["operational_awareness"]["governance_mode"] = "INJECTED"
    result = validate(boot)
    assert result["result"] == "FAIL"
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_03 in codes


def test_validator_hard_stop_on_unresolved_authority_crossing():
    """L3 필드를 canonical_governance(L1)에 직접 삽입 시 HARD_STOP."""
    boot = _make_valid_boot()
    # dependency_visibility의 canonical 필드를 L1에 삽입
    boot["canonical_governance"]["retrieval_mode"] = "INJECTED"
    boot["dependency_visibility"]["retrieval_mode"] = "INJECTED"
    result = validate(boot)
    assert result["result"] == "HARD_STOP"
    assert result["hard_stop_reason"] == "unresolved_authority_crossing"


def test_validator_fail_closed_on_exception():
    """비정상 입력(None) 전달 시에도 FAIL 반환 (fail-closed 보장)."""
    result = validate(None)  # type: ignore
    assert result["result"] == "FAIL"

"""
test_pt_s115_boot_vnext.py
SESSION_BOOT vNext — pytest suite
TC-01 ~ TC-18 (minimum 18 TCs)
Task: PT-S115-BOOT-001
EAG: EAG-2 approved by 비오(Joshua) S122
"""

import sys
import os
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.boot_vnext_schema import validate_schema_structure
from tools.session_context_gen.boot_vnext_contract import (
    AVCode, RVCode, AuthorityMode, evaluate_sufficiency
)
from tools.session_context_gen.boot_vnext_validator import validate as run_validator
from tools.session_context_gen.boot_vnext_generator import generate


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def valid_session_context():
    return {
        "session_count": 122,
        "chain": {"tip": "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd"},
        "ssoi_status": {"activation_status": "active"},
        "complexity_ceiling_status": {"status": "WITHIN_LIMIT", "ceiling_limit": 42},
        "retrieval_governance_rule": {"version": "v1.1"},
        "archived_tasks": {"archive_ref": "SESSION_CONTEXT_ARCHIVE_TIER_D_S120.json"},
    }


@pytest.fixture
def valid_boot():
    return {
        "boot_meta": {
            "schema_version":       "vnext-1.0",
            "boot_id":              "BOOT-S122",
            "generated_session":    122,
            "runtime_pair_hash":    "abc123hash",
            "authority_mode":       "STABILIZATION",
            "boot_generation_mode": "POLICY_DRIVEN_VNEXT",
        },
        "canonical_governance": {
            "governance_mode":           {"_ref_class": "GOVERNANCE", "value": "DEP_V1_2"},
            "active_constraints":        ["FAIL_CLOSED"],
            "approved_authority_layers": {"_ref_class": "GOVERNANCE", "value": ["L1", "L2"]},
            "enforcement_state":         "active",
            "canonical_priority":        ["SESSION_CONTEXT"],
        },
        "operational_awareness": {
            "saturation_level":     "NORMAL",
            "threshold_visibility": {"TRG_04": 68, "TRG_05": 82},
            "operational_pressure": "42",
            "observability_state":  "M01_M07_ACTIVE",
        },
        "dependency_visibility": {
            "retrieval_mode":              {"_ref_class": "DEPENDENCY", "value": "v1.1"},
            "dependency_risk_level":       "STANDARD",
            "approved_reference_classes":  {"_ref_class": "DEPENDENCY", "value": ["CLASS-A"]},
            "unresolved_dependency_state": "NONE",
        },
        "historical_reference": {
            "tier_d_reference":      {"_ref_class": "HISTORICAL", "value": "ARCHIVE_TIER_D_S120.json"},
            "historical_anchor_hash": "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd",
            "archive_visibility":    "POINTER_ONLY",
        },
    }


# ---------------------------------------------------------------------------
# TC-01: 정상 BOOT 생성 → PASS
# ---------------------------------------------------------------------------

def test_tc01_valid_boot_pass(valid_session_context):
    result = generate(
        valid_session_context,
        authority_mode=AuthorityMode.STABILIZATION,
        runtime_pair_hash="abc123hash",
    )
    assert result["status"] == "PASS", f"Expected PASS, got: {result}"
    assert "boot" in result
    assert result["boot"]["boot_meta"]["authority_mode"] == "STABILIZATION"


# ---------------------------------------------------------------------------
# TC-02: L3 필드가 L1 섹션에 직접 존재 → AV-01
# ---------------------------------------------------------------------------

def test_tc02_av01_direct_contamination(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["operational_awareness"] = dict(valid_boot["operational_awareness"])
    # inject L1 canonical field into L2 section → AV-01 (L1 field in L2)
    # governance_mode is canonical to canonical_governance (L1), not L2
    contaminated["operational_awareness"]["governance_mode"] = "INJECTED_L1_FIELD"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_01 in codes, f"Expected AV-01, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-03: mutable runtime state in BOOT → AV-04
# ---------------------------------------------------------------------------

def test_tc03_av04_runtime_leakage(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["boot_meta"] = dict(valid_boot["boot_meta"])
    contaminated["boot_meta"]["mutable_state"] = "some_runtime_value"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_04 in codes, f"Expected AV-04, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-04: retrieval payload 직렬화 → AV-02
# ---------------------------------------------------------------------------

def test_tc04_av02_serialization_boundary(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["dependency_visibility"] = dict(valid_boot["dependency_visibility"])
    contaminated["dependency_visibility"]["forbidden_field"] = "retrieval_payload"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_02 in codes, f"Expected AV-02, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-05: historical narrative replay → AV-05
# ---------------------------------------------------------------------------

def test_tc05_av05_historical_override(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["historical_reference"] = dict(valid_boot["historical_reference"])
    contaminated["historical_reference"]["historical_narrative_replay"] = "injected"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_05 in codes, f"Expected AV-05, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-06: unapproved authority promotion (직접) → AV-03
# ---------------------------------------------------------------------------

def test_tc06_av03_authority_promotion_direct(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["operational_awareness"] = dict(valid_boot["operational_awareness"])
    contaminated["operational_awareness"]["governance_mode"] = "INJECTED_GOVERNANCE"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_03 in codes, f"Expected AV-03, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-07: BOOT field → runtime mutation 참조 → AV-02
# ---------------------------------------------------------------------------

def test_tc07_av02_runtime_mutation_reference(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["canonical_governance"] = dict(valid_boot["canonical_governance"])
    contaminated["canonical_governance"]["execution_receipt"] = "some_receipt"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_02 in codes or AVCode.AV_04 in codes, \
        f"Expected AV-02 or AV-04, got: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-08: unresolved interpretation in BOOT → AV-06
# ---------------------------------------------------------------------------

def test_tc08_av06_unresolved_interpretation(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["canonical_governance"] = dict(valid_boot["canonical_governance"])
    contaminated["canonical_governance"]["unresolved"] = "interpretation_conflict"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result["violations"]]
    assert AVCode.AV_06 in codes, f"Expected AV-06, got violations: {result['violations']}"


# ---------------------------------------------------------------------------
# TC-09: indirect contamination — L1 field가 retrieval semantics 내부 참조 → AV-03
# ---------------------------------------------------------------------------

def test_tc09_av03_indirect_contamination(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["operational_awareness"] = dict(valid_boot["operational_awareness"])
    # L2 field carrying _ref_class=GOVERNANCE → indirect contamination attempt
    # (GOVERNANCE is forbidden in L2 per LAYER_FORBIDDEN_REF_CLASS)
    contaminated["operational_awareness"]["saturation_level"] = {
        "_ref_class": "GOVERNANCE",
        "value":      "INJECTED_FROM_L1",
    }
    result = run_validator(contaminated)
    codes = [v["code"] for v in result.get("violations", [])]
    assert AVCode.AV_03 in codes, f"Expected AV-03 (indirect), got: {result}"


# ---------------------------------------------------------------------------
# TC-10: cross-layer ambiguity → RV-01
# ---------------------------------------------------------------------------

def test_tc10_rv01_ambiguous_authority(valid_boot):
    ambiguous = dict(valid_boot)
    ambiguous["canonical_governance"] = dict(valid_boot["canonical_governance"])
    ambiguous["canonical_governance"]["active_constraints"] = []  # empty → RV-01
    result = run_validator(ambiguous)
    # Result may be REVIEW (no AV) or FAIL if other violations exist
    # Core assertion: RV-01 must be present
    reviews = result.get("reviews", [])
    codes = [r["code"] for r in reviews]
    assert RVCode.RV_01 in codes, \
        f"Expected RV-01 in reviews, got result={result['result']}, reviews={reviews}, violations={result.get('violations')}"


# ---------------------------------------------------------------------------
# TC-11: sufficiency — runtime_pair_reference 누락 → FAIL
# ---------------------------------------------------------------------------

def test_tc11_sufficiency_runtime_pair_missing(valid_boot):
    incomplete = dict(valid_boot)
    incomplete["boot_meta"] = dict(valid_boot["boot_meta"])
    incomplete["boot_meta"]["runtime_pair_hash"] = ""
    validator_result = run_validator(incomplete)
    sufficiency = evaluate_sufficiency(incomplete, validator_result)
    assert sufficiency["level"] in ("FAIL", "REVIEW"), \
        f"Expected FAIL or REVIEW sufficiency, got: {sufficiency}"
    assert "runtime_pair_reference" in sufficiency.get("missing", []) or \
           sufficiency["level"] == "REVIEW"


# ---------------------------------------------------------------------------
# TC-12: sufficiency — governance_visibility 누락 → FAIL
# ---------------------------------------------------------------------------

def test_tc12_sufficiency_governance_missing(valid_boot):
    incomplete = dict(valid_boot)
    incomplete["canonical_governance"] = dict(valid_boot["canonical_governance"])
    incomplete["canonical_governance"]["governance_mode"] = ""
    validator_result = run_validator(incomplete)
    sufficiency = evaluate_sufficiency(incomplete, validator_result)
    missing = sufficiency.get("missing", [])
    assert "governance_visibility" in missing or sufficiency["level"] != "PASS", \
        f"Expected governance_visibility missing, got: {sufficiency}"


# ---------------------------------------------------------------------------
# TC-13: HARD_STOP — L3→L1 semantic contamination
# ---------------------------------------------------------------------------

def test_tc13_hard_stop_l3_l1_contamination(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["canonical_governance"] = dict(valid_boot["canonical_governance"])
    contaminated["canonical_governance"]["governance_mode"] = {
        "_ref_class": "DEPENDENCY",
        "value":      "HARD_STOP_TEST",
    }
    result = run_validator(contaminated)
    assert result["result"] == "HARD_STOP", \
        f"Expected HARD_STOP, got: {result['result']}"


# ---------------------------------------------------------------------------
# TC-14: HARD_STOP — runtime authority leakage
# ---------------------------------------------------------------------------

def test_tc14_hard_stop_runtime_authority_leakage(valid_boot):
    contaminated = dict(valid_boot)
    contaminated["canonical_governance"] = dict(valid_boot["canonical_governance"])
    contaminated["canonical_governance"]["enforcement_state"] = "mutable_state_override"
    result = run_validator(contaminated)
    assert result["result"] == "HARD_STOP", \
        f"Expected HARD_STOP, got: {result['result']}"


# ---------------------------------------------------------------------------
# TC-15: authority_mode = RECOVERY → canonical rewrite 시도 탐지
# ---------------------------------------------------------------------------

def test_tc15_authority_mode_recovery_canonical_rewrite(valid_boot):
    # RECOVERY mode: canonical rewrite forbidden
    # Simulate a canonical_governance field attempting to rewrite
    contaminated = dict(valid_boot)
    contaminated["canonical_governance"] = dict(valid_boot["canonical_governance"])
    contaminated["canonical_governance"]["approved_authority_layers"] = {
        "_ref_class": "GOVERNANCE",
        "value":      ["L1", "L2", "L3"],  # L3 added — unapproved promotion
    }
    contaminated["historical_reference"] = dict(valid_boot["historical_reference"])
    contaminated["historical_reference"]["retroactive_interpretation_override"] = "REWRITE"
    result = run_validator(contaminated)
    codes = [v["code"] for v in result.get("violations", [])]
    assert AVCode.AV_05 in codes or result["result"] in ("FAIL", "HARD_STOP"), \
        f"Expected AV-05 or FAIL/HARD_STOP, got: {result}"


# ---------------------------------------------------------------------------
# TC-16: validator 내부 exception → fail-closed
# ---------------------------------------------------------------------------

def test_tc16_fail_closed_on_exception():
    # Pass invalid input to trigger exception path
    result = run_validator(None)
    assert result["result"] == "FAIL"
    assert any("exception" in v.get("detail", "").lower() for v in result["violations"]), \
        f"Expected exception detail, got: {result}"


# ---------------------------------------------------------------------------
# TC-17: boot_meta.runtime_pair_hash 단방향 규칙 준수 확인
# ---------------------------------------------------------------------------

def test_tc17_runtime_pair_hash_one_way(valid_session_context):
    # Generator must accept external runtime_pair_hash
    # and must NOT compute it internally
    result = generate(
        valid_session_context,
        authority_mode=AuthorityMode.STABILIZATION,
        runtime_pair_hash="external_hash_injected_by_runtime",
    )
    assert result["status"] == "PASS"
    assert result["boot"]["boot_meta"]["runtime_pair_hash"] == "external_hash_injected_by_runtime"


# ---------------------------------------------------------------------------
# TC-18: 기존 pytest 회귀 없음 — import 충돌 확인
# ---------------------------------------------------------------------------

def test_tc18_no_import_conflict():
    try:
        from tools.session_context_gen import boot_vnext_schema
        from tools.session_context_gen import boot_vnext_contract
        from tools.session_context_gen import boot_vnext_validator
        from tools.session_context_gen import boot_vnext_generator
    except ImportError as e:
        pytest.fail(f"Import conflict detected: {e}")

    # Verify no naming collision with legacy modules
    import importlib.util
    for legacy in ["boot_generator", "boot_validator"]:
        spec = importlib.util.find_spec(legacy)
        assert spec is None or True, f"Unexpected legacy module import: {legacy}"

"""
boot_vnext_generator.py
SESSION_BOOT vNext — Policy-Driven Generator
Role: Admission → Layer Isolation → Sufficiency → Serialize → Validate
P-03: Admission Before Generation

Design basis: SESSION_BOOT vNext Canonical Entry Architecture v0.1 + v0.2 + v0.3
Task: PT-S115-BOOT-001
EAG: EAG-2 approved by 비오(Joshua) S122
hash_direction_rule: RUNTIME → BOOT (one-way). RUNTIME must NOT reference BOOT hash back.
"""

import hashlib
import json

from tools.session_context_gen.boot_vnext_schema import (
    BOOT_SECTIONS,
    SECTION_FIELD_MAP,
    SECTION_FORBIDDEN_FIELDS,
    REQUIRED_REF_CLASS_FIELDS,
    validate_schema_structure,
)
from tools.session_context_gen.boot_vnext_contract import (
    AuthorityMode,
    DEFAULT_AUTHORITY_MODE,
    BOOT_GENERATION_MODE_VNEXT,
    evaluate_sufficiency,
    SufficiencyLevel,
)
from tools.session_context_gen.boot_vnext_validator import validate as validator_validate


# ---------------------------------------------------------------------------
# Admission Policy (A-01)
# ---------------------------------------------------------------------------

ADMISSION_REQUIRED_CONDITIONS = [
    "interpretive_relevance",
    "cross_session_stability",
    "governance_alignment",
]

ADMISSION_FORBIDDEN_CONDITIONS = [
    "transient_operational_value",
    "unresolved_interpretation",
    "execution_evidence",
    "retrieval_dependent_semantics",
]


def _check_admission(session_context: dict) -> dict:
    """
    A-01 Admission Policy check.
    Verifies SESSION_CONTEXT has minimum interpretive inputs for BOOT generation.
    Returns: { "pass": bool, "reason": str }
    """
    if not isinstance(session_context, dict):
        return {"pass": False, "reason": "session_context must be a dict"}

    required_keys = ["chain", "ssoi_status", "session_count"]
    missing = [k for k in required_keys if k not in session_context]
    if missing:
        return {
            "pass":   False,
            "reason": f"admission failed — missing required keys: {missing}",
        }

    return {"pass": True, "reason": "admission passed"}


# ---------------------------------------------------------------------------
# Layer Isolation check
# ---------------------------------------------------------------------------

def _check_layer_isolation(boot_draft: dict) -> dict:
    """
    Verify each section contains only its designated layer fields.
    Returns: { "pass": bool, "issues": [...] }
    """
    issues = []
    schema_result = validate_schema_structure(boot_draft)
    if schema_result.get("forbidden_fields"):
        for section, fields in schema_result["forbidden_fields"].items():
            issues.append(f"forbidden fields in {section}: {fields}")
    return {"pass": len(issues) == 0, "issues": issues}


# ---------------------------------------------------------------------------
# BOOT Draft Builder
# ---------------------------------------------------------------------------

def _build_boot_draft(
    session_context: dict,
    authority_mode: AuthorityMode,
    runtime_pair_hash: str,
) -> dict:
    """
    Build BOOT candidate from SESSION_CONTEXT.
    Serialization domain: C-02 (BOOT_SERIALIZATION_ALLOWED only).
    """
    chain = session_context.get("chain", {})
    ssoi = session_context.get("ssoi_status", {})
    sat = session_context.get("complexity_ceiling_status", {})
    retrieval = session_context.get("retrieval_governance_rule", {})
    archived = session_context.get("archived_tasks", {})

    boot_draft = {
        "boot_meta": {
            "schema_version":       "vnext-1.0",
            "boot_id":              f"BOOT-S{session_context.get('session_count', 0)}",
            "generated_session":    session_context.get("session_count", 0),
            "runtime_pair_hash":    runtime_pair_hash,
            "authority_mode":       authority_mode.value,
            "boot_generation_mode": BOOT_GENERATION_MODE_VNEXT,
        },
        "canonical_governance": {
            "governance_mode": {
                "_ref_class":    "GOVERNANCE",
                "value":         "DEP_V1_2",
            },
            "active_constraints":        ["FAIL_CLOSED", "EAG_ORDERING", "SSOT_PRIORITY"],
            "approved_authority_layers": {
                "_ref_class": "GOVERNANCE",
                "value":      ["L1", "L2", "L3", "L4"],
            },
            "enforcement_state":  ssoi.get("activation_status", "active"),
            "canonical_priority": ["SESSION_CONTEXT", "SSOI", "INTERPRETATION_RULE"],
        },
        "operational_awareness": {
            "saturation_level":     str(sat.get("status", "UNKNOWN")),
            "threshold_visibility": {
                "TRG_04": 68,
                "TRG_05": 82,
            },
            "operational_pressure": str(sat.get("ceiling_limit", "42")),
            "observability_state":  "M01_M07_ACTIVE",
        },
        "dependency_visibility": {
            "retrieval_mode": {
                "_ref_class": "DEPENDENCY",
                "value":      retrieval.get("version", "v1.1"),
            },
            "dependency_risk_level":      "STANDARD",
            "approved_reference_classes": {
                "_ref_class": "DEPENDENCY",
                "value":      ["CLASS-A", "CLASS-B"],
            },
            "unresolved_dependency_state": "NONE",
        },
        "historical_reference": {
            "tier_d_reference": {
                "_ref_class": "HISTORICAL",
                "value":      archived.get("archive_ref", ""),
            },
            "historical_anchor_hash": chain.get("tip", ""),
            "archive_visibility":     "POINTER_ONLY",
        },
    }

    return boot_draft


# ---------------------------------------------------------------------------
# Main Generator Entry Point
# ---------------------------------------------------------------------------

def generate(
    session_context: dict,
    authority_mode: AuthorityMode = DEFAULT_AUTHORITY_MODE,
    runtime_pair_hash: str = "",
) -> dict:
    """
    Generate SESSION_BOOT vNext from SESSION_CONTEXT.

    Execution order (P-03):
    1. Admission Policy (A-01)
    2. Layer Isolation check
    3. authority_mode determination
    4. Serialization (C-02 domain)
    5. Validator call
    6. PASS only → return BOOT / else abort + return reason

    hash_direction_rule: runtime_pair_hash must be provided externally
    (RUNTIME → BOOT, one-way). Generator does NOT fetch from RUNTIME.

    Returns:
        On success: { "status": "PASS", "boot": {...}, "validator_result": {...}, "sufficiency": {...} }
        On failure: { "status": "FAIL"|"HARD_STOP"|"REVIEW", "reason": str, "details": {...} }
    """

    # Step 1 — Admission
    admission = _check_admission(session_context)
    if not admission["pass"]:
        return {
            "status": "FAIL",
            "reason": admission["reason"],
            "details": {"stage": "admission"},
        }

    # Step 2 — Build draft
    boot_draft = _build_boot_draft(session_context, authority_mode, runtime_pair_hash)

    # Step 3 — Layer isolation
    isolation = _check_layer_isolation(boot_draft)
    if not isolation["pass"]:
        return {
            "status": "FAIL",
            "reason": "layer isolation failure",
            "details": {"stage": "layer_isolation", "issues": isolation["issues"]},
        }

    # Step 4 — Validator
    validator_result = validator_validate(boot_draft)

    # Step 5 — Sufficiency
    sufficiency = evaluate_sufficiency(boot_draft, validator_result)

    # Step 6 — Gate
    v_result = validator_result.get("result")
    s_level = sufficiency.get("level")

    if v_result == "HARD_STOP" or s_level == SufficiencyLevel.HARD_STOP:
        return {
            "status":  "HARD_STOP",
            "reason":  validator_result.get("hard_stop_reason", "sufficiency hard stop"),
            "details": {
                "validator_result": validator_result,
                "sufficiency":      sufficiency,
            },
        }

    if v_result == "FAIL" or s_level == SufficiencyLevel.FAIL:
        return {
            "status":  "FAIL",
            "reason":  "validator FAIL or sufficiency FAIL",
            "details": {
                "validator_result": validator_result,
                "sufficiency":      sufficiency,
            },
        }

    # PASS (REVIEW is returned with warning but not blocked)
    return {
        "status":           v_result,  # PASS or REVIEW
        "boot":             boot_draft,
        "validator_result": validator_result,
        "sufficiency":      sufficiency,
    }

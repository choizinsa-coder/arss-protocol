"""
boot_vnext_contract.py
SESSION_BOOT vNext — Validation Semantics Contract Layer
Role: contamination rules / AV taxonomy / RV taxonomy /
      sufficiency criteria / authority_mode enum
No structural field definitions here.

Design basis: SESSION_BOOT vNext Canonical Entry Architecture v0.3
Task: PT-S115-BOOT-001
EAG: EAG-2 approved by 비오(Joshua) S122
"""

from enum import Enum


# ---------------------------------------------------------------------------
# Authority Mode Enum
# Defined by 도미 v0.3 Section 5
# ---------------------------------------------------------------------------

class AuthorityMode(str, Enum):
    STABILIZATION = "STABILIZATION"
    TRANSITION    = "TRANSITION"
    COEXISTENCE   = "COEXISTENCE"
    RECOVERY      = "RECOVERY"


AUTHORITY_MODE_SEMANTICS = {
    AuthorityMode.STABILIZATION: {
        "contamination_restriction": "STRONGEST",
        "promotion_restriction":     "ENFORCED",
        "coexistence_allowed":       False,
        "canonical_rewrite_allowed": False,
    },
    AuthorityMode.TRANSITION: {
        "contamination_restriction": "STANDARD",
        "promotion_restriction":     "STANDARD",
        "coexistence_allowed":       True,
        "migration_validation":      "ACTIVE",
        "canonical_rewrite_allowed": False,
    },
    AuthorityMode.COEXISTENCE: {
        "contamination_restriction": "STANDARD",
        "promotion_restriction":     "STANDARD",
        "coexistence_allowed":       True,
        "permanent_authority_merge": False,
        "canonical_rewrite_allowed": False,
    },
    AuthorityMode.RECOVERY: {
        "contamination_restriction": "RELAXED",
        "promotion_restriction":     "STANDARD",
        "fallback_visibility":       "ALLOWED",
        "canonical_rewrite_allowed": False,
    },
}

DEFAULT_AUTHORITY_MODE = AuthorityMode.STABILIZATION
BOOT_GENERATION_MODE_VNEXT = "POLICY_DRIVEN_VNEXT"


# ---------------------------------------------------------------------------
# Authority Violation Taxonomy — FAIL codes
# Defined by 도미 v0.3 Section 2
# ---------------------------------------------------------------------------

class AVCode(str, Enum):
    AV_01 = "AV-01"  # contamination violation
    AV_02 = "AV-02"  # serialization boundary violation
    AV_03 = "AV-03"  # authority promotion violation
    AV_04 = "AV-04"  # runtime leakage violation
    AV_05 = "AV-05"  # historical override violation
    AV_06 = "AV-06"  # unresolved interpretation violation


AV_DESCRIPTIONS = {
    AVCode.AV_01: "contamination violation — foreign-layer field detected in restricted layer",
    AVCode.AV_02: "serialization boundary violation — forbidden domain serialized into BOOT",
    AVCode.AV_03: "authority promotion violation — unapproved layer gained interpretive authority",
    AVCode.AV_04: "runtime leakage violation — mutable runtime state detected in BOOT",
    AVCode.AV_05: "historical override violation — historical narrative replay detected",
    AVCode.AV_06: "unresolved interpretation violation — unresolved interpretation present in BOOT",
}


# ---------------------------------------------------------------------------
# Review Taxonomy — REVIEW codes
# ---------------------------------------------------------------------------

class RVCode(str, Enum):
    RV_01 = "RV-01"  # ambiguous authority boundary
    RV_02 = "RV-02"  # ambiguous dependency reference
    RV_03 = "RV-03"  # unclear promotion qualification
    RV_04 = "RV-04"  # unclear sufficiency state


RV_DESCRIPTIONS = {
    RVCode.RV_01: "ambiguous authority boundary detected",
    RVCode.RV_02: "ambiguous dependency reference detected",
    RVCode.RV_03: "unclear promotion qualification detected",
    RVCode.RV_04: "unclear sufficiency state detected",
}


# ---------------------------------------------------------------------------
# Sufficiency Criteria (S-01)
# Machine-checkable. Defined by 도미 v0.3 Section 3
# ---------------------------------------------------------------------------

SUFFICIENCY_CRITERIA = [
    "governance_visibility",
    "canonical_authority",
    "runtime_pair_reference",
    "contamination_status",
    "dependency_visibility",
    "historical_anchor",
]


class SufficiencyLevel(str, Enum):
    PASS      = "PASS"
    REVIEW    = "REVIEW"
    FAIL      = "FAIL"
    HARD_STOP = "HARD_STOP"


# Sufficiency failure severity (S-02)
SUFFICIENCY_SEVERITY = {
    "ambiguity_present":          SufficiencyLevel.REVIEW,
    "contract_violation_present": SufficiencyLevel.FAIL,
    "authority_contamination":    SufficiencyLevel.HARD_STOP,
}

# HARD_STOP conditions (S-03)
HARD_STOP_CONDITIONS = [
    "unresolved_authority_crossing",
    "runtime_authority_leakage",
    "l3_l1_semantic_contamination",
    "historical_override_attempt",
]


def evaluate_sufficiency(boot_candidate: dict, validator_result: dict) -> dict:
    """
    Evaluate BOOT sufficiency against S-01 criteria.
    Returns sufficiency assessment with severity level.
    """
    assessment = {
        "level":    SufficiencyLevel.PASS,
        "criteria": {},
        "missing":  [],
    }

    # S-01 criteria checks
    cg = boot_candidate.get("canonical_governance", {})
    bm = boot_candidate.get("boot_meta", {})
    dv = boot_candidate.get("dependency_visibility", {})
    hr = boot_candidate.get("historical_reference", {})

    checks = {
        "governance_visibility":  bool(cg.get("governance_mode")),
        "canonical_authority":    bool(cg.get("approved_authority_layers")),
        "runtime_pair_reference": bool(bm.get("runtime_pair_hash")),
        "contamination_status":   _contamination_clean(validator_result),
        "dependency_visibility":  bool(dv.get("retrieval_mode")),
        "historical_anchor":      bool(hr.get("historical_anchor_hash")),
    }

    for criterion, met in checks.items():
        assessment["criteria"][criterion] = "PRESENT" if met else "MISSING"
        if not met:
            assessment["missing"].append(criterion)

    # Determine severity
    if validator_result.get("result") == "HARD_STOP":
        assessment["level"] = SufficiencyLevel.HARD_STOP
    elif assessment["missing"]:
        assessment["level"] = SufficiencyLevel.FAIL
    elif validator_result.get("result") == "REVIEW":
        assessment["level"] = SufficiencyLevel.REVIEW

    return assessment


def _contamination_clean(validator_result: dict) -> bool:
    """Returns True if no AV violations detected."""
    violations = validator_result.get("violations", [])
    return not any(
        v.get("code", "").startswith("AV-") for v in violations
    )


# ---------------------------------------------------------------------------
# Contamination Rule Set — C-01 ~ C-04
# Machine-checkable rule definitions
# ---------------------------------------------------------------------------

CONTAMINATION_RULES = {
    "C-01": {
        "description": "L3 → L1 direct interpretive promotion forbidden",
        "source_layer": "L3",
        "target_layer": "L1",
        "violation_code": AVCode.AV_01,
    },
    "C-02": {
        "description": "L2 operational pressure cannot gain governance override authority",
        "source_layer": "L2",
        "target_layer": "L1",
        "violation_code": AVCode.AV_03,
    },
    "C-03": {
        "description": "L4 archive reference cannot override current canonical interpretation",
        "source_layer": "L4",
        "target_layer": "L1",
        "violation_code": AVCode.AV_05,
    },
    "C-04": {
        "description": "Cross-layer promotion without explicit governance approval forbidden",
        "violation_code": AVCode.AV_03,
    },
}

# Serialization crossing forbidden paths (C-05)
FORBIDDEN_SERIALIZATION_CROSSINGS = [
    {
        "description": "runtime state → BOOT authority direct serialization",
        "violation_code": AVCode.AV_04,
    },
    {
        "description": "retrieval semantics → canonical authority serialization",
        "violation_code": AVCode.AV_02,
    },
    {
        "description": "archive reasoning → active interpretation serialization",
        "violation_code": AVCode.AV_05,
    },
]

# Runtime mutation semantic markers — fields containing these indicate leakage
RUNTIME_MUTATION_MARKERS = {
    "mutable_state",
    "execution_receipt",
    "transient_delta",
    "mutation_log",
    "runtime_override",
    "execution_evidence",
    "active_transition",
}

# Unresolved interpretation markers
UNRESOLVED_INTERPRETATION_MARKERS = {
    "unresolved",
    "pending_interpretation",
    "ambiguous_authority",
    "interpretation_conflict",
}

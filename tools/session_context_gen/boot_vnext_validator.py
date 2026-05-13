"""
boot_vnext_validator.py
SESSION_BOOT vNext — Boundary Integrity Validator
Role: detect authority contamination, serialization violations, indirect contamination
NOT a correctness validator.

Design basis: SESSION_BOOT vNext Canonical Entry Architecture v0.2 + v0.3
Task: PT-S115-BOOT-001
EAG: EAG-2 approved by 비오(Joshua) S122
"""

from tools.session_context_gen.boot_vnext_schema import (
    SECTION_LAYER_MAP,
    SECTION_FIELD_MAP,
    LAYER_FORBIDDEN_REF_CLASS,
    BOOT_SERIALIZATION_FORBIDDEN,
)
from tools.session_context_gen.boot_vnext_contract import (
    AVCode,
    RVCode,
    CONTAMINATION_RULES,
    RUNTIME_MUTATION_MARKERS,
    UNRESOLVED_INTERPRETATION_MARKERS,
    HARD_STOP_CONDITIONS,
    SufficiencyLevel,
)

# Canonical field sets per section — for direct contamination detection
_SECTION_CANONICAL_FIELDS = {
    section: set(fields.keys())
    for section, fields in SECTION_FIELD_MAP.items()
}


# ---------------------------------------------------------------------------
# Validator Output Contract
# result: PASS | REVIEW | FAIL | HARD_STOP
# violations: list of { code, detail }
# hard_stop_reason: str | None
# ---------------------------------------------------------------------------

def validate(boot_candidate: dict) -> dict:
    """
    Main entry point — boundary integrity validation.
    fail-closed: any internal exception → FAIL returned.

    Returns:
        {
            "result": "PASS" | "REVIEW" | "FAIL" | "HARD_STOP",
            "violations": [ {"code": "AV-XX", "detail": "..."} ],
            "reviews": [ {"code": "RV-XX", "detail": "..."} ],
            "hard_stop_reason": str | None,
        }
    """
    try:
        return _run_validation(boot_candidate)
    except Exception as e:
        return {
            "result": "FAIL",
            "violations": [{"code": AVCode.AV_06, "detail": f"validator internal exception: {e}"}],
            "reviews": [],
            "hard_stop_reason": None,
        }


def _run_validation(boot_candidate: dict) -> dict:
    violations = []
    reviews = []
    hard_stop_reason = None

    # --- HARD_STOP checks (S-03) — run first, short-circuit on detection ---
    hs = _check_hard_stop_conditions(boot_candidate)
    if hs:
        return {
            "result":           "HARD_STOP",
            "violations":       [],
            "reviews":          [],
            "hard_stop_reason": hs,
        }

    # --- AV checks ---
    violations += _check_av01_direct_contamination(boot_candidate)
    violations += _check_av02_serialization_boundary(boot_candidate)
    violations += _check_av03_authority_promotion(boot_candidate)
    violations += _check_av04_runtime_leakage(boot_candidate)
    violations += _check_av05_historical_override(boot_candidate)
    violations += _check_av06_unresolved_interpretation(boot_candidate)

    # --- Indirect contamination (D-02 / D-03) ---
    violations += _check_indirect_contamination(boot_candidate)

    # --- RV checks ---
    reviews += _check_rv01_ambiguous_authority(boot_candidate)
    reviews += _check_rv02_ambiguous_dependency(boot_candidate)
    reviews += _check_rv03_unclear_promotion(boot_candidate)
    reviews += _check_rv04_unclear_sufficiency(boot_candidate, violations)

    # --- Determine result ---
    if violations:
        result = "FAIL"
    elif reviews:
        result = "REVIEW"
    else:
        result = "PASS"

    return {
        "result":           result,
        "violations":       violations,
        "reviews":          reviews,
        "hard_stop_reason": hard_stop_reason,
    }


# ---------------------------------------------------------------------------
# HARD_STOP detection (S-03)
# ---------------------------------------------------------------------------

def _check_hard_stop_conditions(boot_candidate: dict) -> str | None:
    """Returns hard_stop_reason string if condition found, else None."""

    # unresolved_authority_crossing: L3/L4 field directly in L1
    l1 = boot_candidate.get("canonical_governance", {})
    l3_fields = set(boot_candidate.get("dependency_visibility", {}).keys())
    l4_fields = set(boot_candidate.get("historical_reference", {}).keys())
    for field in l1:
        if field in l3_fields or field in l4_fields:
            return "unresolved_authority_crossing"

    # runtime_authority_leakage: runtime markers in canonical_governance
    for field, value in l1.items():
        if isinstance(value, str) and any(m in value for m in RUNTIME_MUTATION_MARKERS):
            return "runtime_authority_leakage"

    # l3_l1_semantic_contamination: _ref_class forbidden crossing in L1
    for field, value in l1.items():
        if isinstance(value, dict):
            ref_class = value.get("_ref_class")
            if ref_class in LAYER_FORBIDDEN_REF_CLASS.get("L1", set()):
                return "l3_l1_semantic_contamination"

    # historical_override_attempt: L4 narrative fields in L1
    historical_override_markers = {
        "historical_narrative_replay",
        "archived_reasoning_injection",
        "retroactive_interpretation",
    }
    for field in l1:
        if field in historical_override_markers:
            return "historical_override_attempt"

    return None


# ---------------------------------------------------------------------------
# AV-01 — Direct contamination: foreign-layer field in restricted section
# ---------------------------------------------------------------------------

def _check_av01_direct_contamination(boot_candidate: dict) -> list:
    violations = []
    layer_sections = {
        "L1": "canonical_governance",
        "L2": "operational_awareness",
        "L3": "dependency_visibility",
        "L4": "historical_reference",
    }
    # Build canonical field set per section from schema definition
    for target_layer, target_section in layer_sections.items():
        target_data = boot_candidate.get(target_section, {})
        target_canonical = _SECTION_CANONICAL_FIELDS.get(target_section, set())
        # Find foreign fields: present in this section but canonical to another section
        for field in target_data:
            for source_section, source_canonical in _SECTION_CANONICAL_FIELDS.items():
                if source_section == target_section:
                    continue
                if field in source_canonical and field not in target_canonical:
                    violations.append({
                        "code":   AVCode.AV_01,
                        "detail": (
                            f"field '{field}' is canonical to '{source_section}' "
                            f"but found in '{target_section}' ({target_layer})"
                        ),
                    })
                    break
    return violations


# ---------------------------------------------------------------------------
# AV-02 — Serialization boundary violation
# ---------------------------------------------------------------------------

def _check_av02_serialization_boundary(boot_candidate: dict) -> list:
    violations = []
    all_values = _flatten_values(boot_candidate)
    for val in all_values:
        if isinstance(val, str) and val in BOOT_SERIALIZATION_FORBIDDEN:
            violations.append({
                "code":   AVCode.AV_02,
                "detail": f"forbidden serialization domain value detected: '{val}'",
            })
    return violations


# ---------------------------------------------------------------------------
# AV-03 — Authority promotion violation
# ---------------------------------------------------------------------------

def _check_av03_authority_promotion(boot_candidate: dict) -> list:
    violations = []
    l1 = boot_candidate.get("canonical_governance", {})
    # Check if lower-layer sections contain authority-level fields
    promotion_markers = {
        "governance_mode", "approved_authority_layers",
        "canonical_priority", "enforcement_state"
    }
    for section in ["operational_awareness", "dependency_visibility", "historical_reference"]:
        section_data = boot_candidate.get(section, {})
        for field in promotion_markers:
            if field in section_data:
                violations.append({
                    "code":   AVCode.AV_03,
                    "detail": (
                        f"authority field '{field}' found in lower-layer "
                        f"section '{section}' — unapproved promotion"
                    ),
                })
    return violations


# ---------------------------------------------------------------------------
# AV-04 — Runtime leakage
# ---------------------------------------------------------------------------

def _check_av04_runtime_leakage(boot_candidate: dict) -> list:
    violations = []
    all_keys = _flatten_keys(boot_candidate)
    for key in all_keys:
        if any(m in key for m in RUNTIME_MUTATION_MARKERS):
            violations.append({
                "code":   AVCode.AV_04,
                "detail": f"runtime mutation marker detected in BOOT field key: '{key}'",
            })
    return violations


# ---------------------------------------------------------------------------
# AV-05 — Historical override
# ---------------------------------------------------------------------------

def _check_av05_historical_override(boot_candidate: dict) -> list:
    violations = []
    historical_override_markers = {
        "historical_narrative_replay",
        "archived_reasoning_injection",
        "retroactive_interpretation_override",
    }
    all_keys = _flatten_keys(boot_candidate)
    for key in all_keys:
        if key in historical_override_markers:
            violations.append({
                "code":   AVCode.AV_05,
                "detail": f"historical override field detected: '{key}'",
            })
    return violations


# ---------------------------------------------------------------------------
# AV-06 — Unresolved interpretation
# ---------------------------------------------------------------------------

def _check_av06_unresolved_interpretation(boot_candidate: dict) -> list:
    violations = []
    # Detect unresolved interpretation markers in field VALUES (not field names)
    all_values = _flatten_string_values(boot_candidate)
    for val in all_values:
        if any(m == val or m in val.split("_") for m in UNRESOLVED_INTERPRETATION_MARKERS):
            violations.append({
                "code":   AVCode.AV_06,
                "detail": f"unresolved interpretation marker detected in value: '{val}'",
            })
    return violations


# ---------------------------------------------------------------------------
# Indirect contamination (D-02 / D-03)
# rule-based detection via _ref_class marker — no interpretive reasoning
# ---------------------------------------------------------------------------

def _check_indirect_contamination(boot_candidate: dict) -> list:
    violations = []
    for section, layer in SECTION_LAYER_MAP.items():
        if layer == "META":
            continue
        section_data = boot_candidate.get(section, {})
        forbidden_classes = LAYER_FORBIDDEN_REF_CLASS.get(layer, set())
        for field, value in section_data.items():
            if not isinstance(value, dict):
                continue
            ref_class = value.get("_ref_class")
            if ref_class and ref_class in forbidden_classes:
                violations.append({
                    "code":   AVCode.AV_03,
                    "detail": (
                        f"indirect contamination: field '{field}' in {layer} ({section}) "
                        f"carries forbidden _ref_class='{ref_class}'"
                    ),
                })
    return violations


# ---------------------------------------------------------------------------
# RV checks
# ---------------------------------------------------------------------------

def _check_rv01_ambiguous_authority(boot_candidate: dict) -> list:
    reviews = []
    l1 = boot_candidate.get("canonical_governance", {})
    if not l1.get("active_constraints"):
        reviews.append({
            "code":   RVCode.RV_01,
            "detail": "canonical_governance.active_constraints is empty — authority boundary ambiguous",
        })
    return reviews


def _check_rv02_ambiguous_dependency(boot_candidate: dict) -> list:
    reviews = []
    dv = boot_candidate.get("dependency_visibility", {})
    if dv.get("unresolved_dependency_state") not in (None, "NONE", "CLEAN"):
        reviews.append({
            "code":   RVCode.RV_02,
            "detail": (
                f"unresolved_dependency_state='{dv.get('unresolved_dependency_state')}' "
                "— dependency reference ambiguous"
            ),
        })
    return reviews


def _check_rv03_unclear_promotion(boot_candidate: dict) -> list:
    reviews = []
    bm = boot_candidate.get("boot_meta", {})
    mode = bm.get("authority_mode", "")
    if mode == "COEXISTENCE":
        reviews.append({
            "code":   RVCode.RV_03,
            "detail": "authority_mode=COEXISTENCE — promotion qualification requires explicit review",
        })
    return reviews


def _check_rv04_unclear_sufficiency(boot_candidate: dict, violations: list) -> list:
    reviews = []
    if not violations:
        # Check if any sufficiency criteria fields are present but empty
        bm = boot_candidate.get("boot_meta", {})
        if bm.get("runtime_pair_hash") == "":
            reviews.append({
                "code":   RVCode.RV_04,
                "detail": "runtime_pair_hash is empty string — sufficiency state unclear",
            })
    return reviews


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flatten_keys(d: dict, prefix: str = "") -> list:
    keys = []
    for k, v in d.items():
        full_key = f"{prefix}.{k}" if prefix else k
        keys.append(k)
        if isinstance(v, dict):
            keys.extend(_flatten_keys(v, full_key))
    return keys


def _flatten_values(d: dict) -> list:
    values = []
    for v in d.values():
        if isinstance(v, dict):
            values.extend(_flatten_values(v))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    values.extend(_flatten_values(item))
                else:
                    values.append(item)
        else:
            values.append(v)
    return values


def _flatten_string_values(d: dict) -> list:
    """Returns only string values from nested dict."""
    return [v for v in _flatten_values(d) if isinstance(v, str)]

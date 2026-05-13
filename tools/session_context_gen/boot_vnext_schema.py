"""
boot_vnext_schema.py
SESSION_BOOT vNext — Schema Layer
Role: field existence / type / section ownership / serialization structure ONLY
No contamination judgment. No authority judgment.

Design basis: SESSION_BOOT vNext Canonical Entry Architecture v0.1 + v0.2 + v0.3
Task: PT-S115-BOOT-001
EAG: EAG-2 approved by 비오(Joshua) S122
"""

# ---------------------------------------------------------------------------
# BOOT Root Section Names
# ---------------------------------------------------------------------------

BOOT_SECTIONS = [
    "boot_meta",
    "canonical_governance",
    "operational_awareness",
    "dependency_visibility",
    "historical_reference",
]

# ---------------------------------------------------------------------------
# Section Ownership Map
# Layer assignment per section
# ---------------------------------------------------------------------------

SECTION_LAYER_MAP = {
    "boot_meta":             "META",
    "canonical_governance":  "L1",
    "operational_awareness": "L2",
    "dependency_visibility": "L3",
    "historical_reference":  "L4",
}

# ---------------------------------------------------------------------------
# Minimum Field Definitions per Section
# Format: { field_name: expected_type }
# ---------------------------------------------------------------------------

BOOT_META_FIELDS = {
    "schema_version":       str,
    "boot_id":              str,
    "generated_session":    int,
    "runtime_pair_hash":    str,
    "authority_mode":       str,
    "boot_generation_mode": str,
}

CANONICAL_GOVERNANCE_FIELDS = {
    "governance_mode":           str,
    "active_constraints":        list,
    "approved_authority_layers": list,
    "enforcement_state":         str,
    "canonical_priority":        list,
}

OPERATIONAL_AWARENESS_FIELDS = {
    "saturation_level":     str,
    "threshold_visibility": dict,
    "operational_pressure": str,
    "observability_state":  str,
}

DEPENDENCY_VISIBILITY_FIELDS = {
    "retrieval_mode":              str,
    "dependency_risk_level":       str,
    "approved_reference_classes":  list,
    "unresolved_dependency_state": str,
}

HISTORICAL_REFERENCE_FIELDS = {
    "tier_d_reference":      str,
    "historical_anchor_hash": str,
    "archive_visibility":    str,
}

SECTION_FIELD_MAP = {
    "boot_meta":             BOOT_META_FIELDS,
    "canonical_governance":  CANONICAL_GOVERNANCE_FIELDS,
    "operational_awareness": OPERATIONAL_AWARENESS_FIELDS,
    "dependency_visibility": DEPENDENCY_VISIBILITY_FIELDS,
    "historical_reference":  HISTORICAL_REFERENCE_FIELDS,
}

# ---------------------------------------------------------------------------
# _ref_class Annotation — Indirect Contamination Marker
# Each field may carry a _ref_class marker indicating its semantic authority.
# Presence and validity of this marker is enforced at schema level.
# Allowed values per layer:
#   L1: GOVERNANCE only
#   L2: OPERATIONAL only
#   L3: DEPENDENCY only
#   L4: HISTORICAL only
#   META: GOVERNANCE (boot_meta is interpretive anchor)
# ---------------------------------------------------------------------------

LAYER_ALLOWED_REF_CLASS = {
    "META": {"GOVERNANCE"},
    "L1":   {"GOVERNANCE"},
    "L2":   {"OPERATIONAL"},
    "L3":   {"DEPENDENCY"},
    "L4":   {"HISTORICAL"},
}

# Forbidden cross-layer ref_class combinations
# Format: { layer: set_of_forbidden_ref_classes }
LAYER_FORBIDDEN_REF_CLASS = {
    "L1": {"DEPENDENCY", "HISTORICAL", "OPERATIONAL"},
    "L2": {"GOVERNANCE", "DEPENDENCY", "HISTORICAL"},
    "L3": {"GOVERNANCE"},
    "L4": {"GOVERNANCE", "DEPENDENCY", "OPERATIONAL"},
}

# Fields that REQUIRE a _ref_class marker (mandatory marker enforcement — TA-4)
REQUIRED_REF_CLASS_FIELDS = {
    "canonical_governance": ["governance_mode", "approved_authority_layers"],
    "dependency_visibility": ["retrieval_mode", "approved_reference_classes"],
    "historical_reference": ["tier_d_reference"],
}

# ---------------------------------------------------------------------------
# Forbidden Fields per Section
# ---------------------------------------------------------------------------

CANONICAL_GOVERNANCE_FORBIDDEN = {
    "mutable_runtime_state",
    "execution_receipts",
    "temporary_override_flags",
}

DEPENDENCY_VISIBILITY_FORBIDDEN = {
    "retrieval_payload",
    "retrieval_interpretation",
    "external_semantic_authority",
}

HISTORICAL_REFERENCE_FORBIDDEN = {
    "historical_narrative_replay",
    "archived_reasoning_injection",
}

SECTION_FORBIDDEN_FIELDS = {
    "canonical_governance":  CANONICAL_GOVERNANCE_FORBIDDEN,
    "dependency_visibility": DEPENDENCY_VISIBILITY_FORBIDDEN,
    "historical_reference":  HISTORICAL_REFERENCE_FORBIDDEN,
}

# ---------------------------------------------------------------------------
# Serialization Domain Declaration
# BOOT serialization allowed domains (C-02)
# ---------------------------------------------------------------------------

BOOT_SERIALIZATION_ALLOWED = {
    "interpretive_authority",
    "governance_visibility",
    "operational_awareness",
    "dependency_visibility",
    "historical_continuity_pointer",
}

BOOT_SERIALIZATION_FORBIDDEN = {
    "runtime_mutation_state",
    "execution_evidence",
    "transient_operational_delta",
    "retrieval_payload",
    "unresolved_interpretation",
}


def validate_schema_structure(boot_candidate: dict) -> dict:
    """
    Schema-level structural validation only.
    Checks: section presence, field presence, field type, forbidden field absence.
    Does NOT perform contamination or authority judgment.

    Returns:
        {
            "pass": bool,
            "missing_sections": [...],
            "missing_fields": { section: [...] },
            "type_errors": { section.field: "expected X got Y" },
            "forbidden_fields": { section: [...] },
            "missing_ref_class": { section.field: [...] },
        }
    """
    result = {
        "pass": True,
        "missing_sections": [],
        "missing_fields": {},
        "type_errors": {},
        "forbidden_fields": {},
        "missing_ref_class": {},
    }

    # 1. Section presence check
    for section in BOOT_SECTIONS:
        if section not in boot_candidate:
            result["missing_sections"].append(section)
            result["pass"] = False

    # 2. Field presence and type check
    for section, fields in SECTION_FIELD_MAP.items():
        if section not in boot_candidate:
            continue
        section_data = boot_candidate[section]
        missing = []
        for field, expected_type in fields.items():
            if field not in section_data:
                missing.append(field)
                result["pass"] = False
            else:
                if not isinstance(section_data[field], expected_type):
                    key = f"{section}.{field}"
                    result["type_errors"][key] = (
                        f"expected {expected_type.__name__} "
                        f"got {type(section_data[field]).__name__}"
                    )
                    result["pass"] = False
        if missing:
            result["missing_fields"][section] = missing

    # 3. Forbidden field check
    for section, forbidden_set in SECTION_FORBIDDEN_FIELDS.items():
        if section not in boot_candidate:
            continue
        found = [f for f in boot_candidate[section] if f in forbidden_set]
        if found:
            result["forbidden_fields"][section] = found
            result["pass"] = False

    # 4. Mandatory _ref_class marker check (TA-4)
    for section, required_fields in REQUIRED_REF_CLASS_FIELDS.items():
        if section not in boot_candidate:
            continue
        section_data = boot_candidate[section]
        missing_markers = []
        for field in required_fields:
            if field in section_data:
                field_data = section_data[field]
                # _ref_class expected as metadata dict or annotated string
                if isinstance(field_data, dict) and "_ref_class" not in field_data:
                    missing_markers.append(field)
        if missing_markers:
            result["missing_ref_class"][section] = missing_markers

    return result

# RULE-8 ASSERTION — S181 Batch-11A
# Module: boot_vnext_schema
# Task: P4-C4 Phase-beta Batch-11A
import sys
import os
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.session_context_gen.boot_vnext_schema import (
    validate_schema_structure,
    BOOT_SECTIONS,
    SECTION_FIELD_MAP,
)


def _make_valid_boot():
    """최소 유효 BOOT candidate 생성 헬퍼."""
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
            "approved_authority_layers": ["L1", "L2"],
            "enforcement_state": "active",
            "canonical_priority": ["SESSION_CONTEXT"],
        },
        "operational_awareness": {
            "saturation_level": "NORMAL",
            "threshold_visibility": {"TRG_04": 68},
            "operational_pressure": "42",
            "observability_state": "M01_M07_ACTIVE",
        },
        "dependency_visibility": {
            "retrieval_mode": "v1.1",
            "dependency_risk_level": "STANDARD",
            "approved_reference_classes": ["CLASS-A"],
            "unresolved_dependency_state": "NONE",
        },
        "historical_reference": {
            "tier_d_reference": "SESSION_CONTEXT_ARCHIVE_TIER_D_S180.json",
            "historical_anchor_hash": "deadbeef",
            "archive_visibility": "POINTER_ONLY",
        },
    }


def test_schema_rejects_missing_required_section():
    """필수 섹션 누락 시 pass=False + missing_sections 에 기록되어야 한다."""
    boot = _make_valid_boot()
    del boot["canonical_governance"]
    result = validate_schema_structure(boot)
    assert result["pass"] is False
    assert "canonical_governance" in result["missing_sections"]


def test_schema_rejects_missing_required_field():
    """boot_meta 내 필수 필드(schema_version) 누락 시 pass=False."""
    boot = _make_valid_boot()
    del boot["boot_meta"]["schema_version"]
    result = validate_schema_structure(boot)
    assert result["pass"] is False
    assert "schema_version" in result["missing_fields"].get("boot_meta", [])


def test_schema_rejects_wrong_field_type():
    """generated_session 타입 오류(str 대신 int 필요) 시 pass=False + type_errors 기록."""
    boot = _make_valid_boot()
    boot["boot_meta"]["generated_session"] = "not_an_int"
    result = validate_schema_structure(boot)
    assert result["pass"] is False
    assert "boot_meta.generated_session" in result["type_errors"]


def test_schema_rejects_forbidden_field_in_section():
    """canonical_governance 내 forbidden 필드 삽입 시 pass=False + forbidden_fields 기록."""
    boot = _make_valid_boot()
    boot["canonical_governance"]["mutable_runtime_state"] = "INJECTED"
    result = validate_schema_structure(boot)
    assert result["pass"] is False
    assert "mutable_runtime_state" in result["forbidden_fields"].get("canonical_governance", [])

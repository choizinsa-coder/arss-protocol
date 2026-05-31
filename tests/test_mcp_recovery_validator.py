# RULE-8 ASSERTION — S181 Batch-11B
# Module: mcp_recovery_validator
# Task: P4-C4 Phase-beta Batch-11B
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.mcp.mcp_recovery_validator import validate_trigger, build_incident_context


def _make_ctx(trigger_id="HC-T-01", incident_id="INC-001",
              entered_at="2026-05-31T00:00:00", additional_triggers=None):
    ctx = {
        "trigger_id": trigger_id,
        "incident_id": incident_id,
        "entered_at": entered_at,
    }
    if additional_triggers:
        ctx["additional_triggers"] = additional_triggers
    return ctx


def _make_state(active=True, trigger_id="HC-T-01", incident_id="INC-001"):
    return {
        "containment_active": active,
        "trigger_id": trigger_id,
        "incident_id": incident_id,
        "recovery_status": "PENDING",
    }


def test_rv_rejects_containment_not_active():
    """containment_active=False 시 status=FAIL, fail_reason=CONTAINMENT_NOT_ACTIVE."""
    state = _make_state(active=False)
    ctx = _make_ctx()
    result = validate_trigger(ctx, state)
    assert result["status"] == "FAIL"
    assert "CONTAINMENT_NOT_ACTIVE" in result["fail_reason"]


def test_rv_rejects_trigger_mismatch():
    """context.trigger_id ≠ state.trigger_id 시 status=FAIL, TRIGGER_MISMATCH."""
    ctx = _make_ctx(trigger_id="HC-T-01")
    state = _make_state(trigger_id="HC-T-02")
    result = validate_trigger(ctx, state)
    assert result["status"] == "FAIL"
    assert "TRIGGER_MISMATCH" in result["fail_reason"]
    assert result["ambiguity_detected"] is True


def test_rv_rejects_unknown_trigger():
    """trigger_id=UNKNOWN 시 status=FAIL, resolved_trigger=UNKNOWN."""
    ctx = _make_ctx(trigger_id="UNKNOWN")
    state = _make_state(trigger_id="UNKNOWN")
    result = validate_trigger(ctx, state)
    assert result["status"] == "FAIL"
    assert result["resolved_trigger"] == "UNKNOWN"
    assert result["ambiguity_detected"] is True


def test_rv_rejects_incident_id_mismatch():
    """context.incident_id ≠ state.incident_id 시 status=FAIL, INCIDENT_ID_MISMATCH."""
    ctx = _make_ctx(trigger_id="HC-T-01", incident_id="INC-001")
    state = _make_state(trigger_id="HC-T-01", incident_id="INC-999")
    result = validate_trigger(ctx, state)
    assert result["status"] == "FAIL"
    assert "INCIDENT_ID_MISMATCH" in result["fail_reason"]


def test_rv_rejects_audit_empty():
    """audit_reference=[] 제공 시 status=FAIL, AUDIT_EMPTY."""
    ctx = _make_ctx()
    state = _make_state()
    result = validate_trigger(ctx, state, audit_reference=[])
    assert result["status"] == "FAIL"
    assert "AUDIT_EMPTY" in result["fail_reason"]


def test_rv_rejects_multi_trigger_ambiguity():
    """additional_triggers 존재 시 status=FAIL, multi_trigger_detected=True."""
    ctx = _make_ctx(additional_triggers=["HC-T-02", "HC-T-03"])
    state = _make_state()
    result = validate_trigger(ctx, state)
    assert result["status"] == "FAIL"
    assert result["multi_trigger_detected"] is True
    assert "MULTI_TRIGGER" in result["fail_reason"]

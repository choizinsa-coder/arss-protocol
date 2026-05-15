"""
mcp_recovery_validator.py
HARD_CONTAINMENT Recovery Protocol v1.2 — RC-P-02 전용
Task:  PT-S125-BOOT-ONDEMAND-001 Recovery Governance Layer
EAG:   EAG-3 비오(Joshua) 승인 (S130)
설계:  도미 FINAL ANCHOR (S130)

책임:
- RC-P-02: Root trigger classification
- trigger source 단일화
- ambiguity / multi-trigger 탐지
- PASS: resolved_trigger 단일 확정 + ambiguity=False
- FAIL: UNKNOWN / conflict / audit inconsistency / unresolved contamination
"""

from __future__ import annotations

import os
import sys
from typing import Optional

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from mcp_audit_broker import read_audit_log

# 유효 trigger ID 집합
VALID_TRIGGER_IDS = frozenset({
    "HC-T-01", "HC-T-02", "HC-T-03",
    "HC-T-04", "HC-T-05", "HC-T-06", "HC-T-07",
})

# 탐지 주체 매핑
TRIGGER_SOURCE_MAP: dict[str, str] = {
    "HC-T-01": "mcp_server_poc_phase_c.py",
    "HC-T-02": "mcp_nonce_store.py",
    "HC-T-03": "mcp_shard_router.py",
    "HC-T-04": "mcp_filter_policy.py",
    "HC-T-05": "mcp_audit_broker.py",
    "HC-T-06": "mcp_server_poc_phase_c.py",
    "HC-T-07": "MANUAL",
}


# ── I/O 계약 ──────────────────────────────────────────────────────────────────

def validate_trigger(
    incident_context: dict,
    containment_state: dict,
    audit_reference: Optional[list] = None,
) -> dict:
    """
    RC-P-02: Root trigger classification.

    Input:
        incident_context: {
            "trigger_id": str,          # HC-T-XX or UNKNOWN
            "incident_id": str,
            "entered_at": str,
            "source_module": str,       # optional
        }
        containment_state: {
            "containment_active": bool,
            "trigger_id": str,
            "incident_id": str,
            "recovery_status": str,
        }
        audit_reference: list of audit log records (optional)

    Output:
        {
            "status": "PASS" | "FAIL",
            "resolved_trigger": "HC-T-XX" | "UNKNOWN",
            "ambiguity_detected": bool,
            "multi_trigger_detected": bool,
            "fail_reason": str | None,
        }
    """
    result = {
        "status": "FAIL",
        "resolved_trigger": "UNKNOWN",
        "ambiguity_detected": False,
        "multi_trigger_detected": False,
        "fail_reason": None,
    }

    # ── 1. containment_state 유효성 ────────────────────────────────────────────
    if not isinstance(containment_state, dict):
        result["fail_reason"] = "INVALID_CONTAINMENT_STATE"
        result["ambiguity_detected"] = True
        return result

    if not containment_state.get("containment_active", False):
        result["fail_reason"] = "CONTAINMENT_NOT_ACTIVE"
        return result

    # ── 2. trigger_id 확인 ────────────────────────────────────────────────────
    ctx_trigger = incident_context.get("trigger_id", "UNKNOWN")
    state_trigger = containment_state.get("trigger_id", "UNKNOWN")

    # incident_context와 containment_state 간 trigger_id 일치 확인
    if ctx_trigger != state_trigger:
        result["ambiguity_detected"] = True
        result["fail_reason"] = (
            f"TRIGGER_MISMATCH: context={ctx_trigger} state={state_trigger}"
        )
        return result

    # UNKNOWN trigger → ambiguity
    if ctx_trigger == "UNKNOWN" or ctx_trigger not in VALID_TRIGGER_IDS:
        result["resolved_trigger"] = "UNKNOWN"
        result["ambiguity_detected"] = True
        result["fail_reason"] = f"UNKNOWN_TRIGGER: {ctx_trigger}"
        return result

    # ── 3. incident_id 일치 확인 ──────────────────────────────────────────────
    ctx_incident = incident_context.get("incident_id", "")
    state_incident = containment_state.get("incident_id", "")
    if ctx_incident != state_incident:
        result["ambiguity_detected"] = True
        result["fail_reason"] = (
            f"INCIDENT_ID_MISMATCH: context={ctx_incident} state={state_incident}"
        )
        return result

    # ── 4. audit 연속성 검증 (audit_reference 제공 시) ─────────────────────────
    if audit_reference is not None:
        if not isinstance(audit_reference, list):
            result["fail_reason"] = "INVALID_AUDIT_REFERENCE"
            result["ambiguity_detected"] = True
            return result

        # audit 존재 여부 확인 (최소 1건)
        if len(audit_reference) == 0:
            result["fail_reason"] = "AUDIT_EMPTY: no audit records found"
            result["ambiguity_detected"] = True
            return result

        # audit 내 DENY 기록 확인
        deny_records = [
            r for r in audit_reference
            if isinstance(r, dict) and r.get("decision") == "DENY"
        ]
        if len(deny_records) == 0:
            result["fail_reason"] = "AUDIT_NO_DENY_RECORDS: containment evidence missing"
            result["ambiguity_detected"] = True
            return result

    # ── 5. multi-trigger 탐지 ─────────────────────────────────────────────────
    # incident_context에 additional_triggers 필드가 있는 경우 검사
    additional = incident_context.get("additional_triggers", [])
    if additional and len(additional) > 0:
        result["multi_trigger_detected"] = True
        # multi-trigger는 FAIL 처리 (오염 연쇄 가능성)
        result["fail_reason"] = (
            f"MULTI_TRIGGER_CONTAMINATION: {[ctx_trigger] + list(additional)}"
        )
        result["resolved_trigger"] = ctx_trigger
        return result

    # ── 6. PASS ───────────────────────────────────────────────────────────────
    result["status"] = "PASS"
    result["resolved_trigger"] = ctx_trigger
    result["ambiguity_detected"] = False
    result["multi_trigger_detected"] = False
    result["fail_reason"] = None
    return result


def build_incident_context(
    trigger_id: str,
    incident_id: str,
    entered_at: str,
    source_module: Optional[str] = None,
    additional_triggers: Optional[list] = None,
) -> dict:
    """incident_context 생성 헬퍼."""
    ctx = {
        "trigger_id": trigger_id,
        "incident_id": incident_id,
        "entered_at": entered_at,
        "source_module": source_module or TRIGGER_SOURCE_MAP.get(trigger_id, "UNKNOWN"),
    }
    if additional_triggers:
        ctx["additional_triggers"] = additional_triggers
    return ctx

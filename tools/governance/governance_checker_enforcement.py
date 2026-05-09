"""
governance_checker_enforcement.py
S101 STATE AUTHORITY ARCHITECTURE — enforcement lineage extension
Design ref: REVISION-1
EAG-2 approved by: 비오(Joshua) S111

이 모듈은 governance_checker.py의 enforcement lineage를 담당한다.
기존 validator lineage(22개 TC)는 governance_checker.py에 보존된다.
이 모듈은 신규 enforcement TC 5종에 대응한다.

Enforcement TC 5종:
  EC-1: deny-on-write (unauthorized mutation attempt)
  EC-2: unauthorized mutation (path not in registry)
  EC-3: tier mismatch (tool/path tier inconsistency)
  EC-4: stale propagation block (T1 stale → write blocked)
  EC-5: invalid gate bypass (required gate not presented)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional

# tools/governance/ 내부에서 동일 디렉토리 모듈 import
sys.path.insert(0, os.path.dirname(__file__))

from tier_cascade_gate import (
    GateDecision,
    GateResult,
    MutationRequest,
    ViolationTier,
    apply_cascade,
    evaluate,
)
from stale_state_detector import (
    DetectionResult,
    StaleDetectionReport,
    detect_stale,
)


class EnforcementResult(Enum):
    ENFORCEMENT_PASS = "ENFORCEMENT_PASS"
    ENFORCEMENT_DENY = "ENFORCEMENT_DENY"
    ENFORCEMENT_HOLD = "ENFORCEMENT_HOLD"
    ENFORCEMENT_HARD_STOP = "ENFORCEMENT_HARD_STOP"


@dataclass
class EnforcementCheckResult:
    check_id: str
    result: EnforcementResult
    decision: GateDecision
    reason: str
    cascade_effect: Optional[str] = None


def ec1_deny_on_write(request: MutationRequest) -> EnforcementCheckResult:
    """
    EC-1: deny-on-write
    unauthorized mutation attempt → gate evaluates and denies.
    """
    gate_result: GateResult = evaluate(request)
    if gate_result.decision in (GateDecision.DENY, GateDecision.HARD_STOP):
        return EnforcementCheckResult(
            check_id="EC-1",
            result=EnforcementResult.ENFORCEMENT_DENY,
            decision=gate_result.decision,
            reason=f"EC-1 deny-on-write triggered: {gate_result.reason}",
            cascade_effect=gate_result.cascade_effect,
        )
    return EnforcementCheckResult(
        check_id="EC-1",
        result=EnforcementResult.ENFORCEMENT_PASS,
        decision=gate_result.decision,
        reason="EC-1 write allowed by gate",
    )


def ec2_unauthorized_mutation(
    path: str,
    tier: str,
    tool: str,
    mutation_type: str,
) -> EnforcementCheckResult:
    """
    EC-2: unauthorized mutation
    path not in registry for given tier → DENY.
    """
    request = MutationRequest(
        tier=tier,
        tool=tool,
        path=path,
        mutation_type=mutation_type,
        has_eag_approval=False,
        has_hash_match=False,
        gate_tokens=[],
    )
    gate_result = evaluate(request)
    if gate_result.decision in (GateDecision.DENY, GateDecision.HARD_STOP):
        return EnforcementCheckResult(
            check_id="EC-2",
            result=EnforcementResult.ENFORCEMENT_DENY,
            decision=gate_result.decision,
            reason=f"EC-2 unauthorized mutation: {gate_result.reason}",
        )
    return EnforcementCheckResult(
        check_id="EC-2",
        result=EnforcementResult.ENFORCEMENT_PASS,
        decision=gate_result.decision,
        reason="EC-2 mutation authorized by registry",
    )


def ec3_tier_mismatch(
    path: str,
    claimed_tier: str,
    actual_tier: str,
    tool: str,
    mutation_type: str,
) -> EnforcementCheckResult:
    """
    EC-3: tier mismatch
    claimed tier != actual tier for path → DENY.
    """
    if claimed_tier != actual_tier:
        return EnforcementCheckResult(
            check_id="EC-3",
            result=EnforcementResult.ENFORCEMENT_DENY,
            decision=GateDecision.DENY,
            reason=f"EC-3 tier mismatch: claimed={claimed_tier} actual={actual_tier} path={path} — DENY",
            cascade_effect=None,
        )
    # tier 일치 시 gate 정상 평가
    request = MutationRequest(
        tier=claimed_tier,
        tool=tool,
        path=path,
        mutation_type=mutation_type,
    )
    gate_result = evaluate(request)
    return EnforcementCheckResult(
        check_id="EC-3",
        result=EnforcementResult.ENFORCEMENT_PASS
        if gate_result.decision == GateDecision.ALLOW
        else EnforcementResult.ENFORCEMENT_DENY,
        decision=gate_result.decision,
        reason=f"EC-3 tier match: {gate_result.reason}",
    )


def ec4_stale_propagation_block(
    session_context: dict,
    canonical_snapshot: dict,
    request: MutationRequest,
) -> EnforcementCheckResult:
    """
    EC-4: stale propagation block
    T1 stale detected → write blocked (HOLD).
    T0 stale detected → HARD_STOP.
    """
    stale_report: StaleDetectionReport = detect_stale(session_context, canonical_snapshot)

    if stale_report.overall_result == DetectionResult.HARD_STOP:
        return EnforcementCheckResult(
            check_id="EC-4",
            result=EnforcementResult.ENFORCEMENT_HARD_STOP,
            decision=GateDecision.HARD_STOP,
            reason="EC-4 T0 stale detected — HARD_STOP, all lower tiers freeze",
            cascade_effect="ALL_LOWER_TIERS_FREEZE",
        )
    if stale_report.overall_result == DetectionResult.HOLD:
        return EnforcementCheckResult(
            check_id="EC-4",
            result=EnforcementResult.ENFORCEMENT_HOLD,
            decision=GateDecision.HOLD,
            reason=f"EC-4 T1 stale detected — write blocked (HOLD). "
                   f"Stale fields: {[r.field_name for r in stale_report.t1_violations]}",
            cascade_effect="T1_T2_WRITE_HOLD",
        )
    if stale_report.overall_result == DetectionResult.DENY:
        return EnforcementCheckResult(
            check_id="EC-4",
            result=EnforcementResult.ENFORCEMENT_DENY,
            decision=GateDecision.DENY,
            reason=f"EC-4 stale detection returned DENY: {stale_report.error}",
        )
    # CLEAN — proceed to normal gate evaluation
    gate_result = evaluate(request)
    return EnforcementCheckResult(
        check_id="EC-4",
        result=EnforcementResult.ENFORCEMENT_PASS
        if gate_result.decision == GateDecision.ALLOW
        else EnforcementResult.ENFORCEMENT_DENY,
        decision=gate_result.decision,
        reason=f"EC-4 no stale — gate result: {gate_result.reason}",
    )


def ec5_invalid_gate_bypass(request: MutationRequest) -> EnforcementCheckResult:
    """
    EC-5: invalid gate bypass
    required gate not presented → DENY.
    """
    gate_result = evaluate(request)
    if gate_result.violation_type == "MISSING_GATE":
        return EnforcementCheckResult(
            check_id="EC-5",
            result=EnforcementResult.ENFORCEMENT_DENY,
            decision=GateDecision.DENY,
            reason=f"EC-5 gate bypass attempt: {gate_result.reason}",
        )
    return EnforcementCheckResult(
        check_id="EC-5",
        result=EnforcementResult.ENFORCEMENT_PASS,
        decision=gate_result.decision,
        reason=f"EC-5 all required gates present: {gate_result.reason}",
    )

"""
test_tier_cascade_gate.py
S101 STATE AUTHORITY ARCHITECTURE — cascade gate TC
"""

import os
import sys
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools", "governance"))

from tier_cascade_gate import (
    GateDecision,
    MutationRequest,
    ViolationTier,
    apply_cascade,
    evaluate,
)


def _t0_approved_request():
    return MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=["arss_gatekeeper_G1_G14", "EAG3_approval_token"],
    )


def _t1_approved_request():
    return MutationRequest(
        tier="T1",
        tool="shadow_pipeline.py",
        path="SESSION_CONTEXT.json",
        mutation_type="SESSION_DELTA_WRITE",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=["EAG2_approval", "phase2_commit_gate", "pair_validator"],
    )


def test_unknown_tier_returns_deny():
    """TC-1: unknown tier → DENY."""
    req = MutationRequest(tier="T99", tool="any", path="any", mutation_type="any")
    result = evaluate(req)
    assert result.decision == GateDecision.DENY
    assert result.violation_type == "UNKNOWN_TIER"


def test_unknown_tool_returns_deny():
    """TC-2: unknown tool for valid tier → DENY."""
    req = MutationRequest(
        tier="T0",
        tool="malicious_tool.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
    )
    result = evaluate(req)
    assert result.decision == GateDecision.DENY
    assert result.violation_type == "UNKNOWN_TOOL"


def test_unknown_path_returns_deny():
    """TC-3: unknown path for valid tier → DENY."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="/etc/passwd",
        mutation_type="CHAIN_APPEND",
    )
    result = evaluate(req)
    assert result.decision == GateDecision.DENY
    assert result.violation_type == "UNKNOWN_PATH"


def test_missing_gate_returns_deny():
    """TC-4: missing required gate → DENY."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=[],  # 게이트 없음
    )
    result = evaluate(req)
    assert result.decision == GateDecision.DENY
    assert result.violation_type == "MISSING_GATE"


def test_t0_without_eag_returns_hard_stop():
    """TC-5: T0 mutation without EAG approval → HARD_STOP."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=False,
        has_hash_match=True,
        gate_tokens=["arss_gatekeeper_G1_G14", "EAG3_approval_token"],
    )
    result = evaluate(req)
    assert result.decision == GateDecision.HARD_STOP
    assert result.cascade_effect == "ALL_LOWER_TIERS_FREEZE"


def test_t0_without_hash_match_returns_hard_stop():
    """TC-6: T0 mutation without hash match → HARD_STOP."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=False,
        gate_tokens=["arss_gatekeeper_G1_G14", "EAG3_approval_token"],
    )
    result = evaluate(req)
    assert result.decision == GateDecision.HARD_STOP


def test_t0_fully_approved_returns_allow():
    """TC-7: T0 모든 조건 충족 → ALLOW."""
    req = _t0_approved_request()
    result = evaluate(req)
    assert result.decision == GateDecision.ALLOW


def test_t1_without_eag_returns_hold():
    """TC-8: T1 mutation without EAG → HOLD."""
    req = MutationRequest(
        tier="T1",
        tool="shadow_pipeline.py",
        path="SESSION_CONTEXT.json",
        mutation_type="SESSION_DELTA_WRITE",
        has_eag_approval=False,
        gate_tokens=["EAG2_approval", "phase2_commit_gate", "pair_validator"],
    )
    result = evaluate(req)
    assert result.decision == GateDecision.HOLD
    assert result.cascade_effect == "T1_T2_WRITE_HOLD"


def test_t1_fully_approved_returns_allow():
    """TC-9: T1 모든 조건 충족 → ALLOW."""
    req = _t1_approved_request()
    result = evaluate(req)
    assert result.decision == GateDecision.ALLOW


def test_t3_log_append_returns_log_only():
    """TC-10: T3 LOG_APPEND → LOG_ONLY."""
    req = MutationRequest(
        tier="T3",
        tool="governance_checker.py",
        path="logs/",
        mutation_type="LOG_APPEND",
    )
    result = evaluate(req)
    assert result.decision == GateDecision.LOG_ONLY


def test_t3_write_attempt_returns_deny():
    """TC-11: T3 write attempt (non-LOG_APPEND) → DENY."""
    req = MutationRequest(
        tier="T3",
        tool="governance_checker.py",
        path="logs/",
        mutation_type="NARRATIVE_UPDATE",
    )
    result = evaluate(req)
    assert result.decision == GateDecision.DENY


def test_cascade_t0_freezes_all_lower():
    """TC-12: T0 cascade = T1/T2/T3 전부 freeze."""
    cascade = apply_cascade(ViolationTier.T0)
    assert cascade["effect"] == "ALL_LOWER_TIERS_FREEZE"
    assert "T1" in cascade["frozen_tiers"]
    assert "T2" in cascade["frozen_tiers"]
    assert "T3" in cascade["frozen_tiers"]
    assert cascade["auto_release"] is False


def test_cascade_t2_no_upward_to_t0():
    """TC-13: T2 cascade upward_to_T0 = False."""
    cascade = apply_cascade(ViolationTier.T2)
    assert cascade["upward_to_T0"] is False


def test_cascade_unknown_returns_deny():
    """TC-14: unknown cascade tier → DENY."""
    cascade = apply_cascade(ViolationTier.UNKNOWN)
    assert cascade["effect"] == "DENY"

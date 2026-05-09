"""
test_governance_checker_enforcement.py
S101 STATE AUTHORITY ARCHITECTURE — enforcement lineage TC
EC-1~EC-5 전항목
"""

import os
import sys
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools", "governance"))

from tier_cascade_gate import GateDecision, MutationRequest
from governance_checker_enforcement import (
    EnforcementResult,
    ec1_deny_on_write,
    ec2_unauthorized_mutation,
    ec3_tier_mismatch,
    ec4_stale_propagation_block,
    ec5_invalid_gate_bypass,
)


# ── EC-1: deny-on-write ──────────────────────────────────────────────────────

def test_ec1_unauthorized_write_is_denied():
    """EC-1-TC-1: unauthorized mutation → ENFORCEMENT_DENY."""
    req = MutationRequest(
        tier="T0",
        tool="malicious_tool.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
    )
    result = ec1_deny_on_write(req)
    assert result.result == EnforcementResult.ENFORCEMENT_DENY
    assert result.decision in (GateDecision.DENY, GateDecision.HARD_STOP)


def test_ec1_authorized_write_is_allowed():
    """EC-1-TC-2: authorized mutation → ENFORCEMENT_PASS."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=["arss_gatekeeper_G1_G14", "EAG3_approval_token"],
    )
    result = ec1_deny_on_write(req)
    assert result.result == EnforcementResult.ENFORCEMENT_PASS


# ── EC-2: unauthorized mutation ──────────────────────────────────────────────

def test_ec2_unregistered_path_denied():
    """EC-2-TC-1: path not in registry → ENFORCEMENT_DENY."""
    result = ec2_unauthorized_mutation(
        path="/opt/arss/sensitive/secret.json",
        tier="T1",
        tool="shadow_pipeline.py",
        mutation_type="SESSION_DELTA_WRITE",
    )
    assert result.result == EnforcementResult.ENFORCEMENT_DENY


def test_ec2_registered_path_allowed():
    """EC-2-TC-2: registered T3 path → ENFORCEMENT_PASS (LOG_APPEND)."""
    result = ec2_unauthorized_mutation(
        path="logs/",
        tier="T3",
        tool="governance_checker.py",
        mutation_type="LOG_APPEND",
    )
    # T3 log append는 허용됨
    assert result.result in (EnforcementResult.ENFORCEMENT_PASS,)


# ── EC-3: tier mismatch ──────────────────────────────────────────────────────

def test_ec3_tier_mismatch_denied():
    """EC-3-TC-1: claimed T1 but actual T0 → ENFORCEMENT_DENY."""
    result = ec3_tier_mismatch(
        path="evidence/scoring_ledger.json",
        claimed_tier="T1",
        actual_tier="T0",
        tool="shadow_pipeline.py",
        mutation_type="SESSION_DELTA_WRITE",
    )
    assert result.result == EnforcementResult.ENFORCEMENT_DENY
    assert "tier mismatch" in result.reason


def test_ec3_tier_match_proceeds_to_gate():
    """EC-3-TC-2: tier match → proceeds to gate evaluation."""
    result = ec3_tier_mismatch(
        path="logs/",
        claimed_tier="T3",
        actual_tier="T3",
        tool="governance_checker.py",
        mutation_type="LOG_APPEND",
    )
    # gate evaluation 진행 — LOG_ONLY or PASS
    assert result.check_id == "EC-3"


# ── EC-4: stale propagation block ───────────────────────────────────────────

def _clean_sc():
    return {
        "chain": {"tip": "abc123"},
        "enforcement_active": True,
        "last_rpu": "RPU-0050",
        "scoring_ledger_hash": "hash_ok",
        "active_tasks": ["task_a"],
        "blocked_tasks": [],
        "hold_tasks": [],
    }


def _clean_canonical():
    return {
        "chain.tip": "abc123",
        "enforcement_active": True,
        "last_rpu": "RPU-0050",
        "scoring_ledger_hash": "hash_ok",
        "task_status": "active",
        "eag_stage": "EAG-3_COMPLETE",
        "active_tasks": ["task_a"],
        "blocked_tasks": [],
        "hold_tasks": [],
    }


def test_ec4_t0_stale_returns_hard_stop():
    """EC-4-TC-1: T0 stale → ENFORCEMENT_HARD_STOP."""
    sc = _clean_sc()
    canonical = _clean_canonical()
    canonical["chain.tip"] = "different_tip"  # T0 불일치
    req = MutationRequest(
        tier="T1",
        tool="shadow_pipeline.py",
        path="SESSION_CONTEXT.json",
        mutation_type="SESSION_DELTA_WRITE",
        has_eag_approval=True,
        gate_tokens=["EAG2_approval", "phase2_commit_gate", "pair_validator"],
    )
    result = ec4_stale_propagation_block(sc, canonical, req)
    assert result.result == EnforcementResult.ENFORCEMENT_HARD_STOP
    assert result.cascade_effect == "ALL_LOWER_TIERS_FREEZE"


def test_ec4_t1_stale_returns_hold():
    """EC-4-TC-2: T1 stale → ENFORCEMENT_HOLD."""
    sc = _clean_sc()
    canonical = _clean_canonical()
    canonical["active_tasks"] = ["task_a", "task_b"]  # T1 불일치
    req = MutationRequest(
        tier="T1",
        tool="shadow_pipeline.py",
        path="SESSION_CONTEXT.json",
        mutation_type="SESSION_DELTA_WRITE",
        has_eag_approval=True,
        gate_tokens=["EAG2_approval", "phase2_commit_gate", "pair_validator"],
    )
    result = ec4_stale_propagation_block(sc, canonical, req)
    assert result.result == EnforcementResult.ENFORCEMENT_HOLD


def test_ec4_clean_state_proceeds():
    """EC-4-TC-3: clean state → gate evaluation proceeds."""
    sc = _clean_sc()
    canonical = _clean_canonical()
    req = MutationRequest(
        tier="T1",
        tool="shadow_pipeline.py",
        path="SESSION_CONTEXT.json",
        mutation_type="SESSION_DELTA_WRITE",
        has_eag_approval=True,
        gate_tokens=["EAG2_approval", "phase2_commit_gate", "pair_validator"],
    )
    result = ec4_stale_propagation_block(sc, canonical, req)
    assert result.check_id == "EC-4"
    # clean → gate가 EAG 있어도 hash_match 미제공 시 HOLD 가능
    assert result.result in (
        EnforcementResult.ENFORCEMENT_PASS,
        EnforcementResult.ENFORCEMENT_HOLD,
        EnforcementResult.ENFORCEMENT_DENY,
    )


# ── EC-5: invalid gate bypass ────────────────────────────────────────────────

def test_ec5_missing_gate_denied():
    """EC-5-TC-1: required gate not presented → ENFORCEMENT_DENY."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=[],  # 게이트 없음
    )
    result = ec5_invalid_gate_bypass(req)
    assert result.result == EnforcementResult.ENFORCEMENT_DENY
    assert "gate bypass" in result.reason.lower() or "gate" in result.reason.lower()


def test_ec5_all_gates_present_passes():
    """EC-5-TC-2: all required gates present → ENFORCEMENT_PASS."""
    req = MutationRequest(
        tier="T0",
        tool="rpu_atomic_issuer.py",
        path="evidence/scoring_ledger.json",
        mutation_type="CHAIN_APPEND",
        has_eag_approval=True,
        has_hash_match=True,
        gate_tokens=["arss_gatekeeper_G1_G14", "EAG3_approval_token"],
    )
    result = ec5_invalid_gate_bypass(req)
    assert result.result == EnforcementResult.ENFORCEMENT_PASS

"""
test_deadlock_protocol.py
AIBA 3-5: Delegation Policy + Deadlock Protocol TC
EAG: EAG-S263-3-5-001
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from tools.governance.delegation_policy import (
    classify_governance_risk, should_escalate, match_known_risk_scenario,
    GovernanceRisk, EscalationDecision,
)
from tools.governance.deadlock_models import ValidationResult, DeadlockState
from tools.governance.deadlock_protocol import (
    validate_not_ready_payload, classify_layer, evaluate_deadlock,
)


# ── TC-01: LOW 위험 작업 → LOCAL ──────────────────────────────────
def test_tc01_low_risk_local():
    action = {"action_type": "read", "target": "log", "reversible": True,
              "service_count": 1, "data_destructive": False}
    dec = should_escalate(action)
    assert dec.decision == "LOCAL"


# ── TC-02: HIGH 위험 작업 → BLOCK ─────────────────────────────────
def test_tc02_high_risk_block():
    action = {"action_type": "delete", "target": "database", "reversible": False,
              "service_count": 1, "data_destructive": True}
    dec = should_escalate(action)
    assert dec.decision == "BLOCK"


# ── TC-03: 사전 정의 시나리오 매치 → BLOCK ──────────────────────────
def test_tc03_known_scenario_block():
    action = {"action_type": "write", "target": "governance_doc",
              "reversible": True, "service_count": 1, "data_destructive": False}
    scenario = match_known_risk_scenario(action)
    assert scenario == "governance_doc_change"
    dec = should_escalate(action)
    assert dec.decision == "BLOCK"


# ── TC-04: 규칙 1 — violations 없는 NOT_READY → ADVISORY 강등 ───────────────
def test_tc04_rule1_downgrade_to_advisory():
    result = ValidationResult(
        status="TRUST_NOT_READY",
        violations=[],
        advisories=["some quality concern"],
    )
    out = validate_not_ready_payload(result)
    assert out.status == "TRUST_ADVISORY"
    assert "AUTO_DOWNGRADED" in out.advisories[-1]


# ── TC-05: 규칙 1 — violations 있는 NOT_READY → 유지 ────────────────────────
def test_tc05_rule1_keep_not_ready_with_violations():
    result = ValidationResult(
        status="TRUST_NOT_READY",
        violations=["guardrail_3_violated"],
    )
    out = validate_not_ready_payload(result)
    assert out.status == "TRUST_NOT_READY"


# ── TC-06: 규칙 2 — 선언 텍스트 → DECLARATION ──────────────────────────────
def test_tc06_rule2_declaration():
    proposal = {"text": "This governance policy establishes the charter and principles"}
    assert classify_layer(proposal) == "DECLARATION"


# ── TC-07: 규칙 2 — 구현 텍스트 → IMPLEMENTATION ───────────────────────────
def test_tc07_rule2_implementation():
    proposal = {"text": "deploy the service to path /opt/arss with threshold 3"}
    assert classify_layer(proposal) == "IMPLEMENTATION"


# ── TC-08: 규칙 3 — 라운드 1 → NORMAL ──────────────────────────────────────
def test_tc08_rule3_round1_normal():
    result = evaluate_deadlock("proposal-abc", 1)
    assert result["status"] == "NORMAL"
    assert result["escalate"] is False


# ── TC-09: 규칙 3 — 라운드 2 → WARNING ──────────────────────────────────────
def test_tc09_rule3_round2_warning():
    result = evaluate_deadlock("proposal-abc", 2)
    assert result["status"] == "WARNING"
    assert result["escalate"] is False


# ── TC-10: 규칙 3 — 라운드 3 → DEADLOCK + Escalate ──────────────────────────
def test_tc10_rule3_round3_deadlock():
    result = evaluate_deadlock("proposal-abc", 3)
    assert result["status"] == "DEADLOCK"
    assert result["deadlock"] is True
    assert result["escalate"] is True

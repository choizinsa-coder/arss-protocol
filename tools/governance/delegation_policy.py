"""
delegation_policy.py  v1.0
AIBA Governance 3-5: Delegation Policy
EAG: EAG-S263-3-5-001

작업을 LOCAL / ESCALATE / BLOCK 중 하나로 판정한다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class GovernanceRisk:
    level: str  # LOW | MEDIUM | HIGH


@dataclass
class EscalationDecision:
    decision: str   # LOCAL | ESCALATE | BLOCK
    reason: str


# ── 사전 정의 위험 시나리오 ────────────────────────────────────────────────────

KNOWN_RISK_SCENARIOS: list[str] = [
    "governance_doc_change",
    "worm_write",
    "tier_override",
    "multi_service_restart",
    "data_destructive_action",
    "firewall_change",
    "secret_rotation",
]


# ── 공개 API ──────────────────────────────────────────────────────────────────

def classify_governance_risk(action: dict) -> GovernanceRisk:
    """
    action 딕셔너리를 받아 위험 수준을 LOW / MEDIUM / HIGH 로 반환.

    action keys:
        action_type     : str
        target          : str
        reversible      : bool
        service_count   : int
        data_destructive: bool
    """
    reversible       = bool(action.get("reversible", True))
    data_destructive = bool(action.get("data_destructive", False))
    service_count    = int(action.get("service_count", 1))
    action_type      = str(action.get("action_type", "")).lower()
    target           = str(action.get("target", "")).lower()

    # HIGH: 비가역·파괴적·거버넌스 문서 영향
    if data_destructive or not reversible:
        return GovernanceRisk(level="HIGH")
    if any(kw in target for kw in ("governance", "worm", "freeze", "secret")):
        return GovernanceRisk(level="HIGH")
    if any(kw in action_type for kw in ("delete", "drop", "destroy", "override")):
        return GovernanceRisk(level="HIGH")

    # MEDIUM: 설정 변경·서비스 재시작·다중 서비스
    if service_count > 1:
        return GovernanceRisk(level="MEDIUM")
    if any(kw in action_type for kw in ("restart", "config", "update", "patch")):
        return GovernanceRisk(level="MEDIUM")

    return GovernanceRisk(level="LOW")


def should_escalate(action: dict) -> EscalationDecision:
    """
    classify_governance_risk 결과를 기반으로
    LOCAL / ESCALATE / BLOCK 중 하나를 반환.
    """
    risk = classify_governance_risk(action)
    scenario = match_known_risk_scenario(action)

    if scenario is not None:
        return EscalationDecision(
            decision="BLOCK",
            reason=f"known_risk_scenario:{scenario}",
        )

    mapping = {
        "LOW":    EscalationDecision(decision="LOCAL",    reason="low_risk_autonomous"),
        "MEDIUM": EscalationDecision(decision="ESCALATE", reason="medium_risk_requires_review"),
        "HIGH":   EscalationDecision(decision="BLOCK",    reason="high_risk_eag_required"),
    }
    return mapping[risk.level]


def match_known_risk_scenario(action: dict) -> Optional[str]:
    """
    action 이 사전 정의 위험 시나리오에 해당하면 시나리오 ID 반환.
    해당 없으면 None.
    """
    action_type = str(action.get("action_type", "")).lower()
    target      = str(action.get("target", "")).lower()
    combined    = action_type + " " + target

    scenario_keywords: dict[str, list[str]] = {
        "governance_doc_change":  ["governance", "freeze", "govdoc"],
        "worm_write":             ["worm", "journal"],
        "tier_override":          ["tier_override", "tier override"],
        "multi_service_restart":  [],   # service_count > 1 + restart 으로 판정
        "data_destructive_action":["delete", "drop", "destroy"],
        "firewall_change":        ["firewall", "ufw", "iptables"],
        "secret_rotation":        ["secret", "env", "credential"],
    }

    # multi_service_restart 는 별도 조건
    if (int(action.get("service_count", 1)) > 1
            and "restart" in action_type):
        return "multi_service_restart"

    for scenario_id, keywords in scenario_keywords.items():
        if scenario_id == "multi_service_restart":
            continue
        if any(kw in combined for kw in keywords):
            return scenario_id

    return None

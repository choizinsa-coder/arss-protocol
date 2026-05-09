"""
tier_cascade_gate.py
S101 STATE AUTHORITY ARCHITECTURE — T0~T3 cascade enforcement gate
Design ref: REVISION-1
EAG-2 approved by: 비오(Joshua) S111

Default: DENY.
Unknown tier/path/tool/gate = DENY.
Ambiguous authority = HOLD.
"Did forbidden mutation become impossible?" — this is the validation question.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class GateDecision(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    HOLD = "HOLD"
    HARD_STOP = "HARD_STOP"
    LOG_ONLY = "LOG_ONLY"


class ViolationTier(Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    UNKNOWN = "UNKNOWN"


@dataclass
class MutationRequest:
    tier: str
    tool: str
    path: str
    mutation_type: str
    has_eag_approval: bool = False
    has_hash_match: bool = False
    gate_tokens: list[str] = field(default_factory=list)


@dataclass
class GateResult:
    decision: GateDecision
    tier: str
    reason: str
    cascade_effect: Optional[str] = None
    requires_beo_confirmation: bool = False
    violation_type: Optional[str] = None


_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__),
    "mutation_authority_registry_v1.0.json",
)

_registry_cache: Optional[dict] = None


def _load_registry() -> dict:
    """Registry 로드. 실패 시 DENY (fail-closed)."""
    global _registry_cache
    if _registry_cache is not None:
        return _registry_cache
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            _registry_cache = json.load(f)
        return _registry_cache
    except Exception:
        # Registry 로드 실패 = 전체 DENY
        return {}


def _get_tier_config(registry: dict, tier: str) -> Optional[dict]:
    return registry.get("tiers", {}).get(tier)


def _is_allowed_tool(tier_config: dict, tool: str) -> bool:
    return tool in tier_config.get("allowed_tools", [])


def _is_allowed_path(tier_config: dict, path: str) -> bool:
    allowed = tier_config.get("allowed_paths", [])
    return any(
        path == p or path.startswith(p.rstrip("*"))
        for p in allowed
    )


def _is_allowed_mutation_type(tier_config: dict, mutation_type: str) -> bool:
    return mutation_type in tier_config.get("allowed_mutation_types", [])


def _check_required_gates(tier_config: dict, gate_tokens: list[str]) -> bool:
    required = tier_config.get("required_gate", [])
    if not required:
        return True
    return all(g in gate_tokens for g in required)


def evaluate(request: MutationRequest) -> GateResult:
    """
    MutationRequest를 평가하여 GateResult를 반환.

    Default: DENY.
    Unknown tier/path/tool/gate = DENY.
    Ambiguous = HOLD.
    T0 violation = HARD_STOP + cascade to all lower tiers.
    """
    registry = _load_registry()

    # Registry 로드 실패 — fail-closed DENY
    if not registry:
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason="Registry load failed — fail-closed DENY",
            requires_beo_confirmation=True,
            violation_type="REGISTRY_UNAVAILABLE",
        )

    unknown_handling = registry.get("unknown_handling", {})

    # Unknown tier — DENY
    tier_config = _get_tier_config(registry, request.tier)
    if tier_config is None:
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason=f"Unknown tier '{request.tier}' — {unknown_handling.get('unknown_tier', 'DENY')}",
            violation_type="UNKNOWN_TIER",
        )

    # Unknown tool — DENY
    if not _is_allowed_tool(tier_config, request.tool):
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason=f"Unknown tool '{request.tool}' for tier {request.tier} — DENY",
            violation_type="UNKNOWN_TOOL",
        )

    # Unknown path — DENY
    if not _is_allowed_path(tier_config, request.path):
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason=f"Unknown path '{request.path}' for tier {request.tier} — DENY",
            violation_type="UNKNOWN_PATH",
        )

    # Unknown mutation type — DENY
    if not _is_allowed_mutation_type(tier_config, request.mutation_type):
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason=f"Unknown mutation type '{request.mutation_type}' for tier {request.tier} — DENY",
            violation_type="UNKNOWN_MUTATION_TYPE",
        )

    # Missing gate — DENY
    if not _check_required_gates(tier_config, request.gate_tokens):
        required = tier_config.get("required_gate", [])
        missing = [g for g in required if g not in request.gate_tokens]
        return GateResult(
            decision=GateDecision.DENY,
            tier=request.tier,
            reason=f"Missing required gate(s): {missing} — DENY",
            violation_type="MISSING_GATE",
        )

    # T0: EAG 승인 필수
    if request.tier == "T0":
        if not request.has_eag_approval:
            return GateResult(
                decision=GateDecision.HARD_STOP,
                tier="T0",
                reason="T0 mutation requires explicit EAG approval — HARD_STOP",
                cascade_effect="ALL_LOWER_TIERS_FREEZE",
                requires_beo_confirmation=True,
                violation_type="T0_EAG_MISSING",
            )
        if not request.has_hash_match:
            return GateResult(
                decision=GateDecision.HARD_STOP,
                tier="T0",
                reason="T0 mutation requires hash match verification — HARD_STOP",
                cascade_effect="ALL_LOWER_TIERS_FREEZE",
                requires_beo_confirmation=True,
                violation_type="T0_HASH_MISMATCH",
            )

    # T1: EAG 승인 필수
    if request.tier == "T1":
        if not request.has_eag_approval:
            return GateResult(
                decision=GateDecision.HOLD,
                tier="T1",
                reason="T1 mutation requires EAG approval — HOLD",
                cascade_effect="T1_T2_WRITE_HOLD",
                requires_beo_confirmation=True,
                violation_type="T1_EAG_MISSING",
            )

    # T3: LOG_ONLY — mutation 금지
    if request.tier == "T3":
        if request.mutation_type != "LOG_APPEND":
            return GateResult(
                decision=GateDecision.DENY,
                tier="T3",
                reason="T3 is observation only — only LOG_APPEND allowed — DENY",
                violation_type="T3_WRITE_ATTEMPT",
            )
        return GateResult(
            decision=GateDecision.LOG_ONLY,
            tier="T3",
            reason="T3 LOG_APPEND allowed",
        )

    # 모든 검증 통과 — ALLOW
    return GateResult(
        decision=GateDecision.ALLOW,
        tier=request.tier,
        reason=f"All gate conditions met for tier {request.tier}",
    )


def apply_cascade(violation_tier: ViolationTier, registry: Optional[dict] = None) -> dict:
    """
    tier 위반 발생 시 cascade effect를 반환.
    T0 위반 = 전 하위 tier freeze.
    T1 위반 = T1/T2 write hold.
    T2 위반 = warning only.
    T3 = log only.
    upward escalation 금지 (T2 단독으로 T0 유발 불가).
    """
    if registry is None:
        registry = _load_registry()

    cascade_rules = registry.get("cascade_rules", {})

    if violation_tier == ViolationTier.T0:
        rule = cascade_rules.get("T0_violation", {})
        return {
            "violated_tier": "T0",
            "effect": rule.get("effect", "ALL_LOWER_TIERS_FREEZE"),
            "frozen_tiers": rule.get("scope", ["T1", "T2", "T3"]),
            "auto_release": rule.get("auto_release", False),
            "release_requires": rule.get("release_requires", "explicit_beo_eag_approval"),
        }
    if violation_tier == ViolationTier.T1:
        rule = cascade_rules.get("T1_violation", {})
        return {
            "violated_tier": "T1",
            "effect": rule.get("effect", "T1_T2_WRITE_HOLD"),
            "frozen_tiers": rule.get("scope", ["T1", "T2"]),
            "auto_release": rule.get("auto_release", "recovery_evidence_required"),
            "release_conditions": rule.get("release_conditions", []),
        }
    if violation_tier == ViolationTier.T2:
        rule = cascade_rules.get("T2_violation", {})
        return {
            "violated_tier": "T2",
            "effect": rule.get("effect", "WARNING_ONLY"),
            "escalation_to_T1": rule.get("escalation_to_T1", "after_timeout"),
            "upward_to_T0": False,  # upward escalation 금지
        }
    if violation_tier == ViolationTier.T3:
        return {
            "violated_tier": "T3",
            "effect": "LOG_ONLY",
            "escalation": False,
        }
    # UNKNOWN
    return {
        "violated_tier": "UNKNOWN",
        "effect": "DENY",
        "reason": "Unknown violation tier — fail-closed DENY",
    }

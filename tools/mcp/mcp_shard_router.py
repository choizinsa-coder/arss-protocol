"""
AIBA MCP Shard Router  v1.0.1
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C + Recovery Governance Layer
EAG:   EAG-2 비오(Joshua) 승인 (S128) / EAG-3 비오(Joshua) 승인 (S130)

변경 이력:
- v1.0.0 (S128): 최초 구현
- v1.0.1 (S130): HC-T-03 (unauthorized shard access) -> HARD_CONTAINMENT 진입 추가

책임:
- whitelist 기반 shard 라우팅
- agent별 접근 권한 매핑
- 금지 shard / 금지 operation 차단
- read-only 불변성 유지
- HC-T-03: 허용되지 않은 shard 접근 시도 -> enter_containment("HC-T-03")
"""

import logging as _logging
import os
import sys
from typing import Optional

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from mcp_containment_state import enter_containment

ALLOWED_AGENTS = frozenset({"domi", "jeni", "caddy"})

ALL_ALLOWED_SHARDS = frozenset({
    "session_context_active",
    "agent_focus",
    "active_tasks",
    "canonical_rules_summary",
    "phase_status",
    "retrieval_governance_status",
    "mcp_phase_status",
})

FORBIDDEN_SHARDS = frozenset({
    "full_session_context",
    "tier_d_raw_archive",
    "secret_material",
    "credential_store",
    "full_audit_log",
    "dynamic_file_path",
})

FORBIDDEN_OPERATIONS = frozenset({
    "get_all_context",
    "bulk_preload",
    "archive_bulk_load",
    "arbitrary_retrieval_expansion",
})

_AGENT_SHARD_MAP: dict[str, frozenset] = {
    "domi": frozenset({
        "session_context_active",
        "agent_focus",
        "canonical_rules_summary",
        "phase_status",
        "retrieval_governance_status",
        "mcp_phase_status",
    }),
    "jeni": frozenset({
        "session_context_active",
        "agent_focus",
        "canonical_rules_summary",
        "phase_status",
        "retrieval_governance_status",
        "mcp_phase_status",
    }),
    "caddy": frozenset({
        "session_context_active",
        "agent_focus",
        "active_tasks",
        "canonical_rules_summary",
        "phase_status",
        "retrieval_governance_status",
        "mcp_phase_status",
    }),
}

# HC-T-03 탐지 대상: FORBIDDEN_SHARD 또는 AGENT_SHARD_PERMISSION_DENIED
_HC_T03_REASONS = frozenset({
    "FORBIDDEN_SHARD",
    "AGENT_SHARD_PERMISSION_DENIED",
})


class ShardRouteResult:
    def __init__(
        self,
        allowed: bool,
        shard: Optional[str],
        agent_id: Optional[str],
        reason: str,
        load_state: str,
        retrieval_class: str,
    ):
        self.allowed = allowed
        self.shard = shard
        self.agent_id = agent_id
        self.reason = reason
        self.load_state = load_state
        self.retrieval_class = retrieval_class


def route_shard(agent_id: str, requested_shard: str) -> ShardRouteResult:
    """
    shard 접근 라우팅.
    HC-T-03: FORBIDDEN_SHARD 또는 AGENT_SHARD_PERMISSION_DENIED 시 HARD_CONTAINMENT 진입.
    """
    if requested_shard in FORBIDDEN_OPERATIONS:
        return ShardRouteResult(
            allowed=False, shard=requested_shard, agent_id=agent_id,
            reason="FORBIDDEN_OPERATION", load_state="DENIED", retrieval_class="CLASS-D",
        )

    if requested_shard in FORBIDDEN_SHARDS:
        # HC-T-03: 명시적 금지 shard 접근 시도
        _trigger_hct03()
        return ShardRouteResult(
            allowed=False, shard=requested_shard, agent_id=agent_id,
            reason="FORBIDDEN_SHARD", load_state="DENIED", retrieval_class="CLASS-D",
        )

    if requested_shard not in ALL_ALLOWED_SHARDS:
        return ShardRouteResult(
            allowed=False, shard=requested_shard, agent_id=agent_id,
            reason="SHARD_NOT_IN_WHITELIST", load_state="DENIED", retrieval_class="CLASS-D",
        )

    agent_shards = _AGENT_SHARD_MAP.get(agent_id, frozenset())
    if requested_shard not in agent_shards:
        # HC-T-03: agent 권한 초과 접근 시도
        _trigger_hct03()
        return ShardRouteResult(
            allowed=False, shard=requested_shard, agent_id=agent_id,
            reason="AGENT_SHARD_PERMISSION_DENIED", load_state="DENIED", retrieval_class="CLASS-C",
        )

    return ShardRouteResult(
        allowed=True, shard=requested_shard, agent_id=agent_id,
        reason="ALLOWED", load_state="LOADED", retrieval_class="CLASS-B",
    )


def _trigger_hct03() -> None:
    """HC-T-03: unauthorized shard access -> HARD_CONTAINMENT 진입."""
    try:
        enter_containment("HC-T-03")
    except Exception as _rule6_e:
        _logging.debug("RULE6 mcp_shard_router: %s", _rule6_e)


def get_agent_allowed_shards(agent_id: str) -> frozenset:
    """agent별 허용 shard 목록 반환 (테스트·감사용)."""
    return _AGENT_SHARD_MAP.get(agent_id, frozenset())

"""
AIBA MCP Shard Router  v1.0.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
설계:  도미 PHASE-C FINAL ANCHOR (S128)

책임:
- whitelist 기반 shard 라우팅
- agent별 접근 권한 매핑
- 금지 shard / 금지 operation 차단
- read-only 불변성 유지
"""

from typing import Optional

# 허용 agent 목록 (고정)
ALLOWED_AGENTS = frozenset({"domi", "jeni", "caddy"})

# 허용 shard 전체 목록 (고정)
ALL_ALLOWED_SHARDS = frozenset({
    "session_context_active",
    "agent_focus",
    "active_tasks",
    "canonical_rules_summary",
    "phase_status",
    "retrieval_governance_status",
    "mcp_phase_status",
})

# 금지 shard 목록 (명시적 차단)
FORBIDDEN_SHARDS = frozenset({
    "full_session_context",
    "tier_d_raw_archive",
    "secret_material",
    "credential_store",
    "full_audit_log",
    "dynamic_file_path",
})

# 금지 operation 목록
FORBIDDEN_OPERATIONS = frozenset({
    "get_all_context",
    "bulk_preload",
    "archive_bulk_load",
    "arbitrary_retrieval_expansion",
})

# agent별 접근 가능 shard 매핑
# 도미: 설계 관련 / 제니: 검증 관련 / 캐디: 구현 관련
# 공통 shard는 전원 접근 가능
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
    ALLOW / DENY 판정 및 사유 반환.
    """
    # 금지 operation 감지
    if requested_shard in FORBIDDEN_OPERATIONS:
        return ShardRouteResult(
            allowed=False,
            shard=requested_shard,
            agent_id=agent_id,
            reason="FORBIDDEN_OPERATION",
            load_state="DENIED",
            retrieval_class="CLASS-D",
        )

    # 금지 shard 감지
    if requested_shard in FORBIDDEN_SHARDS:
        return ShardRouteResult(
            allowed=False,
            shard=requested_shard,
            agent_id=agent_id,
            reason="FORBIDDEN_SHARD",
            load_state="DENIED",
            retrieval_class="CLASS-D",
        )

    # 허용 shard 목록 외 요청
    if requested_shard not in ALL_ALLOWED_SHARDS:
        return ShardRouteResult(
            allowed=False,
            shard=requested_shard,
            agent_id=agent_id,
            reason="SHARD_NOT_IN_WHITELIST",
            load_state="DENIED",
            retrieval_class="CLASS-D",
        )

    # agent별 권한 확인
    agent_shards = _AGENT_SHARD_MAP.get(agent_id, frozenset())
    if requested_shard not in agent_shards:
        return ShardRouteResult(
            allowed=False,
            shard=requested_shard,
            agent_id=agent_id,
            reason="AGENT_SHARD_PERMISSION_DENIED",
            load_state="DENIED",
            retrieval_class="CLASS-C",
        )

    return ShardRouteResult(
        allowed=True,
        shard=requested_shard,
        agent_id=agent_id,
        reason="ALLOWED",
        load_state="LOADED",
        retrieval_class="CLASS-B",
    )


def get_agent_allowed_shards(agent_id: str) -> frozenset:
    """agent별 허용 shard 목록 반환 (테스트·감사용)."""
    return _AGENT_SHARD_MAP.get(agent_id, frozenset())

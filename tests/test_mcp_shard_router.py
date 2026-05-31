# RULE-8 ASSERTION — S181 Batch-12A
# Module: mcp_shard_router
# Task: P4-C4 Phase-beta Batch-12A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest


def _route(agent_id, shard):
    from tools.mcp.mcp_shard_router import route_shard
    return route_shard(agent_id, shard)


def test_sr_forbidden_shard_denied():
    """SR-1: FORBIDDEN_SHARD 접근 → allowed=False / reason=FORBIDDEN_SHARD."""
    result = _route("caddy", "full_session_context")
    assert result.allowed is False
    assert result.reason == "FORBIDDEN_SHARD"


def test_sr_forbidden_operation_denied():
    """SR-2: FORBIDDEN_OPERATION 접근 → allowed=False / reason=FORBIDDEN_OPERATION."""
    result = _route("caddy", "get_all_context")
    assert result.allowed is False
    assert result.reason == "FORBIDDEN_OPERATION"


def test_sr_shard_not_in_whitelist_denied():
    """SR-3: whitelist에 없는 shard → allowed=False / reason=SHARD_NOT_IN_WHITELIST."""
    result = _route("caddy", "nonexistent_shard_xyz")
    assert result.allowed is False
    assert result.reason == "SHARD_NOT_IN_WHITELIST"


def test_sr_agent_permission_denied_for_restricted_shard():
    """SR-4: agent 권한 초과 shard → allowed=False / reason=AGENT_SHARD_PERMISSION_DENIED.
    domi는 active_tasks에 접근 불가 (caddy 전용).
    """
    result = _route("domi", "active_tasks")
    assert result.allowed is False
    assert result.reason == "AGENT_SHARD_PERMISSION_DENIED"


def test_sr_unknown_agent_returns_empty_allowed_shards():
    """SR-5: 알 수 없는 agent_id → get_agent_allowed_shards == frozenset()."""
    from tools.mcp.mcp_shard_router import get_agent_allowed_shards
    result = get_agent_allowed_shards("unknown_agent_xyz")
    assert result == frozenset()

"""
AIBA MCP Server POC PHASE-C Test Suite
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
"""

import hashlib
import hmac
import os
import sys
import time

# sys.path 주입 — importlib 모드 대응 (caddy_operational_rules.importlib_syspath_rule)
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/mcp")

import pytest

os.environ["AIBA_MCP_SECRET_DOMI"]  = "test-secret-domi"
os.environ["AIBA_MCP_SECRET_JENI"]  = "test-secret-jeni"
os.environ["AIBA_MCP_SECRET_CADDY"] = "test-secret-caddy"

from mcp_audit_broker import read_audit_log
from mcp_nonce_store import clear_nonce_store
from mcp_server_poc import BIND_ADDRESS, handle_retrieval
from mcp_shard_router import get_agent_allowed_shards


def _make_signature(agent_id, timestamp, nonce, secret):
    message = f"{agent_id}:{timestamp}:{nonce}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _valid_request(agent_id="caddy", shard="active_tasks",
                   secret="test-secret-caddy", nonce=None, timestamp_offset=0.0):
    ts = str(time.time() + timestamp_offset)
    n  = nonce or f"nonce-{time.time_ns()}"
    sig = _make_signature(agent_id, ts, n, secret)
    return {"agent_id": agent_id, "timestamp": ts, "nonce": n, "signature": sig, "shard": shard}


@pytest.fixture(autouse=True)
def reset_nonce_store():
    clear_nonce_store()
    yield
    clear_nonce_store()


@pytest.fixture
def tmp_log(tmp_path):
    return str(tmp_path / "test_audit.log")


def test_tc1_valid_agent_valid_signature_allow(tmp_log):
    """TC-1: 유효 agent + 유효 서명 → ALLOW"""
    result = handle_retrieval(_valid_request(), log_path=tmp_log)
    assert result["ok"] is True
    assert result["load_state"] == "LOADED"


def test_tc2_agent_not_in_allowlist_deny(tmp_log):
    """TC-2: allowlist 외 agent_id → DENY"""
    req = _valid_request(agent_id="unknown_agent", secret="any")
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["error_code"] == "DENIED"
    assert result["load_state"] == "DENIED"


def test_tc3_invalid_signature_deny(tmp_log):
    """TC-3: 서명 무효 → DENY"""
    req = _valid_request()
    req["signature"] = "0" * 64
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "INVALID_SIGNATURE"


def test_tc4_timestamp_expired_deny(tmp_log):
    """TC-4: timestamp 만료 (±60초 초과) → DENY"""
    result = handle_retrieval(_valid_request(timestamp_offset=-120.0), log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "TIMESTAMP_EXPIRED"


def test_tc5_nonce_reused_deny(tmp_log):
    """TC-5: nonce 재사용 → DENY"""
    fixed_nonce = "fixed-nonce-replay-test"
    r1 = handle_retrieval(_valid_request(nonce=fixed_nonce), log_path=tmp_log)
    assert r1["ok"] is True
    r2 = handle_retrieval(_valid_request(nonce=fixed_nonce), log_path=tmp_log)
    assert r2["ok"] is False
    assert r2["reason"] == "NONCE_REUSED"


def test_tc6_allowed_shard_returns_data(tmp_log):
    """TC-6: 허용 shard 요청 → 정상 반환"""
    result = handle_retrieval(_valid_request(shard="active_tasks"), log_path=tmp_log)
    assert result["ok"] is True
    assert result["shard"] == "active_tasks"
    assert "data" in result


def test_tc7_forbidden_shard_deny(tmp_log):
    """TC-7: 금지 shard 요청 → DENY"""
    result = handle_retrieval(_valid_request(shard="tier_d_raw_archive"), log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] in ("FORBIDDEN_SHARD", "SHARD_NOT_IN_WHITELIST")


def test_tc8_get_all_context_deny(tmp_log):
    """TC-8: get_all_context 요청 → DENY"""
    result = handle_retrieval(_valid_request(shard="get_all_context"), log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "FORBIDDEN_OPERATION"


def test_tc9_deny_audit_recorded(tmp_log):
    """TC-9: DENY 시 audit 기록 확인"""
    handle_retrieval(_valid_request(agent_id="hacker", secret="x"), log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    assert any(r["decision"] == "DENY" for r in records)


def test_tc10_allow_audit_10_fields(tmp_log):
    """TC-10: ALLOW 시 audit 10개 필드 전항목 확인"""
    handle_retrieval(_valid_request(), log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    allow_records = [r for r in records if r["decision"] == "ALLOW"]
    assert len(allow_records) >= 1
    required = {"timestamp", "agent_id", "requested_shard", "returned_scope",
                "decision", "reason", "source_hash", "load_state",
                "retrieval_class", "nonce_hash"}
    for field in required:
        assert field in allow_records[0], f"누락 필드: {field}"


def test_tc11_localhost_bind_constant():
    """TC-11: BIND_ADDRESS = 127.0.0.1 확인"""
    assert BIND_ADDRESS == "127.0.0.1"


def test_tc12_nonce_hash_in_audit(tmp_log):
    """TC-12: nonce_hash audit 필드 포함 확인"""
    handle_retrieval(_valid_request(), log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    allow_records = [r for r in records if r["decision"] == "ALLOW"]
    assert len(allow_records) >= 1
    assert allow_records[0].get("nonce_hash") is not None


def test_tc13_domi_shard_access(tmp_log):
    """TC-13: domi shard 권한 확인"""
    allowed = get_agent_allowed_shards("domi")
    assert "session_context_active" in allowed
    assert "active_tasks" not in allowed
    result = handle_retrieval(
        _valid_request(agent_id="domi", shard="session_context_active", secret="test-secret-domi"),
        log_path=tmp_log
    )
    assert result["ok"] is True


def test_tc14_jeni_shard_access(tmp_log):
    """TC-14: jeni shard 권한 확인"""
    allowed = get_agent_allowed_shards("jeni")
    assert "retrieval_governance_status" in allowed
    result = handle_retrieval(
        _valid_request(agent_id="jeni", shard="retrieval_governance_status", secret="test-secret-jeni"),
        log_path=tmp_log
    )
    assert result["ok"] is True


def test_tc15_caddy_shard_access(tmp_log):
    """TC-15: caddy shard 권한 확인"""
    allowed = get_agent_allowed_shards("caddy")
    assert "active_tasks" in allowed
    result = handle_retrieval(
        _valid_request(agent_id="caddy", shard="active_tasks", secret="test-secret-caddy"),
        log_path=tmp_log
    )
    assert result["ok"] is True


def test_tc16_read_only_invariant(tmp_log):
    """TC-16: read-only invariant 확인"""
    result = handle_retrieval(_valid_request(), log_path=tmp_log)
    assert result["ok"] is True
    write_fields = {"write", "mutate", "delete", "update", "modify"}
    for field in write_fields:
        assert field not in result
        assert field not in result.get("data", {})

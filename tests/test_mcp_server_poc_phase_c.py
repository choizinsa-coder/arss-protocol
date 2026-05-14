"""
AIBA MCP Server POC PHASE-C Test Suite  v3
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
TC-1~16
"""

import hashlib
import hmac
import os
import sys
import time

# sys.path 주입 (importlib_syspath_rule)
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/mcp")

import pytest

os.environ["AIBA_MCP_SECRET_DOMI"]  = "test-secret-domi"
os.environ["AIBA_MCP_SECRET_JENI"]  = "test-secret-jeni"
os.environ["AIBA_MCP_SECRET_CADDY"] = "test-secret-caddy"

from mcp_audit_broker import read_audit_log
from mcp_nonce_store import clear_nonce_store
from mcp_server_poc_phase_c import BIND_ADDRESS, handle_retrieval
from mcp_shard_router import get_agent_allowed_shards


def _sig(agent_id, ts, nonce, secret):
    msg = f"{agent_id}:{ts}:{nonce}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _req(agent_id="caddy", shard="active_tasks", secret="test-secret-caddy",
         nonce=None, offset=0.0):
    ts = str(time.time() + offset)
    n  = nonce or f"n-{time.time_ns()}"
    return {"agent_id": agent_id, "timestamp": ts, "nonce": n,
            "signature": _sig(agent_id, ts, n, secret), "shard": shard}


@pytest.fixture(autouse=True)
def reset():
    clear_nonce_store()
    yield
    clear_nonce_store()


@pytest.fixture
def log(tmp_path):
    return str(tmp_path / "audit.log")


def test_tc1_allow(log):
    r = handle_retrieval(_req(), log_path=log)
    assert r["ok"] is True and r["load_state"] == "LOADED"

def test_tc2_unknown_agent_deny(log):
    r = handle_retrieval(_req(agent_id="hacker", secret="x"), log_path=log)
    assert r["ok"] is False and r["error_code"] == "DENIED"

def test_tc3_bad_signature_deny(log):
    req = _req(); req["signature"] = "0" * 64
    r = handle_retrieval(req, log_path=log)
    assert r["ok"] is False and r["reason"] == "INVALID_SIGNATURE"

def test_tc4_expired_timestamp_deny(log):
    r = handle_retrieval(_req(offset=-120.0), log_path=log)
    assert r["ok"] is False and r["reason"] == "TIMESTAMP_EXPIRED"

def test_tc5_nonce_reuse_deny(log):
    n = "fixed-nonce-001"
    assert handle_retrieval(_req(nonce=n), log_path=log)["ok"] is True
    r = handle_retrieval(_req(nonce=n), log_path=log)
    assert r["ok"] is False and r["reason"] == "NONCE_REUSED"

def test_tc6_allowed_shard(log):
    r = handle_retrieval(_req(shard="active_tasks"), log_path=log)
    assert r["ok"] is True and r["shard"] == "active_tasks"

def test_tc7_forbidden_shard_deny(log):
    r = handle_retrieval(_req(shard="tier_d_raw_archive"), log_path=log)
    assert r["ok"] is False

def test_tc8_get_all_context_deny(log):
    r = handle_retrieval(_req(shard="get_all_context"), log_path=log)
    assert r["ok"] is False and r["reason"] == "FORBIDDEN_OPERATION"

def test_tc9_deny_audit_recorded(log):
    handle_retrieval(_req(agent_id="hacker", secret="x"), log_path=log)
    assert any(r["decision"] == "DENY" for r in read_audit_log(log_path=log))

def test_tc10_allow_audit_10_fields(log):
    handle_retrieval(_req(), log_path=log)
    allow = [r for r in read_audit_log(log_path=log) if r["decision"] == "ALLOW"]
    assert len(allow) >= 1
    for f in {"timestamp","agent_id","requested_shard","returned_scope",
              "decision","reason","source_hash","load_state","retrieval_class","nonce_hash"}:
        assert f in allow[0], f"누락: {f}"

def test_tc11_bind_address():
    assert BIND_ADDRESS == "127.0.0.1"

def test_tc12_nonce_hash_in_audit(log):
    handle_retrieval(_req(), log_path=log)
    allow = [r for r in read_audit_log(log_path=log) if r["decision"] == "ALLOW"]
    assert allow and allow[0].get("nonce_hash") is not None

def test_tc13_domi_access(log):
    allowed = get_agent_allowed_shards("domi")
    assert "session_context_active" in allowed
    assert "active_tasks" not in allowed
    r = handle_retrieval(_req(agent_id="domi", shard="session_context_active",
                              secret="test-secret-domi"), log_path=log)
    assert r["ok"] is True

def test_tc14_jeni_access(log):
    r = handle_retrieval(_req(agent_id="jeni", shard="retrieval_governance_status",
                              secret="test-secret-jeni"), log_path=log)
    assert r["ok"] is True

def test_tc15_caddy_access(log):
    r = handle_retrieval(_req(agent_id="caddy", shard="active_tasks",
                              secret="test-secret-caddy"), log_path=log)
    assert r["ok"] is True

def test_tc16_read_only(log):
    r = handle_retrieval(_req(), log_path=log)
    assert r["ok"] is True
    for f in {"write","mutate","delete","update","modify"}:
        assert f not in r and f not in r.get("data", {})

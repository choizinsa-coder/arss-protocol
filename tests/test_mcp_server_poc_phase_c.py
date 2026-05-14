"""
AIBA MCP Server POC PHASE-C Test Suite
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)

TC-1  유효 agent + 유효 서명 → ALLOW
TC-2  allowlist 외 agent_id → DENY
TC-3  서명 무효 → DENY
TC-4  timestamp 만료 → DENY
TC-5  nonce 재사용 → DENY
TC-6  허용 shard 요청 → 정상 반환
TC-7  금지 shard 요청 → DENY
TC-8  get_all_context 요청 → DENY
TC-9  DENY 시 audit 기록 확인
TC-10 ALLOW 시 audit 10개 필드 전항목 확인
TC-11 127.0.0.1 bind 상수 확인
TC-12 nonce_hash audit 필드 포함 확인
TC-13 domi shard 권한 범위 확인
TC-14 jeni shard 권한 범위 확인
TC-15 caddy shard 권한 범위 확인
TC-16 read-only invariant — ALLOW 응답에 write 필드 없음 확인
"""

import hashlib
import hmac
import os
import tempfile
import time

import pytest

# 테스트용 secret 환경변수 설정
os.environ["AIBA_MCP_SECRET_DOMI"]  = "test-secret-domi"
os.environ["AIBA_MCP_SECRET_JENI"]  = "test-secret-jeni"
os.environ["AIBA_MCP_SECRET_CADDY"] = "test-secret-caddy"

from mcp_audit_broker import read_audit_log
from mcp_nonce_store import clear_nonce_store
from mcp_server_poc import BIND_ADDRESS, handle_retrieval
from mcp_shard_router import get_agent_allowed_shards


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_signature(agent_id: str, timestamp: str, nonce: str, secret: str) -> str:
    message = f"{agent_id}:{timestamp}:{nonce}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _valid_request(
    agent_id: str = "caddy",
    shard: str = "active_tasks",
    secret: str = "test-secret-caddy",
    nonce: str = None,
    timestamp_offset: float = 0.0,
) -> dict:
    ts = str(time.time() + timestamp_offset)
    n  = nonce or f"nonce-{time.time_ns()}"
    sig = _make_signature(agent_id, ts, n, secret)
    return {
        "agent_id":  agent_id,
        "timestamp": ts,
        "nonce":     n,
        "signature": sig,
        "shard":     shard,
    }


@pytest.fixture(autouse=True)
def reset_nonce_store():
    """각 테스트 전 nonce 저장소 초기화."""
    clear_nonce_store()
    yield
    clear_nonce_store()


@pytest.fixture
def tmp_log(tmp_path):
    return str(tmp_path / "test_audit.log")


# ── TC-1 ~ TC-16 ──────────────────────────────────────────────────────────────

def test_tc1_valid_agent_valid_signature_allow(tmp_log):
    """TC-1: 유효 agent + 유효 서명 → ALLOW"""
    req = _valid_request()
    result = handle_retrieval(req, log_path=tmp_log)
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
    req["signature"] = "invalidsignature000000000000000000000000000000000000000000000000"
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "INVALID_SIGNATURE"


def test_tc4_timestamp_expired_deny(tmp_log):
    """TC-4: timestamp 만료 (±60초 초과) → DENY"""
    req = _valid_request(timestamp_offset=-120.0)  # 120초 전
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "TIMESTAMP_EXPIRED"


def test_tc5_nonce_reused_deny(tmp_log):
    """TC-5: nonce 재사용 → DENY"""
    fixed_nonce = "fixed-nonce-replay-test"
    req1 = _valid_request(nonce=fixed_nonce)
    req2 = _valid_request(nonce=fixed_nonce)

    # 첫 번째 요청: ALLOW
    r1 = handle_retrieval(req1, log_path=tmp_log)
    assert r1["ok"] is True

    # 두 번째 요청: DENY (nonce 재사용)
    r2 = handle_retrieval(req2, log_path=tmp_log)
    assert r2["ok"] is False
    assert r2["reason"] == "NONCE_REUSED"


def test_tc6_allowed_shard_returns_data(tmp_log):
    """TC-6: 허용 shard 요청 → 정상 반환"""
    req = _valid_request(shard="active_tasks")
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is True
    assert result["shard"] == "active_tasks"
    assert "data" in result


def test_tc7_forbidden_shard_deny(tmp_log):
    """TC-7: 금지 shard 요청 → DENY"""
    req = _valid_request(shard="tier_d_raw_archive")
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] in ("FORBIDDEN_SHARD", "SHARD_NOT_IN_WHITELIST")


def test_tc8_get_all_context_deny(tmp_log):
    """TC-8: get_all_context 요청 → DENY (Lock-3 / Lock-8)"""
    req = _valid_request(shard="get_all_context")
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is False
    assert result["reason"] == "FORBIDDEN_OPERATION"


def test_tc9_deny_audit_recorded(tmp_log):
    """TC-9: DENY 시 audit 기록 확인"""
    req = _valid_request(agent_id="hacker", secret="x")
    handle_retrieval(req, log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    assert len(records) >= 1
    deny_records = [r for r in records if r["decision"] == "DENY"]
    assert len(deny_records) >= 1


def test_tc10_allow_audit_10_fields(tmp_log):
    """TC-10: ALLOW 시 audit 10개 필드 전항목 확인"""
    req = _valid_request()
    handle_retrieval(req, log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    allow_records = [r for r in records if r["decision"] == "ALLOW"]
    assert len(allow_records) >= 1
    required_fields = {
        "timestamp", "agent_id", "requested_shard", "returned_scope",
        "decision", "reason", "source_hash", "load_state",
        "retrieval_class", "nonce_hash",
    }
    for field in required_fields:
        assert field in allow_records[0], f"누락 필드: {field}"


def test_tc11_localhost_bind_constant():
    """TC-11: BIND_ADDRESS = 127.0.0.1 확인"""
    assert BIND_ADDRESS == "127.0.0.1"


def test_tc12_nonce_hash_in_audit(tmp_log):
    """TC-12: nonce_hash audit 필드 포함 확인"""
    req = _valid_request()
    handle_retrieval(req, log_path=tmp_log)
    records = read_audit_log(log_path=tmp_log)
    allow_records = [r for r in records if r["decision"] == "ALLOW"]
    assert len(allow_records) >= 1
    assert "nonce_hash" in allow_records[0]
    assert allow_records[0]["nonce_hash"] is not None


def test_tc13_domi_shard_access(tmp_log):
    """TC-13: domi 접근 가능 shard 확인"""
    allowed = get_agent_allowed_shards("domi")
    assert "session_context_active" in allowed
    assert "canonical_rules_summary" in allowed
    # active_tasks는 domi 권한 밖
    assert "active_tasks" not in allowed

    req = _valid_request(
        agent_id="domi",
        shard="session_context_active",
        secret="test-secret-domi",
    )
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is True


def test_tc14_jeni_shard_access(tmp_log):
    """TC-14: jeni 접근 가능 shard 확인"""
    allowed = get_agent_allowed_shards("jeni")
    assert "retrieval_governance_status" in allowed
    assert "phase_status" in allowed

    req = _valid_request(
        agent_id="jeni",
        shard="retrieval_governance_status",
        secret="test-secret-jeni",
    )
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is True


def test_tc15_caddy_shard_access(tmp_log):
    """TC-15: caddy 접근 가능 shard 확인"""
    allowed = get_agent_allowed_shards("caddy")
    assert "active_tasks" in allowed
    assert "mcp_phase_status" in allowed

    req = _valid_request(
        agent_id="caddy",
        shard="active_tasks",
        secret="test-secret-caddy",
    )
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is True


def test_tc16_read_only_invariant(tmp_log):
    """TC-16: read-only invariant — ALLOW 응답에 write 관련 필드 없음"""
    req = _valid_request()
    result = handle_retrieval(req, log_path=tmp_log)
    assert result["ok"] is True
    # write 관련 필드 부재 확인
    write_fields = {"write", "mutate", "delete", "update", "modify"}
    for field in write_fields:
        assert field not in result, f"write 필드 감지: {field}"
    # data 내부에도 write 필드 없음
    data = result.get("data", {})
    for field in write_fields:
        assert field not in data, f"data 내 write 필드 감지: {field}"

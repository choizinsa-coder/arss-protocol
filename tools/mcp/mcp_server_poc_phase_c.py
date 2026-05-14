"""
AIBA MCP Server POC PHASE-C  v0.4.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
설계:  도미 PHASE-C FINAL ANCHOR (S128)

PHASE-C 전용 모듈 — PHASE-B mcp_server_poc.py와 독립.
PHASE-B 기능(Throttling/AuditBroker/ThrottleGuard 등)은 mcp_server_poc.py 유지.

계약:
- deny-by-default
- allowlist: domi / jeni / caddy
- HMAC 4요소: agent_id + timestamp + nonce + signature
- localhost 127.0.0.1 bind only
- Lock-3 / Lock-5 / Lock-7 / Lock-8 유지
"""

import hashlib
import hmac
import os
import sys
import time
from typing import Optional

# sys.path — tools/mcp 하위 모듈 접근
_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_nonce_store import consume_nonce, is_nonce_used
from mcp_shard_router import ALLOWED_AGENTS, FORBIDDEN_OPERATIONS, route_shard

# ── 상수 ──────────────────────────────────────────────────────────────────────

VERSION = "0.4.0"
TIMESTAMP_TOLERANCE_SECONDS = 60
CREDENTIAL_TTL_SECONDS = 900
BIND_ADDRESS = "127.0.0.1"
FAIL_CLOSED_POLICY = True
MCP_LAYER = {"L0": "identity_verification", "L1": "shard_routing"}

_SECRET_ENV_MAP = {
    "domi":  "AIBA_MCP_SECRET_DOMI",
    "jeni":  "AIBA_MCP_SECRET_JENI",
    "caddy": "AIBA_MCP_SECRET_CADDY",
}


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _get_agent_secret(agent_id: str) -> Optional[bytes]:
    env_key = _SECRET_ENV_MAP.get(agent_id)
    if env_key is None:
        return None
    secret = os.environ.get(env_key)
    if not secret:
        return None
    return secret.encode()


def _verify_hmac_signature(agent_id: str, timestamp: str, nonce: str, signature: str) -> bool:
    secret = _get_agent_secret(agent_id)
    if secret is None:
        return False
    message = f"{agent_id}:{timestamp}:{nonce}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_timestamp(timestamp_str: str) -> bool:
    try:
        request_time = float(timestamp_str)
    except (ValueError, TypeError):
        return False
    return abs(time.time() - request_time) <= TIMESTAMP_TOLERANCE_SECONDS


# ── 응답 생성 ─────────────────────────────────────────────────────────────────

def _deny_response(reason: str) -> dict:
    return {"ok": False, "error_code": "DENIED", "reason": reason, "load_state": "DENIED"}


def _allow_response(shard: str, data: dict, load_state: str, retrieval_class: str) -> dict:
    return {
        "ok": True,
        "shard": shard,
        "data": data,
        "load_state": load_state,
        "retrieval_class": retrieval_class,
        "source_hash": "PLACEHOLDER",
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()),
        "canonical_epoch": None,
    }


# ── L0: Identity Verification ─────────────────────────────────────────────────

def verify_identity(request: dict, log_path: Optional[str] = None):
    agent_id  = request.get("agent_id", "")
    timestamp = request.get("timestamp", "")
    nonce     = request.get("nonce", "")
    signature = request.get("signature", "")
    shard     = request.get("shard", "UNKNOWN")

    if agent_id not in ALLOWED_AGENTS:
        write_deny_audit(agent_id=agent_id or "UNKNOWN", requested_shard=shard,
                         reason="AGENT_NOT_IN_ALLOWLIST", nonce=nonce or None, log_path=log_path)
        return False, "AGENT_NOT_IN_ALLOWLIST", None

    if not _verify_timestamp(timestamp):
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="TIMESTAMP_EXPIRED", nonce=nonce or None, log_path=log_path)
        return False, "TIMESTAMP_EXPIRED", None

    if is_nonce_used(nonce):
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="NONCE_REUSED", nonce=nonce, log_path=log_path)
        return False, "NONCE_REUSED", None

    if not _verify_hmac_signature(agent_id, timestamp, nonce, signature):
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="INVALID_SIGNATURE", nonce=nonce, log_path=log_path)
        return False, "INVALID_SIGNATURE", None

    if not consume_nonce(nonce):
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="NONCE_CONSUME_FAILED", nonce=nonce, log_path=log_path)
        return False, "NONCE_CONSUME_FAILED", None

    return True, "IDENTITY_VERIFIED", nonce


# ── L1: Shard Routing ─────────────────────────────────────────────────────────

def handle_retrieval(request: dict, log_path: Optional[str] = None) -> dict:
    agent_id       = request.get("agent_id", "UNKNOWN")
    requested_shard = request.get("shard", "UNKNOWN")

    if requested_shard in FORBIDDEN_OPERATIONS:
        write_deny_audit(agent_id=agent_id, requested_shard=requested_shard,
                         reason="FORBIDDEN_OPERATION", log_path=log_path)
        return _deny_response("FORBIDDEN_OPERATION")

    ok, reason, nonce = verify_identity(request, log_path=log_path)
    if not ok:
        return _deny_response(reason)

    route = route_shard(agent_id, requested_shard)
    if not route.allowed:
        write_deny_audit(agent_id=agent_id, requested_shard=requested_shard,
                         reason=route.reason, nonce=nonce, log_path=log_path)
        return _deny_response(route.reason)

    write_audit(
        agent_id=agent_id, requested_shard=requested_shard,
        returned_scope=requested_shard, decision="ALLOW", reason="ALLOWED",
        source_hash="PLACEHOLDER", load_state=route.load_state,
        retrieval_class=route.retrieval_class, nonce=nonce, log_path=log_path,
    )
    return _allow_response(
        shard=requested_shard,
        data={"shard": requested_shard, "content": "SHARD_DATA_PLACEHOLDER"},
        load_state=route.load_state,
        retrieval_class=route.retrieval_class,
    )

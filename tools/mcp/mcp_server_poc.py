"""
AIBA MCP Server POC  v0.4.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
설계:  도미 PHASE-C FINAL ANCHOR (S128)

변경:
- v0.3.0 (PHASE-B): Throttling / Audit Isolation / Timeout / Freshness / Routing Integrity
- v0.4.0 (PHASE-C): HMAC 4요소 인증 / shard 라우팅 / agent 권한 매핑 / localhost bind 강제

계약:
- deny-by-default
- allowlist: domi / jeni / caddy
- HMAC 4요소: agent_id + timestamp + nonce + signature
- localhost 127.0.0.1 bind only
- Lock-3 / Lock-5 / Lock-7 / Lock-8 유지
"""

import hashlib
import hmac
import json
import os
import time
from typing import Optional

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_nonce_store import consume_nonce, is_nonce_used
from mcp_shard_router import (
    ALLOWED_AGENTS,
    FORBIDDEN_OPERATIONS,
    route_shard,
)

# ── 상수 ──────────────────────────────────────────────────────────────────────

VERSION = "0.4.0"

# timestamp 허용 오차: ±60초
TIMESTAMP_TOLERANCE_SECONDS = 60

# TTL: 15분
CREDENTIAL_TTL_SECONDS = 900

# bind 주소 — public bind 금지
BIND_ADDRESS = "127.0.0.1"

# FAIL_CLOSED_POLICY: 인증 실패 시 즉시 DENY
FAIL_CLOSED_POLICY = True

# MCP 계층 정의
MCP_LAYER = {
    "L0": "identity_verification",
    "L1": "shard_routing",
}

# agent별 HMAC secret 환경변수 매핑
_SECRET_ENV_MAP = {
    "domi":  "AIBA_MCP_SECRET_DOMI",
    "jeni":  "AIBA_MCP_SECRET_JENI",
    "caddy": "AIBA_MCP_SECRET_CADDY",
}


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _get_agent_secret(agent_id: str) -> Optional[bytes]:
    """agent별 HMAC secret 조회. 미등록 시 None 반환."""
    env_key = _SECRET_ENV_MAP.get(agent_id)
    if env_key is None:
        return None
    secret = os.environ.get(env_key)
    if not secret:
        return None
    return secret.encode()


def _verify_hmac_signature(
    agent_id: str,
    timestamp: str,
    nonce: str,
    signature: str,
) -> bool:
    """
    HMAC-SHA256 서명 검증.
    메시지: agent_id + ":" + timestamp + ":" + nonce
    """
    secret = _get_agent_secret(agent_id)
    if secret is None:
        return False
    message = f"{agent_id}:{timestamp}:{nonce}".encode()
    expected = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_timestamp(timestamp_str: str) -> bool:
    """timestamp 유효성 검증. ±60초 허용."""
    try:
        request_time = float(timestamp_str)
    except (ValueError, TypeError):
        return False
    now = time.time()
    return abs(now - request_time) <= TIMESTAMP_TOLERANCE_SECONDS


# ── 응답 생성 ─────────────────────────────────────────────────────────────────

def _deny_response(reason: str) -> dict:
    """표준 DENY 응답 (HTTP 403 계약)."""
    return {
        "ok": False,
        "error_code": "DENIED",
        "reason": reason,
        "load_state": "DENIED",
    }


def _allow_response(shard: str, data: dict, load_state: str, retrieval_class: str) -> dict:
    """표준 ALLOW 응답."""
    return {
        "ok": True,
        "shard": shard,
        "data": data,
        "load_state": load_state,
        "retrieval_class": retrieval_class,
        "source_hash": "PLACEHOLDER",  # 실제 구현 시 SESSION_CONTEXT hash 주입
        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()),
        "canonical_epoch": None,
    }


# ── L0: Identity Verification ─────────────────────────────────────────────────

def verify_identity(request: dict, log_path: Optional[str] = None) -> tuple[bool, str, Optional[str]]:
    """
    L0 — HMAC 4요소 검증.
    반환: (ok, reason, nonce)
    """
    agent_id  = request.get("agent_id", "")
    timestamp = request.get("timestamp", "")
    nonce     = request.get("nonce", "")
    signature = request.get("signature", "")

    # agent_id allowlist 검사
    if agent_id not in ALLOWED_AGENTS:
        write_deny_audit(
            agent_id=agent_id or "UNKNOWN",
            requested_shard=request.get("shard", "UNKNOWN"),
            reason="AGENT_NOT_IN_ALLOWLIST",
            nonce=nonce or None,
            log_path=log_path,
        )
        return False, "AGENT_NOT_IN_ALLOWLIST", None

    # timestamp 검증
    if not _verify_timestamp(timestamp):
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=request.get("shard", "UNKNOWN"),
            reason="TIMESTAMP_EXPIRED",
            nonce=nonce or None,
            log_path=log_path,
        )
        return False, "TIMESTAMP_EXPIRED", None

    # nonce 재사용 검사
    if is_nonce_used(nonce):
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=request.get("shard", "UNKNOWN"),
            reason="NONCE_REUSED",
            nonce=nonce,
            log_path=log_path,
        )
        return False, "NONCE_REUSED", None

    # HMAC 서명 검증
    if not _verify_hmac_signature(agent_id, timestamp, nonce, signature):
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=request.get("shard", "UNKNOWN"),
            reason="INVALID_SIGNATURE",
            nonce=nonce,
            log_path=log_path,
        )
        return False, "INVALID_SIGNATURE", None

    # nonce 소비 (single-use 등록)
    if not consume_nonce(nonce):
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=request.get("shard", "UNKNOWN"),
            reason="NONCE_CONSUME_FAILED",
            nonce=nonce,
            log_path=log_path,
        )
        return False, "NONCE_CONSUME_FAILED", None

    return True, "IDENTITY_VERIFIED", nonce


# ── L1: Shard Routing ─────────────────────────────────────────────────────────

def handle_retrieval(request: dict, log_path: Optional[str] = None) -> dict:
    """
    PHASE-C 메인 처리 엔트리포인트.

    흐름:
    1. L0 identity verification
    2. forbidden operation 감지
    3. L1 shard routing
    4. audit 기록
    5. 응답 반환
    """
    agent_id      = request.get("agent_id", "UNKNOWN")
    requested_shard = request.get("shard", "UNKNOWN")

    # forbidden operation 선제 차단 (Lock-3 / Lock-8)
    if requested_shard in FORBIDDEN_OPERATIONS:
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=requested_shard,
            reason="FORBIDDEN_OPERATION",
            log_path=log_path,
        )
        return _deny_response("FORBIDDEN_OPERATION")

    # L0 — identity verification
    ok, reason, nonce = verify_identity(request, log_path=log_path)
    if not ok:
        return _deny_response(reason)

    # L1 — shard routing
    route = route_shard(agent_id, requested_shard)

    if not route.allowed:
        write_deny_audit(
            agent_id=agent_id,
            requested_shard=requested_shard,
            reason=route.reason,
            nonce=nonce,
            log_path=log_path,
        )
        return _deny_response(route.reason)

    # ALLOW — audit 기록 후 응답
    write_audit(
        agent_id=agent_id,
        requested_shard=requested_shard,
        returned_scope=requested_shard,
        decision="ALLOW",
        reason="ALLOWED",
        source_hash="PLACEHOLDER",
        load_state=route.load_state,
        retrieval_class=route.retrieval_class,
        nonce=nonce,
        log_path=log_path,
    )

    # read-only 데이터 반환 (실제 구현 시 SESSION_CONTEXT shard 주입)
    return _allow_response(
        shard=requested_shard,
        data={"shard": requested_shard, "content": "SHARD_DATA_PLACEHOLDER"},
        load_state=route.load_state,
        retrieval_class=route.retrieval_class,
    )

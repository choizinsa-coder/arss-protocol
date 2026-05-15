"""
AIBA MCP Server POC PHASE-C  v0.4.1
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C + Recovery Governance Layer
EAG:   EAG-2 비오(Joshua) 승인 (S128) / EAG-3 비오(Joshua) 승인 (S130)
설계:  도미 PHASE-C FINAL ANCHOR (S128) + Recovery Protocol FINAL ANCHOR (S130)

변경 이력:
- v0.4.0 (S128): PHASE-C 최초 구현
- v0.4.1 (S130): HC-T-01 (HMAC 연속 실패 >= 3) + HC-T-06 (cross-module inconsistency) 탐지 추가

계약:
- deny-by-default
- allowlist: domi / jeni / caddy
- HMAC 4요소: agent_id + timestamp + nonce + signature
- localhost 127.0.0.1 bind only
- Lock-3 / Lock-5 / Lock-7 / Lock-8 유지
- HC-T-01: HMAC 연속 실패 >= 3 -> HARD_CONTAINMENT
- HC-T-06: cross-module state inconsistency -> HARD_CONTAINMENT
"""

import collections
import hashlib
import hmac
import os
import sys
import threading
import time
from typing import Optional

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_containment_state import enter_containment, is_active
from mcp_nonce_store import consume_nonce, is_nonce_used
from mcp_shard_router import ALLOWED_AGENTS, FORBIDDEN_OPERATIONS, route_shard

# ── 상수 ──────────────────────────────────────────────────────────────────────

VERSION = "0.4.1"
TIMESTAMP_TOLERANCE_SECONDS = 60
CREDENTIAL_TTL_SECONDS = 900
BIND_ADDRESS = "127.0.0.1"
FAIL_CLOSED_POLICY = True
MCP_LAYER = {"L0": "identity_verification", "L1": "shard_routing"}

# HC-T-01: 연속 HMAC 실패 threshold
HMAC_FAILURE_THRESHOLD = 3

_SECRET_ENV_MAP = {
    "domi":  "AIBA_MCP_SECRET_DOMI",
    "jeni":  "AIBA_MCP_SECRET_JENI",
    "caddy": "AIBA_MCP_SECRET_CADDY",
}

# HC-T-01: agent별 연속 실패 카운터 (thread-safe)
_hmac_failure_counts: dict[str, int] = collections.defaultdict(int)
_hmac_failure_lock = threading.Lock()


# ── HC-T-01 헬퍼 ──────────────────────────────────────────────────────────────

def _record_hmac_failure(agent_id: str) -> None:
    """HMAC 실패 기록. threshold 초과 시 HARD_CONTAINMENT 진입."""
    with _hmac_failure_lock:
        _hmac_failure_counts[agent_id] += 1
        count = _hmac_failure_counts[agent_id]
    if count >= HMAC_FAILURE_THRESHOLD:
        enter_containment("HC-T-01")


def _reset_hmac_failure(agent_id: str) -> None:
    """HMAC 검증 성공 시 카운터 리셋 (single success reset)."""
    with _hmac_failure_lock:
        _hmac_failure_counts[agent_id] = 0


def get_hmac_failure_count(agent_id: str) -> int:
    """테스트용 카운터 조회."""
    with _hmac_failure_lock:
        return _hmac_failure_counts[agent_id]


def reset_all_hmac_counters() -> None:
    """테스트 전용 전체 초기화."""
    with _hmac_failure_lock:
        _hmac_failure_counts.clear()


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


# ── HC-T-06: cross-module state inconsistency 탐지 ────────────────────────────

def _check_cross_module_consistency(
    nonce: str,
    agent_id: str,
    shard: str,
    log_path: Optional[str] = None,
) -> bool:
    """
    HC-T-06: nonce/shard/audit 상태 간 invariant mismatch 탐지.
    불일치 탐지 시 HARD_CONTAINMENT 진입.
    Returns True if consistent, False if inconsistency detected.
    """
    try:
        # nonce 소비 직후에도 is_nonce_used=True여야 함
        if nonce and not is_nonce_used(nonce):
            # nonce가 소비되지 않았는데 후속 처리 중 — inconsistency
            enter_containment("HC-T-06")
            return False
    except Exception:
        enter_containment("HC-T-06")
        return False
    return True


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


# ── CONTAINMENT 차단 ──────────────────────────────────────────────────────────

def _containment_deny_response() -> dict:
    return _deny_response("HARD_CONTAINMENT_ACTIVE")


# ── L0: Identity Verification ─────────────────────────────────────────────────

def verify_identity(request: dict, log_path: Optional[str] = None):
    # containment 활성 시 전체 차단 (HC-A-03 제외 경로는 별도 처리)
    if is_active():
        return False, "HARD_CONTAINMENT_ACTIVE", None

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
        # HC-T-01: HMAC 실패 기록
        _record_hmac_failure(agent_id)
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="INVALID_SIGNATURE", nonce=nonce, log_path=log_path)
        return False, "INVALID_SIGNATURE", None

    # HMAC 성공 -> 카운터 리셋 (single success reset)
    _reset_hmac_failure(agent_id)

    if not consume_nonce(nonce):
        write_deny_audit(agent_id=agent_id, requested_shard=shard,
                         reason="NONCE_CONSUME_FAILED", nonce=nonce, log_path=log_path)
        return False, "NONCE_CONSUME_FAILED", None

    return True, "IDENTITY_VERIFIED", nonce


# ── L1: Shard Routing ─────────────────────────────────────────────────────────

def handle_retrieval(request: dict, log_path: Optional[str] = None) -> dict:
    # containment 활성 시 전체 차단
    if is_active():
        return _containment_deny_response()

    agent_id        = request.get("agent_id", "UNKNOWN")
    requested_shard = request.get("shard", "UNKNOWN")

    if requested_shard in FORBIDDEN_OPERATIONS:
        write_deny_audit(agent_id=agent_id, requested_shard=requested_shard,
                         reason="FORBIDDEN_OPERATION", log_path=log_path)
        return _deny_response("FORBIDDEN_OPERATION")

    ok, reason, nonce = verify_identity(request, log_path=log_path)
    if not ok:
        return _deny_response(reason)

    # HC-T-06: cross-module consistency 검증
    if not _check_cross_module_consistency(nonce, agent_id, requested_shard, log_path):
        return _deny_response("CROSS_MODULE_INCONSISTENCY")

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

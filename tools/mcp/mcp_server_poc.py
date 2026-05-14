"""
AIBA MCP Server POC  v0.3.0
Task:  PT-S125-BOOT-ONDEMAND-001
EAG:   EAG-2 비오(Joshua) 승인 (S127)
설계:  도미 PHASE-B FINAL ANCHOR + SUPPLEMENTAL ANCHOR

=============================================================================
PHASE 정의
=============================================================================
PHASE-A (완료, commit f4d35ca):
    Local stdio observability-only MCP. L0/L1 계층. deny-by-default.
    FAIL_CLOSED structural invariant.

PHASE-B (현재, v0.3.0):
    Boundary hardening.
    B-1 Throttling / B-2 Audit Isolation / B-3 Timeout / B-4 Freshness+Routing.

PHASE-C (미착수):
    HTTP/auth evaluation. 별도 EAG 필요.

PHASE-D (미착수):
    Selective exposure review. EAG 필수.

=============================================================================
MCP 계층 정의 (structural invariant — PHASE-A와 동일, 변경 불가)
=============================================================================
L0 = Ping / Health only          <- PHASE-A/B 허용
L1 = Metadata visibility         <- PHASE-A/B 허용
L2 = Read-only operational data  <- PHASE-B 이후
L3 = Restricted governance data  <- PHASE-D 이후 + CVC-01~04 필수
L4 = Mutation / Execution        <- FORBIDDEN

=============================================================================
B-1 Throttling 계약 (수치 LOCK)
=============================================================================
CALL 단위:    3 calls / 10 seconds  (burst 억제)
SESSION 단위: 30 calls / session    (retrieval dependency 누적 억제)
cooldown:     120 seconds + next-call prevalidation PASS 동시 충족
QUEUE:        불허 — FAIL_CLOSED 우선
escalation:   반복 위반 시 HOLD escalation

=============================================================================
B-3 Timeout 계약 (수치 LOCK)
=============================================================================
T-1 transport timeout:       2 seconds
T-2 tool execution timeout:  5 seconds
T-3 audit persistence:       1 second  (mcp_audit_broker.py 담당)
partial response:            정상 응답으로 취급하지 않음
AUDIT_UNVERIFIED_RESULT:     반환값 폐기 + HOLD

=============================================================================
B-4-A Freshness Mismatch Contract
=============================================================================
canonical_epoch 불일치:  기본 DENY
                         예외: canonical 판단 무관 참고 정보 한정 시
                               READ_ONLY_COGNITION_MODE 강등 허용
source_hash 불일치:      무조건 DENY (강등 불허)
stale-but-readable:      불허

=============================================================================
B-4-B Retrieval Routing Integrity Contract (Lock-2 집행)
=============================================================================
SEMANTIC_DOMAIN_MISMATCH:  requested shard domain != returned shard domain
detection:                 shard identifier + domain tag 이중 일치 (L1 계층)
처리:                      FAIL_CLOSED (READ_ONLY_COGNITION_MODE 강등 불허)
Lock-2 관계:               Lock-2=구조 정의 / B-4-B=집행 계약
"""

import json
import os
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Audit Broker import (B-2-B authority separation)
# ---------------------------------------------------------------------------

_BROKER_DIR = os.path.dirname(os.path.abspath(__file__))
if _BROKER_DIR not in sys.path:
    sys.path.insert(0, _BROKER_DIR)

from mcp_audit_broker import AuditBroker, AuditPersistenceError  # noqa: E402

# ---------------------------------------------------------------------------
# 서버 상수
# ---------------------------------------------------------------------------

SERVER_NAME = "aiba-mcp-poc"
SERVER_VERSION = "0.3.0"
AIBA_SYSTEM = "AIBA Self-Evolution-Ready System"
AIBA_VERSION = "v1.5"
VPS_HOST = "159.203.125.1"
CANONICAL_PATH = "/opt/arss/engine/arss-protocol"
CURRENT_PHASE = "PHASE-B"

# ---------------------------------------------------------------------------
# MCP 계층 상수 (structural invariant — PHASE-A 동일)
# ---------------------------------------------------------------------------

PHASE_A_ALLOWED_LAYERS = frozenset({"L0", "L1"})

FORBIDDEN_TOOLS: frozenset = frozenset({
    "get_all_context", "load_full_session", "preload_all",
    "get_full_boot", "get_session_context",
    "write_context", "modify_context", "update_session", "patch_state",
    "trigger_workflow", "run_pipeline", "execute_command", "invoke_agent",
    "issue_rpu", "write_chain", "modify_chain", "commit_delta",
    "push_canonical", "set_ssot", "override_session",
})

# ---------------------------------------------------------------------------
# B-1 Throttling 상수 (수치 LOCK)
# ---------------------------------------------------------------------------

THROTTLE_CALL_LIMIT = 3          # calls per window
THROTTLE_CALL_WINDOW_S = 10.0    # window size (seconds)
THROTTLE_SESSION_LIMIT = 30      # calls per session
THROTTLE_COOLDOWN_S = 120.0      # cooldown duration (seconds)

# B-1-B TA-1 반영: prevalidation 별도 timeout
THROTTLE_PREVALIDATION_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# B-3 Timeout 상수 (수치 LOCK)
# ---------------------------------------------------------------------------

T1_TRANSPORT_TIMEOUT_S = 2.0     # transport timeout (미사용 — stdio 단방향)
T2_TOOL_EXECUTION_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# 상태값 상수
# ---------------------------------------------------------------------------

STATE_RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
STATE_AUDIT_UNVERIFIED = "AUDIT_UNVERIFIED_RESULT"
STATE_SEMANTIC_DOMAIN_MISMATCH = "SEMANTIC_DOMAIN_MISMATCH"
STATE_READ_ONLY_COGNITION_MODE = "READ_ONLY_COGNITION_MODE"

# ---------------------------------------------------------------------------
# Shard Domain Registry (B-4-B Lock-2 집행 기반)
# ---------------------------------------------------------------------------

SHARD_DOMAIN_REGISTRY: dict = {
    "task":       "operational.task",
    "chain":      "operational.chain",
    "boot":       "kernel.boot",
    "archive":    "storage.archive",
    "governance": "governance.policy",
    "metrics":    "observability.metrics",
}


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------

class ThrottleError(Exception):
    """B-1: RATE_LIMIT_EXCEEDED 상태."""

class ToolExecutionTimeoutError(Exception):
    """B-3 T-2: tool execution timeout."""

class FreshnessError(Exception):
    """B-4-A: freshness mismatch."""

class RoutingIntegrityError(Exception):
    """B-4-B: SEMANTIC_DOMAIN_MISMATCH."""


# ---------------------------------------------------------------------------
# B-1 Throttle Guard
# ---------------------------------------------------------------------------

class ThrottleGuard:
    """
    B-1-A Rate Limit + B-1-B Recovery Contract.
    - CALL 단위: 3 / 10s (burst)
    - SESSION 단위: 30 / session
    - cooldown: 120s + prevalidation PASS
    - QUEUE 불허 — 초과 즉시 ThrottleError
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._call_window: list[float] = []   # 최근 호출 timestamps
        self._session_count: int = 0
        self._cooldown_until: float = 0.0
        self._violation_count: int = 0

    def check(self) -> None:
        """호출 전 throttle 상태 검사. 위반 시 ThrottleError."""
        with self._lock:
            now = time.monotonic()

            # cooldown 상태 확인
            if now < self._cooldown_until:
                remaining = self._cooldown_until - now
                raise ThrottleError(
                    f"[{STATE_RATE_LIMIT_EXCEEDED}] cooldown 중 "
                    f"({remaining:.1f}s 남음) — recovery: cooldown 만료 + prevalidation PASS 필요"
                )

            # SESSION 단위 상한 확인
            if self._session_count >= THROTTLE_SESSION_LIMIT:
                self._enter_cooldown(now)
                raise ThrottleError(
                    f"[{STATE_RATE_LIMIT_EXCEEDED}] SESSION 상한 초과 "
                    f"({THROTTLE_SESSION_LIMIT} calls/session)"
                )

            # CALL 단위 window 정리 및 확인
            self._call_window = [t for t in self._call_window if now - t < THROTTLE_CALL_WINDOW_S]
            if len(self._call_window) >= THROTTLE_CALL_LIMIT:
                self._enter_cooldown(now)
                raise ThrottleError(
                    f"[{STATE_RATE_LIMIT_EXCEEDED}] CALL 상한 초과 "
                    f"({THROTTLE_CALL_LIMIT} calls/{THROTTLE_CALL_WINDOW_S}s)"
                )

            # 허용 — 카운터 증가
            self._call_window.append(now)
            self._session_count += 1

    def prevalidation_pass(self) -> bool:
        """
        B-1-B Recovery Contract: cooldown 만료 후 next-call prevalidation.
        시스템 상태 정상 여부 확인. (PHASE-B: 항상 PASS — 추후 확장 지점)
        TA-1 반영: 이 함수 자체가 hang하지 않도록 timeout_s 내 완료 보장.
        """
        # 현재 구현: 즉시 반환 (hang 없음 — TA-1 충족)
        return True

    def try_recover(self) -> bool:
        """cooldown 만료 + prevalidation PASS 시 복구. 성공 시 True."""
        with self._lock:
            now = time.monotonic()
            if now < self._cooldown_until:
                return False
            # prevalidation (별도 timeout 보장 — TA-1)
            try:
                result = self._run_with_timeout(
                    self.prevalidation_pass,
                    THROTTLE_PREVALIDATION_TIMEOUT_S,
                )
            except TimeoutError:
                return False
            if result:
                self._violation_count = 0
                return True
            return False

    def _enter_cooldown(self, now: float) -> None:
        self._cooldown_until = now + THROTTLE_COOLDOWN_S
        self._violation_count += 1

    @staticmethod
    def _run_with_timeout(fn, timeout_s: float):
        result_holder: list = []
        exc_holder: list = []

        def _target():
            try:
                result_holder.append(fn())
            except Exception as e:
                exc_holder.append(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout_s)
        if t.is_alive():
            raise TimeoutError(f"prevalidation timeout ({timeout_s}s)")
        if exc_holder:
            raise exc_holder[0]
        return result_holder[0] if result_holder else None


# ---------------------------------------------------------------------------
# B-4 Freshness + Routing Integrity Checker
# ---------------------------------------------------------------------------

class IntegrityChecker:
    """B-4-A Freshness Mismatch + B-4-B Retrieval Routing Integrity."""

    @staticmethod
    def check_freshness(
        canonical_epoch: Optional[int],
        source_hash: Optional[str],
        current_epoch: int,
        current_hash: str,
        read_only_eligible: bool = False,
    ) -> str:
        """
        B-4-A Freshness Mismatch Contract.

        반환값:
          "ALLOW"                    — 완전 일치
          READ_ONLY_COGNITION_MODE   — canonical_epoch 불일치 + 참고 정보 한정
        발생 예외:
          FreshnessError             — DENY 조건
        """
        # source_hash 불일치: 무조건 DENY
        if source_hash is not None and source_hash != current_hash:
            raise FreshnessError(
                f"[FRESHNESS_DENY] source_hash 불일치 — "
                f"expected={current_hash} got={source_hash}"
            )

        # canonical_epoch 불일치
        if canonical_epoch is not None and canonical_epoch != current_epoch:
            if read_only_eligible:
                return STATE_READ_ONLY_COGNITION_MODE
            raise FreshnessError(
                f"[FRESHNESS_DENY] canonical_epoch 불일치 — "
                f"expected={current_epoch} got={canonical_epoch}"
            )

        return "ALLOW"

    @staticmethod
    def check_routing_integrity(
        requested_shard: str,
        returned_shard: str,
    ) -> None:
        """
        B-4-B Retrieval Routing Integrity Contract (Lock-2 집행).
        shard identifier + domain tag 이중 일치 검증.
        불일치 시 FAIL_CLOSED — RoutingIntegrityError 발생.
        """
        # shard identifier 일치 확인
        if requested_shard != returned_shard:
            req_domain = SHARD_DOMAIN_REGISTRY.get(requested_shard, "unknown")
            ret_domain = SHARD_DOMAIN_REGISTRY.get(returned_shard, "unknown")
            raise RoutingIntegrityError(
                f"[{STATE_SEMANTIC_DOMAIN_MISMATCH}] "
                f"requested={requested_shard}(domain={req_domain}) "
                f"returned={returned_shard}(domain={ret_domain}) — FAIL_CLOSED"
            )

        # domain tag 일치 확인 (같은 shard identifier라도 registry 등재 여부 검증)
        if requested_shard not in SHARD_DOMAIN_REGISTRY:
            raise RoutingIntegrityError(
                f"[{STATE_SEMANTIC_DOMAIN_MISMATCH}] "
                f"shard '{requested_shard}' not in domain registry — FAIL_CLOSED"
            )


# ---------------------------------------------------------------------------
# Broker 싱글턴
# ---------------------------------------------------------------------------

_audit_broker: Optional[AuditBroker] = None
_broker_lock = threading.Lock()


def _get_broker() -> AuditBroker:
    global _audit_broker
    with _broker_lock:
        if _audit_broker is None:
            _audit_broker = AuditBroker()
    return _audit_broker


# ---------------------------------------------------------------------------
# Throttle Guard 싱글턴
# ---------------------------------------------------------------------------

_throttle_guard: Optional[ThrottleGuard] = None
_throttle_lock = threading.Lock()


def _get_throttle() -> ThrottleGuard:
    global _throttle_guard
    with _throttle_lock:
        if _throttle_guard is None:
            _throttle_guard = ThrottleGuard()
    return _throttle_guard


# ---------------------------------------------------------------------------
# 도구 구현
# ---------------------------------------------------------------------------

def ping() -> dict:
    """[L0] 서버 생존 확인."""
    return {
        "status": "ok",
        "message": "AIBA MCP POC server is alive",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "phase": CURRENT_PHASE,
        "mcp_layer": "L0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_server_status() -> dict:
    """[L1] 서버 및 AIBA 시스템 메타데이터 반환."""
    return {
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "aiba_system": AIBA_SYSTEM,
        "aiba_version": AIBA_VERSION,
        "vps_host": VPS_HOST,
        "canonical_path": CANONICAL_PATH,
        "mcp_poc_task": "PT-S125-BOOT-ONDEMAND-001",
        "eag_stage": "EAG-2_COMPLETE",
        "current_phase": CURRENT_PHASE,
        "mcp_layer": "L1",
        "allowed_layers": sorted(PHASE_A_ALLOWED_LAYERS),
        "fail_closed_policy": "DENY",
        "phase_b_contracts": {
            "throttle_call_limit": f"{THROTTLE_CALL_LIMIT}/{THROTTLE_CALL_WINDOW_S}s",
            "throttle_session_limit": THROTTLE_SESSION_LIMIT,
            "cooldown_s": THROTTLE_COOLDOWN_S,
            "t1_transport_timeout_s": T1_TRANSPORT_TIMEOUT_S,
            "t2_execution_timeout_s": T2_TOOL_EXECUTION_TIMEOUT_S,
        },
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def get_current_epoch() -> dict:
    """[L1] 현재 epoch 및 UTC 타임스탬프 반환."""
    now = datetime.now(timezone.utc)
    return {
        "epoch_ms": int(now.timestamp() * 1000),
        "epoch_s": int(now.timestamp()),
        "utc_iso": now.isoformat(),
        "source": "vps_system_clock",
        "mcp_layer": "L1",
        "note": "Used for CLASS-B Integrity Contract canonical_epoch field",
    }


# ---------------------------------------------------------------------------
# 허용 레지스트리 빌더 (PHASE-A 동일 구조 유지)
# ---------------------------------------------------------------------------

def _build_allowed_tools() -> dict:
    registry = {
        "ping": {
            "name": "ping", "layer": "L0",
            "description": "[L0] AIBA MCP POC 서버 생존 확인.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": ping,
        },
        "get_server_status": {
            "name": "get_server_status", "layer": "L1",
            "description": "[L1] AIBA 시스템 메타데이터 반환.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": get_server_status,
        },
        "get_current_epoch": {
            "name": "get_current_epoch", "layer": "L1",
            "description": "[L1] 현재 epoch 및 UTC 타임스탬프 반환.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": get_current_epoch,
        },
    }
    for name, entry in registry.items():
        if name in FORBIDDEN_TOOLS:
            raise RuntimeError(
                f"[FAIL_CLOSED] FORBIDDEN 도구 '{name}' 허용 레지스트리 등재 — 즉시 중단."
            )
        if entry["layer"] not in PHASE_A_ALLOWED_LAYERS:
            raise RuntimeError(
                f"[FAIL_CLOSED] 도구 '{name}' 계층 '{entry['layer']}' PHASE-A 허용 범위 외부."
            )
    return registry


ALLOWED_TOOLS: dict = _build_allowed_tools()


# ---------------------------------------------------------------------------
# B-2-B + B-3 T-2 통합 디스패처
# ---------------------------------------------------------------------------

def _dispatch(tool_name: str) -> dict:
    """
    순서:
      1. FORBIDDEN_TOOLS 검사 → DENY
      2. ALLOWED_TOOLS 미등재 검사 → DENY
      3. 계층 검사 → DENY
      4. B-1 throttle 검사
      5. B-3 T-2 timeout 내 실행
      6. B-2-B audit broker에 위임 (execution write authority 분리)
    """
    broker = _get_broker()
    throttle = _get_throttle()

    # FORBIDDEN 검사
    if tool_name in FORBIDDEN_TOOLS:
        try:
            broker.submit_deny(tool_name, "FORBIDDEN_TOOLS", CURRENT_PHASE)
        except AuditPersistenceError:
            pass
        raise PermissionError(f"[FAIL_CLOSED] FORBIDDEN 도구: {tool_name}")

    # 미등재 검사
    if tool_name not in ALLOWED_TOOLS:
        try:
            broker.submit_deny(tool_name, "NOT_IN_REGISTRY", CURRENT_PHASE)
        except AuditPersistenceError:
            pass
        raise PermissionError(f"[FAIL_CLOSED] 미등재 도구: {tool_name}")

    entry = ALLOWED_TOOLS[tool_name]

    # 계층 검사
    if entry["layer"] not in PHASE_A_ALLOWED_LAYERS:
        try:
            broker.submit_deny(tool_name, f"LAYER_VIOLATION:{entry['layer']}", CURRENT_PHASE)
        except AuditPersistenceError:
            pass
        raise PermissionError(f"[FAIL_CLOSED] 계층 위반: {tool_name}")

    # B-1 throttle 검사
    try:
        throttle.check()
    except ThrottleError as exc:
        try:
            broker.submit_deny(tool_name, STATE_RATE_LIMIT_EXCEEDED, CURRENT_PHASE)
        except AuditPersistenceError:
            pass
        raise

    # B-3 T-2: 도구 실행 timeout (5s)
    result_holder: list = []
    exc_holder: list = []

    def _run():
        try:
            result_holder.append(entry["fn"]())
        except Exception as e:
            exc_holder.append(e)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=T2_TOOL_EXECUTION_TIMEOUT_S)

    if t.is_alive():
        # T-2 timeout — FAIL_CLOSED
        try:
            broker.submit_deny(tool_name, "T2_TOOL_EXECUTION_TIMEOUT", CURRENT_PHASE)
        except AuditPersistenceError:
            pass
        raise ToolExecutionTimeoutError(
            f"[FAIL_CLOSED] T-2 tool execution timeout ({T2_TOOL_EXECUTION_TIMEOUT_S}s): {tool_name}"
        )

    if exc_holder:
        raise exc_holder[0]

    result = result_holder[0]

    # B-2-B: audit write를 broker에 위임 (execution layer는 write 불가)
    try:
        broker.submit_event(
            tool_name=tool_name,
            layer=entry["layer"],
            result_summary="ok",
            phase=CURRENT_PHASE,
        )
    except AuditPersistenceError as exc:
        # B-3: AUDIT_UNVERIFIED_RESULT — 반환값 폐기
        raise RuntimeError(
            f"[{STATE_AUDIT_UNVERIFIED}] audit 기록 실패 — 반환값 폐기: {exc}"
        )

    return result


# ---------------------------------------------------------------------------
# MCP 프로토콜 핸들러 (stdio JSON-RPC — PHASE-A 동일)
# ---------------------------------------------------------------------------

def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(request: dict) -> None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        _send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        })

    elif method == "tools/list":
        tool_list = [
            {"name": e["name"], "description": e["description"], "inputSchema": e["inputSchema"]}
            for e in ALLOWED_TOOLS.values()
        ]
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_list}})

    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        try:
            result = _dispatch(tool_name)
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            })
        except (PermissionError, ThrottleError, ToolExecutionTimeoutError, RuntimeError) as exc:
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": str(exc)},
            })
        except Exception as exc:
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
            })

    elif method == "notifications/initialized":
        pass

    else:
        if req_id is not None:
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def main() -> None:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [MCP] %(message)s",
                        handlers=[logging.StreamHandler(sys.stderr)])
    log = logging.getLogger("aiba_mcp_poc")
    log.info(
        "AIBA MCP POC Server v%s starting — phase=%s task=PT-S125-BOOT-ONDEMAND-001 "
        "policy=FAIL_CLOSED throttle=%d/%ds session_limit=%d",
        SERVER_VERSION, CURRENT_PHASE,
        THROTTLE_CALL_LIMIT, int(THROTTLE_CALL_WINDOW_S), THROTTLE_SESSION_LIMIT,
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            _handle(request)
        except json.JSONDecodeError as exc:
            log.error("JSON_DECODE_ERROR: %s", exc)
            _send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})


if __name__ == "__main__":
    main()

"""
transport_client.py
AIBA Sync Layer — Transport Client (HTTP Push)
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

역할:
  - Payload 검증 → Endpoint 조회 → HTTP POST → TransportResult 반환
  - 실패 시: notification_emit → ABORTED 반환 (NO RETRY / NO RECOVERY)
  - Allowed Caller 강제 차단 (Jeni EAG-3 HG-1)

Allowed Callers (폐쇄 집합):
  tools.sync_layer.deploy_executor
  tools.sync_layer.sync_orchestrator

HTTP 구현:
  urllib.request (stdlib — 외부 의존성 없음, J-6 자동 해소)

금지:
  - 재시도 로직
  - 자동 복구
  - 위 두 모듈 외 호출자 허용
"""

import inspect
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

from tools.sync_layer.transport.transport_types import (
    TransportResult,
    RESULT_SUCCESS,
    RESULT_ABORTED,
)
from tools.sync_layer.transport.transport_contract import (
    validate_payload,
    compute_payload_hash,
    extract_event_id,
)
from tools.sync_layer.transport.transport_registry import get_active_endpoint
from tools.sync_layer.transport.transport_notification import emit_failure

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
HTTP_TIMEOUT_SECONDS = 10
HTTP_SUCCESS_STATUSES = {200, 201, 202}

ALLOWED_CALLER_MODULES = frozenset({
    "tools.sync_layer.deploy_executor",
    "tools.sync_layer.sync_orchestrator",
})


# ── Allowed Caller 강제 차단 (Jeni EAG-3 HG-1) ─────────────────────────────

def _enforce_allowed_caller() -> None:
    """
    Stack frame 검증 — Allowed Callers 외 호출 즉시 차단.
    Jeni Advisory: 데코레이터 / stack frame 방식 강제 구현.
    CC=3
    """
    stack = inspect.stack()
    for frame_info in stack[2:10]:
        module = frame_info.frame.f_globals.get("__name__", "")
        if module in ALLOWED_CALLER_MODULES:
            return
    raise RuntimeError(
        f"UNAUTHORIZED_CALLER: transport_client.send() is restricted to "
        f"{sorted(ALLOWED_CALLER_MODULES)}"
    )


# ── 메인 전송 진입점 ────────────────────────────────────────────────────────

def send(payload: dict) -> TransportResult:
    """
    Transport 진입점.
    흐름: Caller 검증 → Payload 검증 → Endpoint 조회 → HTTP POST
    실패 시: notification_emit → ABORTED (NO RETRY)

    Allowed Callers: deploy_executor, sync_orchestrator
    CC=4
    """
    _enforce_allowed_caller()

    payload_hash = compute_payload_hash(payload)
    event_id = extract_event_id(payload)
    event_type = payload.get("event_type", "UNKNOWN")
    session = int(payload.get("session", 0))
    timestamp = datetime.now(KST).isoformat()

    valid, error = validate_payload(payload)
    if not valid:
        return _abort(
            event_id=event_id,
            event_type=event_type,
            endpoint="",
            payload_hash=payload_hash,
            reason=f"PAYLOAD_INVALID: {error}",
            session=session,
            timestamp=timestamp,
        )

    endpoint = get_active_endpoint(event_type)
    if not endpoint:
        return _abort(
            event_id=event_id,
            event_type=event_type,
            endpoint="",
            payload_hash=payload_hash,
            reason="ENDPOINT_NOT_FOUND",
            session=session,
            timestamp=timestamp,
        )

    return _http_post(
        payload=payload,
        endpoint=endpoint,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        session=session,
        timestamp=timestamp,
    )


# ── HTTP POST 실행 ──────────────────────────────────────────────────────────

def _http_post(
    payload: dict,
    endpoint: str,
    event_id: str,
    event_type: str,
    payload_hash: str,
    session: int,
    timestamp: str,
) -> TransportResult:
    """
    HTTP POST 실행.
    HTTPError → _abort / URLError|Timeout → _abort / 비정상 상태코드 → _abort
    CC=5
    """
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        return _abort(
            event_id=event_id, event_type=event_type, endpoint=endpoint,
            payload_hash=payload_hash, reason=f"HTTP_ERROR: {exc.code}",
            session=session, timestamp=timestamp,
        )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return _abort(
            event_id=event_id, event_type=event_type, endpoint=endpoint,
            payload_hash=payload_hash, reason=f"TRANSPORT_ERROR: {type(exc).__name__}",
            session=session, timestamp=timestamp,
        )

    if status not in HTTP_SUCCESS_STATUSES:
        return _abort(
            event_id=event_id, event_type=event_type, endpoint=endpoint,
            payload_hash=payload_hash, reason=f"UNEXPECTED_STATUS: {status}",
            session=session, timestamp=timestamp,
        )

    logger.info(
        "TRANSPORT_SUCCESS: event_id=%s event_type=%s status=%s",
        event_id, event_type, status,
    )
    return TransportResult(
        status=RESULT_SUCCESS,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        endpoint=endpoint,
        timestamp=timestamp,
        failure_reason=None,
        session=session,
    )


# ── 실패 공통 처리 ──────────────────────────────────────────────────────────

def _abort(
    event_id: str,
    event_type: str,
    endpoint: str,
    payload_hash: str,
    reason: str,
    session: int,
    timestamp: str,
) -> TransportResult:
    """
    실패 처리: notification_emit → ABORTED TransportResult 반환.
    STOP 원칙 — 재시도 없음.
    CC=1
    """
    emit_failure(
        event_id=event_id,
        event_type=event_type,
        endpoint=endpoint,
        failure_reason=reason,
        payload_hash=payload_hash,
        session=session,
    )
    return TransportResult(
        status=RESULT_ABORTED,
        event_id=event_id,
        event_type=event_type,
        payload_hash=payload_hash,
        endpoint=endpoint,
        timestamp=timestamp,
        failure_reason=reason,
        session=session,
    )


# ── 상태 조회 ───────────────────────────────────────────────────────────────

def get_client_status() -> dict:
    """Transport Client 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "transport_client",
        "layer": "sync_layer/transport",
        "p3_task": "P3-T3",
        "http_timeout_seconds": HTTP_TIMEOUT_SECONDS,
        "allowed_callers": sorted(ALLOWED_CALLER_MODULES),
        "http_library": "urllib.request (stdlib)",
        "jeni_advisory": "NO_RETRY / NO_RECOVERY / NO_SELF_HEAL",
        "result_enum": [RESULT_SUCCESS, RESULT_ABORTED],
    }

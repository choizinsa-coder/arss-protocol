"""
fallback_handler.py
AIBA Sync Layer — Fallback Handler
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

역할:
  - FallbackRecord 수신 → fallback_endpoints.json 조회 → 동작 결정
  - secondary_enabled=false: ESCALATED_ONLY → receipt 생성 → STOP
  - secondary_enabled=true: 1회 secondary HTTP 시도 → 성공/실패 → receipt 생성 → STOP
  - fallback_receipt 저장

Allowed Caller:
  tools.sync_layer.fallback.fallback_scanner 전용

Fail-Closed 정책 (도미 D-2 확정):
  max_attempt = 1 (secondary)
  ttl = same session only
  FALLBACK_EXHAUSTED → FATAL → Manual Path Required → STOP

금지:
  - 재시도 루프 (max_attempt 초과 시도)
  - 자동 복구 / self-heal
  - 위 Allowed Caller 외 호출 허용
"""

import inspect
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tools.sync_layer.fallback.fallback_types import (
    ALLOWED_CALLER_MODULES,
    ACTION_SECONDARY_ATTEMPT,
    ACTION_ESCALATED_ONLY,
    ACTION_INVALID,
    RESULT_SUCCESS,
    RESULT_FAILED,
    RESULT_ESCALATED,
    RESULT_FATAL,
    FallbackRecord,
    FallbackResult,
)
from tools.sync_layer.fallback.fallback_receipt import build_receipt, save_receipt

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
FALLBACK_ENDPOINTS_PATH = VPS_ROOT / "registry" / "fallback_endpoints.json"
KST = timezone(timedelta(hours=9))
HTTP_TIMEOUT_SECONDS = 10
HTTP_SUCCESS_STATUSES = frozenset({200, 201, 202})


# ── Allowed Caller 강제 차단 (Jeni TRUST_READY 설계 요건) ───────────────────

def _enforce_allowed_caller() -> None:
    """
    Stack frame 검증 — fallback_scanner 외 호출 즉시 차단.
    CC=3
    """
    stack = inspect.stack()
    for frame_info in stack[2:10]:
        module = frame_info.frame.f_globals.get("__name__", "")
        if module in ALLOWED_CALLER_MODULES:
            return
    raise RuntimeError(
        f"UNAUTHORIZED_CALLER: fallback_handler.handle() is restricted to "
        f"{sorted(ALLOWED_CALLER_MODULES)}"
    )


# ── 공개 API ─────────────────────────────────────────────────────────────────

def handle(record: FallbackRecord) -> dict:
    """
    Fallback Handler 진입점.
    Caller 검증 → endpoint 조회 → 동작 결정 → receipt 저장.

    반환: {
        "action": str,
        "result": str,
        "receipt_saved": bool,
        "manual_path_required": bool,
        "fallback_id": str,
    }
    CC=4
    """
    _enforce_allowed_caller()

    endpoint_config = _load_endpoint_config(record.event_type)

    if endpoint_config is None:
        return _build_escalation_response(record, errors=["ENDPOINT_CONFIG_NOT_FOUND"])

    if not endpoint_config.get("secondary_enabled", False):
        return _escalate_only(record)

    # secondary_enabled=True: 1회 시도
    secondary_url = endpoint_config.get("secondary_endpoint")
    if not secondary_url:
        return _escalate_only(record, errors=["SECONDARY_URL_EMPTY"])

    return _attempt_secondary(record, secondary_url)


# ── 내부 처리 경로 ────────────────────────────────────────────────────────────

def _escalate_only(record: FallbackRecord, errors: list = None) -> dict:
    """
    secondary_enabled=False 또는 URL 누락 → ESCALATED_ONLY 경로.
    CC=2
    """
    receipt = build_receipt(
        event_id=record.event_id,
        event_type=record.event_type,
        original_endpoint=record.endpoint,
        fallback_endpoint=None,
        action=ACTION_ESCALATED_ONLY,
        result=RESULT_ESCALATED,
        payload_hash=record.payload_hash,
        session=record.session,
        source_failure_record=f"FAIL-{record.event_id}",
        errors=errors or [],
        manual_path_required=True,
    )
    saved = save_receipt(receipt)
    logger.warning(
        "FALLBACK_ESCALATED: event_id=%s — manual path required",
        record.event_id,
    )
    return {
        "action": ACTION_ESCALATED_ONLY,
        "result": RESULT_ESCALATED,
        "receipt_saved": saved,
        "manual_path_required": True,
        "fallback_id": receipt.fallback_id,
    }


def _attempt_secondary(record: FallbackRecord, secondary_url: str) -> dict:
    """
    secondary endpoint 1회 시도.
    성공: RESULT_SUCCESS / 실패: RESULT_FATAL (FALLBACK_EXHAUSTED)
    CC=4
    """
    try:
        payload = _build_retry_payload(record)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url=secondary_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            status = resp.status

        if status in HTTP_SUCCESS_STATUSES:
            receipt = build_receipt(
                event_id=record.event_id,
                event_type=record.event_type,
                original_endpoint=record.endpoint,
                fallback_endpoint=secondary_url,
                action=ACTION_SECONDARY_ATTEMPT,
                result=RESULT_SUCCESS,
                payload_hash=record.payload_hash,
                session=record.session,
                source_failure_record=f"FAIL-{record.event_id}",
                manual_path_required=False,
            )
            saved = save_receipt(receipt)
            logger.info("FALLBACK_SUCCESS: event_id=%s secondary=%s", record.event_id, secondary_url)
            return {
                "action": ACTION_SECONDARY_ATTEMPT,
                "result": RESULT_SUCCESS,
                "receipt_saved": saved,
                "manual_path_required": False,
                "fallback_id": receipt.fallback_id,
            }

        # 비정상 상태 코드 → FATAL
        return _build_fatal_response(
            record, secondary_url, errors=[f"SECONDARY_UNEXPECTED_STATUS: {status}"]
        )

    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return _build_fatal_response(
            record, secondary_url, errors=[f"SECONDARY_HTTP_FAILED: {type(exc).__name__}"]
        )


def _build_fatal_response(
    record: FallbackRecord,
    secondary_url: Optional[str],
    errors: list = None,
) -> dict:
    """
    FALLBACK_EXHAUSTED → FATAL → Manual Path Required.
    CC=2
    """
    receipt = build_receipt(
        event_id=record.event_id,
        event_type=record.event_type,
        original_endpoint=record.endpoint,
        fallback_endpoint=secondary_url,
        action=ACTION_SECONDARY_ATTEMPT,
        result=RESULT_FATAL,
        payload_hash=record.payload_hash,
        session=record.session,
        source_failure_record=f"FAIL-{record.event_id}",
        errors=errors or [],
        manual_path_required=True,
    )
    saved = save_receipt(receipt)
    logger.error(
        "FALLBACK_EXHAUSTED: event_id=%s — FATAL — manual path required",
        record.event_id,
    )
    return {
        "action": ACTION_SECONDARY_ATTEMPT,
        "result": RESULT_FATAL,
        "receipt_saved": saved,
        "manual_path_required": True,
        "fallback_id": receipt.fallback_id,
    }


def _build_escalation_response(record: FallbackRecord, errors: list = None) -> dict:
    """endpoint_config 로드 실패 시 escalation. CC=2"""
    receipt = build_receipt(
        event_id=record.event_id,
        event_type=record.event_type,
        original_endpoint=record.endpoint,
        fallback_endpoint=None,
        action=ACTION_ESCALATED_ONLY,
        result=RESULT_ESCALATED,
        payload_hash=record.payload_hash,
        session=record.session,
        source_failure_record=f"FAIL-{record.event_id}",
        errors=errors or [],
        manual_path_required=True,
    )
    saved = save_receipt(receipt)
    return {
        "action": ACTION_ESCALATED_ONLY,
        "result": RESULT_ESCALATED,
        "receipt_saved": saved,
        "manual_path_required": True,
        "fallback_id": receipt.fallback_id,
    }


# ── Endpoint 조회 ────────────────────────────────────────────────────────────

def _load_endpoint_config(event_type: str) -> Optional[dict]:
    """
    registry/fallback_endpoints.json에서 event_type 엔트리 로드.
    파일 없거나 파싱 실패 시 None 반환 (Fail-Closed).
    CC=4
    """
    if not FALLBACK_ENDPOINTS_PATH.exists():
        logger.warning("FALLBACK_ENDPOINTS_NOT_FOUND: %s", FALLBACK_ENDPOINTS_PATH)
        return None
    try:
        data = json.loads(FALLBACK_ENDPOINTS_PATH.read_text(encoding="utf-8"))
        config = data.get("endpoints", {}).get(event_type)
        if config is None:
            logger.warning("FALLBACK_ENDPOINT_MISSING: event_type=%s", event_type)
        return config
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("FALLBACK_ENDPOINTS_LOAD_FAILED: %s", exc)
        return None


def _build_retry_payload(record: FallbackRecord) -> dict:
    """
    secondary endpoint 전송용 페이로드 생성.
    원본 failure 정보 + fallback 마킹 포함.
    CC=1
    """
    return {
        "event_type": record.event_type,
        "event_id": record.event_id,
        "original_endpoint": record.endpoint,
        "original_failure_reason": record.failure_reason,
        "payload_hash": record.payload_hash,
        "session": record.session,
        "timestamp": record.timestamp,
        "fallback_attempt": True,
        "p3_task": "P3-T4",
    }


def get_handler_status() -> dict:
    """Handler 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "fallback_handler",
        "layer": "sync_layer/fallback",
        "p3_task": "P3-T4",
        "max_secondary_attempts": 1,
        "fail_closed": True,
        "manual_path_preserved": True,
        "fallback_endpoints_path": str(FALLBACK_ENDPOINTS_PATH),
        "allowed_callers": sorted(ALLOWED_CALLER_MODULES),
    }

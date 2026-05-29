"""
fallback_classifier.py
AIBA Sync Layer — Fallback Classifier
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

역할:
  - transport_failure_record의 failure_reason을 3단계로 분류
  - RETRYABLE_CANDIDATE: 일시적 장애 (5xx / Timeout / Connection)
  - NON_RETRYABLE: 영구적 장애 (4xx / PAYLOAD_INVALID / ENDPOINT_NOT_FOUND)
  - INVALID_RECORD: 필드 누락 / 스키마 불일치

주의:
  - "RETRYABLE_CANDIDATE"는 자동 재시도 허용이 아닌 Fallback 대상 후보 의미
  - 실제 secondary 시도 여부는 fallback_handler가 결정

금지:
  - I/O 작업
  - HTTP 호출
  - 재시도 로직
"""

import logging
from typing import Optional

from tools.sync_layer.fallback.fallback_types import (
    CLASSIFICATION_RETRYABLE,
    CLASSIFICATION_NON_RETRYABLE,
    CLASSIFICATION_INVALID,
    REQUIRED_FAILURE_RECORD_FIELDS,
    FallbackRecord,
)

logger = logging.getLogger(__name__)

# ── 분류 기준 키워드 ─────────────────────────────────────────────────────────

_RETRYABLE_PREFIXES = (
    "HTTP_ERROR: 5",          # 5xx server errors
    "TRANSPORT_ERROR:",       # timeout / connection errors
    "UNEXPECTED_STATUS: 5",   # 5xx unexpected
)

_NON_RETRYABLE_PREFIXES = (
    "HTTP_ERROR: 4",          # 4xx client errors
    "PAYLOAD_INVALID",        # 페이로드 검증 실패
    "ENDPOINT_NOT_FOUND",     # registry 미등록 endpoint
    "UNEXPECTED_STATUS: 4",   # 4xx unexpected
)


# ── 공개 API ─────────────────────────────────────────────────────────────────

def classify_failure_record(record: dict) -> str:
    """
    transport_failure_record dict → 3단계 분류 반환.

    반환: RETRYABLE_CANDIDATE | NON_RETRYABLE | INVALID_RECORD
    CC=3
    """
    if not _validate_record_fields(record):
        return CLASSIFICATION_INVALID

    failure_reason = record.get("failure_reason", "")
    classification = _classify_by_reason(failure_reason)

    logger.debug(
        "CLASSIFY: event_id=%s reason=%s → %s",
        record.get("event_id"), failure_reason, classification,
    )
    return classification


def classify_fallback_record(fallback_record: FallbackRecord) -> str:
    """
    FallbackRecord 객체 분류 진입점.
    반환: RETRYABLE_CANDIDATE | NON_RETRYABLE | INVALID_RECORD
    CC=2
    """
    record_dict = {
        "event_id": fallback_record.event_id,
        "event_type": fallback_record.event_type,
        "endpoint": fallback_record.endpoint,
        "failure_reason": fallback_record.failure_reason,
        "payload_hash": fallback_record.payload_hash,
        "session": fallback_record.session,
        "timestamp": fallback_record.timestamp,
        "record_version": fallback_record.record_version,
    }
    return classify_failure_record(record_dict)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _validate_record_fields(record: dict) -> bool:
    """
    필수 필드 존재 여부 확인.
    누락 시 INVALID_RECORD 판정을 위해 False 반환.
    CC=2
    """
    if not isinstance(record, dict) or not record:
        return False
    missing = REQUIRED_FAILURE_RECORD_FIELDS - set(record.keys())
    if missing:
        logger.warning("INVALID_RECORD: missing fields=%s", sorted(missing))
        return False
    return True


def _classify_by_reason(failure_reason: str) -> str:
    """
    failure_reason 문자열 기반 분류.
    매칭 순서: RETRYABLE → NON_RETRYABLE → 기본 NON_RETRYABLE
    CC=3
    """
    for prefix in _RETRYABLE_PREFIXES:
        if failure_reason.startswith(prefix):
            return CLASSIFICATION_RETRYABLE

    for prefix in _NON_RETRYABLE_PREFIXES:
        if failure_reason.startswith(prefix):
            return CLASSIFICATION_NON_RETRYABLE

    # 알 수 없는 오류 → 보수적으로 NON_RETRYABLE (Fail-Closed)
    logger.warning(
        "UNKNOWN_FAILURE_REASON: '%s' → NON_RETRYABLE (Fail-Closed)", failure_reason
    )
    return CLASSIFICATION_NON_RETRYABLE

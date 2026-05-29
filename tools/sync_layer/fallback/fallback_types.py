"""
fallback_types.py
AIBA Sync Layer — Fallback Layer Types & Constants
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

역할:
  - P3-T4 전용 상수, 열거값, 데이터클래스 정의
  - 이 파일은 로직 없음 — 타입 정의 전용

금지:
  - 비즈니스 로직
  - I/O 작업
  - 외부 의존성
"""

from dataclasses import dataclass, field
from typing import Optional

# ── Classification ──────────────────────────────────────────────────────────

CLASSIFICATION_RETRYABLE = "RETRYABLE_CANDIDATE"
CLASSIFICATION_NON_RETRYABLE = "NON_RETRYABLE"
CLASSIFICATION_INVALID = "INVALID_RECORD"

# ── State Transitions ───────────────────────────────────────────────────────

STATE_UNHANDLED = "UNHANDLED"      # FAIL-{id}.json 존재
STATE_PROCESSING = "PROCESSING"   # FAIL-{id}.PROCESSING (atomic rename)
STATE_PROCESSED = "PROCESSED"     # FAIL-{id}.PROCESSED
STATE_ESCALATED = "ESCALATED"     # escalation receipt 생성됨
STATE_FATAL = "FATAL"             # 모든 경로 소진

# ── Actions ─────────────────────────────────────────────────────────────────

ACTION_SECONDARY_ATTEMPT = "SECONDARY_ENDPOINT_ATTEMPT"
ACTION_ESCALATED_ONLY = "ESCALATED_ONLY"
ACTION_INVALID = "INVALID_RECORD"

# ── Results ──────────────────────────────────────────────────────────────────

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_ESCALATED = "ESCALATED"
RESULT_FATAL = "FATAL"

# ── Versioning ───────────────────────────────────────────────────────────────

RECEIPT_VERSION = "FALLBACK_RECEIPT_v1"
REGISTRY_VERSION = "FALLBACK_REGISTRY_v1"

# ── Allowed Caller Enforcement (Jeni TA-1 준수) ─────────────────────────────

ALLOWED_CALLER_MODULES = frozenset({
    "tools.sync_layer.fallback.fallback_scanner",
    "tools.sync_layer.fallback.fallback_handler",
})

# ── Required Fields (transport_failure_record — P3-T4 입력 계약 S169) ────────

REQUIRED_FAILURE_RECORD_FIELDS = frozenset({
    "event_id",
    "event_type",
    "endpoint",
    "failure_reason",
    "payload_hash",
    "session",
    "timestamp",
    "record_version",
})

# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class FallbackRecord:
    """transport_failure_record 파싱 결과."""
    event_id: str
    event_type: str
    endpoint: str
    failure_reason: str
    payload_hash: str
    session: int
    timestamp: str
    record_version: str
    source_path: str
    classification: Optional[str] = None


@dataclass
class FallbackResult:
    """fallback_handler 처리 결과 (내부 전달용)."""
    action: str
    result: str
    fallback_endpoint: Optional[str]
    errors: list = field(default_factory=list)


@dataclass
class FallbackReceiptData:
    """fallback_receipt 저장용 데이터."""
    fallback_id: str
    source_failure_record: str
    event_id: str
    event_type: str
    original_endpoint: str
    fallback_endpoint: Optional[str]
    action: str
    result: str
    payload_hash: str
    session: int
    timestamp: str
    receipt_version: str
    p3_task: str
    validation_hint: str
    manual_path_required: bool
    errors: list = field(default_factory=list)

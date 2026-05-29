"""
transport_types.py
AIBA Sync Layer — Transport Types
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

역할:
  - Transport 레이어 공통 타입 및 상수 정의
  - Payload 필드 규격 상수
  - TransportResult (P3-T4 인터페이스 계약)

금지:
  - 비즈니스 로직 포함
  - 외부 임포트 (stdlib 제외)
"""

from dataclasses import dataclass
from typing import Optional

# ── Event Type 상수 ─────────────────────────────────────────────────────────

EVENT_TYPE_DEPLOYMENT = "DEPLOYMENT_EVENT"
EVENT_TYPE_SYNC = "SYNC_EVENT"
VALID_EVENT_TYPES = {EVENT_TYPE_DEPLOYMENT, EVENT_TYPE_SYNC}

# ── TransportResult 상태 상수 ───────────────────────────────────────────────

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_ABORTED = "ABORTED"
VALID_TRANSPORT_RESULTS = {RESULT_SUCCESS, RESULT_FAILED, RESULT_ABORTED}

# ── deploy_executor result_enum (재정의 — cross-import 방지) ────────────────

DEPLOY_RESULT_SUCCESS = "SUCCESS"
DEPLOY_RESULT_FAILED = "FAILED"
DEPLOY_RESULT_REJECTED = "REJECTED"
DEPLOY_RESULT_ABORTED = "ABORTED"
VALID_DEPLOY_RESULTS = {
    DEPLOY_RESULT_SUCCESS,
    DEPLOY_RESULT_FAILED,
    DEPLOY_RESULT_REJECTED,
    DEPLOY_RESULT_ABORTED,
}

# ── Required Fields ─────────────────────────────────────────────────────────

DEPLOYMENT_EVENT_REQUIRED_FIELDS = frozenset({
    "event_type",
    "deployment_id",
    "approval_id",
    "artifact_hash",
    "target",
    "result",
    "timestamp",
    "session",
})

SYNC_EVENT_REQUIRED_FIELDS = frozenset({
    "event_type",
    "event_id",
    "source",
    "payload_hash",
    "timestamp",
    "session",
})

# ── P3-T4 인터페이스 계약 (S169 확정) ───────────────────────────────────────

@dataclass
class TransportResult:
    """
    P3-T3 → P3-T4 인터페이스 계약.
    transport_failure_record 기록 및 P3-T4 관찰 대상.

    status:        SUCCESS / FAILED / ABORTED
    event_id:      DEPLOYMENT_EVENT → deployment_id / SYNC_EVENT → event_id
    event_type:    DEPLOYMENT_EVENT / SYNC_EVENT
    payload_hash:  SHA256 (직렬화된 payload)
    endpoint:      전송 시도 URL
    timestamp:     KST ISO8601
    failure_reason: 실패 시만 기록
    session:       세션 번호
    """
    status: str
    event_id: str
    event_type: str
    payload_hash: str
    endpoint: str
    timestamp: str
    failure_reason: Optional[str] = None
    session: int = 0

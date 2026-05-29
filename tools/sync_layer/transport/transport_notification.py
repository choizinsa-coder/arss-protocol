"""
transport_notification.py
AIBA Sync Layer — Transport Notification (Jeni Advisory 구현)
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

역할:
  - 전송 실패 시 transport_failure_record 생성 및 저장
  - P3-T4 Fallback Layer 관찰 대상 레코드 제공

Jeni Advisory (EAG-3 HG-1):
  NO RETRY / NO RECOVERY / NO SELF-HEAL
  FAIL → notification_emit → STOP

transport_failure_record 저장 경로:
  registry/transport_failures/FAIL-{event_id}.json
  → P3-T4 입력 계약 (S169 확정)

금지:
  - 재시도 로직
  - 자동 복구
  - HTTP 호출
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
FAILURE_RECORD_DIR = VPS_ROOT / "registry" / "transport_failures"
FAILURE_RECORD_VERSION = "TRANSPORT_FAILURE_RECORD_v1"
KST = timezone(timedelta(hours=9))


def emit_failure(
    event_id: str,
    event_type: str,
    endpoint: str,
    failure_reason: str,
    payload_hash: str = "",
    session: int = 0,
) -> dict:
    """
    전송 실패 통보 발행.
    transport_failure_record 생성 → VPS 저장 → 로그 기록.
    P3-T4가 이 레코드를 관찰한다.

    반환: failure_record dict
    CC=1
    """
    record = _build_failure_record(
        event_id=event_id,
        event_type=event_type,
        endpoint=endpoint,
        failure_reason=failure_reason,
        payload_hash=payload_hash,
        session=session,
    )
    _save_failure_record(record, event_id)
    logger.error(
        "TRANSPORT_FAILURE: event_id=%s reason=%s endpoint=%s",
        event_id, failure_reason, endpoint,
    )
    return record


def _build_failure_record(
    event_id: str,
    event_type: str,
    endpoint: str,
    failure_reason: str,
    payload_hash: str,
    session: int,
) -> dict:
    """P3-T4 인터페이스 계약에 따른 failure_record 빌드. CC=1"""
    return {
        "event_id": event_id,
        "event_type": event_type,
        "endpoint": endpoint,
        "failure_reason": failure_reason,
        "payload_hash": payload_hash,
        "session": session,
        "timestamp": datetime.now(KST).isoformat(),
        "record_version": FAILURE_RECORD_VERSION,
        "p3_task": "P3-T3",
    }


def _save_failure_record(record: dict, event_id: str) -> bool:
    """
    failure_record → registry/transport_failures/ 저장.
    저장 실패 시 로그만 남기고 False 반환 (STOP 흐름은 caller 책임).
    CC=2
    """
    try:
        FAILURE_RECORD_DIR.mkdir(parents=True, exist_ok=True)
        safe_id = event_id.replace("/", "_").replace(" ", "_")[:64]
        path = FAILURE_RECORD_DIR / f"FAIL-{safe_id}.json"
        content = json.dumps(record, ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        return True
    except OSError as exc:
        logger.error(
            "FAILURE_RECORD_SAVE_FAILED: event_id=%s error=%s", event_id, exc
        )
        return False

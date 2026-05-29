"""
fallback_receipt.py
AIBA Sync Layer — Fallback Receipt (P3-T5 Interface)
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

역할:
  - FallbackReceiptData → registry/fallback_receipts/FB-{event_id}.json 저장
  - P3-T5 Validation Layer가 소비하는 최종 산출물 생성
  - validation_hint: P3-T5_REQUIRED 필드 포함

P3-T5 입력 계약 (도미 설계 확정):
  fallback_receipt exists         ✓
  source_failure_record exists    ✓
  payload_hash match              ✓
  result enum valid               ✓
  session match                   ✓
  processed marker exists         ✓

금지:
  - retry 로직
  - HTTP 호출
  - P3-T3 인터페이스 변경
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tools.sync_layer.fallback.fallback_types import (
    FallbackReceiptData,
    RECEIPT_VERSION,
    RESULT_SUCCESS,
    RESULT_FAILED,
    RESULT_ESCALATED,
    RESULT_FATAL,
)

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
FALLBACK_RECEIPT_DIR = VPS_ROOT / "registry" / "fallback_receipts"
KST = timezone(timedelta(hours=9))

VALID_RESULT_ENUM = frozenset({
    RESULT_SUCCESS,
    RESULT_FAILED,
    RESULT_ESCALATED,
    RESULT_FATAL,
})


# ── 공개 API ─────────────────────────────────────────────────────────────────

def build_receipt(
    event_id: str,
    event_type: str,
    original_endpoint: str,
    fallback_endpoint: Optional[str],
    action: str,
    result: str,
    payload_hash: str,
    session: int,
    source_failure_record: str,
    errors: list = None,
    manual_path_required: bool = False,
) -> FallbackReceiptData:
    """
    FallbackReceiptData 생성.
    P3-T5 입력 계약 6개 항목 전부 포함.
    CC=1
    """
    return FallbackReceiptData(
        fallback_id=f"FB-{event_id}",
        source_failure_record=source_failure_record,
        event_id=event_id,
        event_type=event_type,
        original_endpoint=original_endpoint,
        fallback_endpoint=fallback_endpoint,
        action=action,
        result=result,
        payload_hash=payload_hash,
        session=session,
        timestamp=datetime.now(KST).isoformat(),
        receipt_version=RECEIPT_VERSION,
        p3_task="P3-T4",
        validation_hint="P3-T5_REQUIRED",
        manual_path_required=manual_path_required,
        errors=errors or [],
    )


def save_receipt(receipt: FallbackReceiptData) -> bool:
    """
    FallbackReceiptData → registry/fallback_receipts/FB-{event_id}.json 저장.
    저장 실패 시 False 반환 (STOP 흐름은 caller 책임).
    CC=3
    """
    if receipt.result not in VALID_RESULT_ENUM:
        logger.error(
            "RECEIPT_INVALID_RESULT: result=%s not in %s",
            receipt.result, sorted(VALID_RESULT_ENUM),
        )
        return False

    try:
        FALLBACK_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
        path = FALLBACK_RECEIPT_DIR / f"{receipt.fallback_id}.json"
        content = _receipt_to_json(receipt)
        return _fsync_write(path, content)
    except OSError as exc:
        logger.error("RECEIPT_SAVE_FAILED: fallback_id=%s error=%s", receipt.fallback_id, exc)
        return False


def load_receipt(event_id: str) -> Optional[dict]:
    """
    registry/fallback_receipts/FB-{event_id}.json 로드.
    파일 없거나 파싱 실패 시 None 반환.
    CC=3
    """
    path = FALLBACK_RECEIPT_DIR / f"FB-{event_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("RECEIPT_LOAD_FAILED: event_id=%s error=%s", event_id, exc)
        return None


def get_receipt_status() -> dict:
    """Receipt 디렉터리 상태 요약 (관측/감사용). CC=1"""
    count = 0
    if FALLBACK_RECEIPT_DIR.exists():
        count = len(list(FALLBACK_RECEIPT_DIR.glob("FB-*.json")))
    return {
        "component": "fallback_receipt",
        "layer": "sync_layer/fallback",
        "p3_task": "P3-T4",
        "receipt_dir": str(FALLBACK_RECEIPT_DIR),
        "receipt_version": RECEIPT_VERSION,
        "receipt_count": count,
        "p3t5_validation_hint": "P3-T5_REQUIRED",
    }


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _receipt_to_json(receipt: FallbackReceiptData) -> str:
    """FallbackReceiptData → JSON 문자열. CC=1"""
    return json.dumps({
        "fallback_id": receipt.fallback_id,
        "source_failure_record": receipt.source_failure_record,
        "event_id": receipt.event_id,
        "event_type": receipt.event_type,
        "original_endpoint": receipt.original_endpoint,
        "fallback_endpoint": receipt.fallback_endpoint,
        "action": receipt.action,
        "result": receipt.result,
        "payload_hash": receipt.payload_hash,
        "session": receipt.session,
        "timestamp": receipt.timestamp,
        "receipt_version": receipt.receipt_version,
        "p3_task": receipt.p3_task,
        "validation_hint": receipt.validation_hint,
        "manual_path_required": receipt.manual_path_required,
        "errors": receipt.errors,
    }, ensure_ascii=False, indent=2)


def _fsync_write(path: Path, content: str) -> bool:
    """파일 쓰기 + fsync. 실패 시 False. CC=2"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
                return True
            except OSError as exc:
                logger.warning("FSYNC_DEGRADED: path=%s — %s", path, exc)
                return False
    except OSError as exc:
        logger.error("FILE_WRITE_FAILED: path=%s — %s", path, exc)
        return False

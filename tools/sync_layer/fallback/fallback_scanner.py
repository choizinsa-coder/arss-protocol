"""
fallback_scanner.py
AIBA Sync Layer — Fallback Scanner
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

역할:
  - registry/transport_failures/ 폴링 → FAIL-*.json 감지
  - Atomic rename (OS 레벨) → Race Condition 완전 차단 (Jeni TA-1 강제)
  - FallbackRecord 파싱 → fallback_classifier 분류 → fallback_handler 처리
  - 처리 완료 후 .PROCESSING → .PROCESSED 전이

Jeni TA-1 Race Condition 방지:
  FAIL-{id}.json → os.rename → FAIL-{id}.PROCESSING (atomic, 같은 filesystem)
  rename 실패(FileNotFoundError/OSError) → skip (다른 인스턴스 처리 중)
  처리 완료 → os.rename → FAIL-{id}.PROCESSED

금지:
  - fallback_handler 우회 호출
  - FAIL-*.json 직접 삭제
  - PROCESSING 파일 무한 보류
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional

from tools.sync_layer.fallback.fallback_types import (
    FallbackRecord,
    REQUIRED_FAILURE_RECORD_FIELDS,
)
from tools.sync_layer.fallback.fallback_classifier import classify_failure_record
from tools.sync_layer.fallback import fallback_handler

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
FAILURE_RECORD_DIR = VPS_ROOT / "registry" / "transport_failures"
KST = timezone(timedelta(hours=9))


# ── 공개 API ─────────────────────────────────────────────────────────────────

def scan_and_handle() -> dict:
    """
    Fallback Scanner 전체 실행 진입점.
    1. FAIL-*.json 목록 수집
    2. 각 파일에 대해 atomic rename → parse → classify → handle → mark PROCESSED

    반환: {
        "scanned": int,
        "handled": int,
        "skipped": int,
        "results": list[dict],
    }
    CC=4
    """
    candidates = _list_failure_candidates()

    scanned = 0
    handled = 0
    skipped = 0
    results = []

    for candidate in candidates:
        scanned += 1
        processing_path = _atomic_claim(candidate)

        if processing_path is None:
            skipped += 1
            logger.debug("SCAN_SKIP: %s — already claimed", candidate.name)
            continue

        record = _parse_record(processing_path, source_path=str(candidate))
        if record is None:
            _mark_processed(processing_path)
            skipped += 1
            continue

        record.classification = classify_failure_record(_record_to_dict(record))

        result = fallback_handler.handle(record)
        _mark_processed(processing_path)

        handled += 1
        results.append({
            "event_id": record.event_id,
            "classification": record.classification,
            "action": result.get("action"),
            "result": result.get("result"),
            "manual_path_required": result.get("manual_path_required", True),
        })

    logger.info(
        "SCAN_COMPLETE: scanned=%d handled=%d skipped=%d",
        scanned, handled, skipped,
    )
    return {
        "scanned": scanned,
        "handled": handled,
        "skipped": skipped,
        "results": results,
    }


def list_unhandled() -> List[Path]:
    """
    미처리 FAIL-*.json 목록 반환 (관측용).
    .PROCESSING / .PROCESSED 제외.
    CC=2
    """
    return _list_failure_candidates()


def get_scanner_status() -> dict:
    """Scanner 상태 요약 (관측/감사용). CC=1"""
    unhandled = len(_list_failure_candidates())
    processing = len(list(FAILURE_RECORD_DIR.glob("FAIL-*.PROCESSING"))) if FAILURE_RECORD_DIR.exists() else 0
    processed = len(list(FAILURE_RECORD_DIR.glob("FAIL-*.PROCESSED"))) if FAILURE_RECORD_DIR.exists() else 0

    return {
        "component": "fallback_scanner",
        "layer": "sync_layer/fallback",
        "p3_task": "P3-T4",
        "failure_record_dir": str(FAILURE_RECORD_DIR),
        "unhandled_count": unhandled,
        "processing_count": processing,
        "processed_count": processed,
        "race_condition_guard": "atomic_rename",
        "jeni_advisory": "TA-1_COMPLIANT",
    }


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _list_failure_candidates() -> List[Path]:
    """
    FAIL-*.json 파일 목록 반환 (PROCESSING/PROCESSED 제외).
    디렉터리 없거나 오류 시 빈 리스트.
    CC=3
    """
    if not FAILURE_RECORD_DIR.exists():
        return []
    try:
        candidates = [
            p for p in FAILURE_RECORD_DIR.glob("FAIL-*.json")
            if p.is_file()
        ]
        return sorted(candidates)
    except OSError as exc:
        logger.error("SCAN_LIST_FAILED: %s", exc)
        return []


def _atomic_claim(source: Path) -> Optional[Path]:
    """
    Atomic rename: FAIL-{id}.json → FAIL-{id}.PROCESSING
    성공: PROCESSING 경로 반환
    실패(이미 처리 중 / 사라짐): None 반환

    Jeni TA-1: os.rename은 POSIX 보장 atomic (동일 filesystem).
    CC=3
    """
    processing_path = source.with_suffix(".PROCESSING")
    try:
        os.rename(source, processing_path)
        return processing_path
    except FileNotFoundError:
        # 다른 인스턴스가 이미 처리 중 → skip
        return None
    except OSError as exc:
        logger.warning("ATOMIC_CLAIM_FAILED: %s — %s", source.name, exc)
        return None


def _parse_record(processing_path: Path, source_path: str) -> Optional[FallbackRecord]:
    """
    PROCESSING 파일 파싱 → FallbackRecord 반환.
    필드 누락 / JSON 파싱 실패 → None (INVALID 처리).
    CC=4
    """
    try:
        data = json.loads(processing_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("RECORD_PARSE_FAILED: %s — %s", processing_path.name, exc)
        return None

    missing = REQUIRED_FAILURE_RECORD_FIELDS - set(data.keys())
    if missing:
        logger.warning("RECORD_MISSING_FIELDS: %s fields=%s", processing_path.name, sorted(missing))
        return None

    return FallbackRecord(
        event_id=str(data["event_id"]),
        event_type=str(data["event_type"]),
        endpoint=str(data["endpoint"]),
        failure_reason=str(data["failure_reason"]),
        payload_hash=str(data["payload_hash"]),
        session=int(data["session"]),
        timestamp=str(data["timestamp"]),
        record_version=str(data["record_version"]),
        source_path=source_path,
    )


def _mark_processed(processing_path: Path) -> bool:
    """
    PROCESSING 파일 → PROCESSED 전이.
    실패 시 False 반환 (로그만, STOP은 caller 판단).
    CC=2
    """
    processed_path = Path(str(processing_path).replace(".PROCESSING", ".PROCESSED"))
    try:
        os.rename(processing_path, processed_path)
        return True
    except OSError as exc:
        logger.error("MARK_PROCESSED_FAILED: %s — %s", processing_path.name, exc)
        return False


def _record_to_dict(record: FallbackRecord) -> dict:
    """FallbackRecord → dict (classifier 입력용). CC=1"""
    return {
        "event_id": record.event_id,
        "event_type": record.event_type,
        "endpoint": record.endpoint,
        "failure_reason": record.failure_reason,
        "payload_hash": record.payload_hash,
        "session": record.session,
        "timestamp": record.timestamp,
        "record_version": record.record_version,
    }

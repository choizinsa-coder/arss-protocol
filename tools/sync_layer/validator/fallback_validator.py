"""
fallback_validator.py
AIBA Sync Layer — Fallback Atomic Rename Result Validator (P3-T5)
SSOT: Domi Phase 3 Design (S171) / EAG-1 Approved (비오(Joshua))

역할:
  - registry/fallback_receipts/FB-*.json 검증
  - P3-T4 입력 계약 6개 항목 확인 (fallback_receipt.py 정의 기준):
      1. fallback_receipt exists         (F1)
      2. source_failure_record exists    (F2)
      3. processed marker exists         (F3: FAIL-{event_id}.PROCESSED)
      4. payload_hash match              (F4: receipt vs PROCESSED 파일 교차)
      5. result enum valid               (F5)
      6. session valid                   (F6)

증거 원천: receipt 기반 (SC-3 해소안 — VPS 실증)
  - registry/fallback_receipts/FB-{event_id}.json
  - registry/transport_failures/FAIL-{event_id}.PROCESSED

금지:
  - 수정 / 복구 / 재배포
  - UNKNOWN → PASS 승격
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
FALLBACK_RECEIPT_DIR = VPS_ROOT / "registry" / "fallback_receipts"
FAILURE_RECORD_DIR = VPS_ROOT / "registry" / "transport_failures"

VALID_RESULT_ENUM = frozenset({"SUCCESS", "FAILED", "ESCALATED", "FATAL"})

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"


def validate() -> dict:
    """
    Fallback receipt 전체 검증 진입점.
    registry/fallback_receipts/FB-*.json 전수 확인.
    반환: {validator, verdict, checked, failed, details[]}
    CC=5
    """
    if not FALLBACK_RECEIPT_DIR.exists():
        return _result(VERDICT_UNKNOWN, 0, 0, [{"note": "FALLBACK_RECEIPT_DIR_NOT_FOUND"}])

    try:
        receipt_files = sorted(FALLBACK_RECEIPT_DIR.glob("FB-*.json"))
    except OSError as exc:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"error": f"DIR_SCAN_FAILED: {exc}"}])

    if not receipt_files:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"note": "NO_FALLBACK_RECEIPTS"}])

    checked = 0
    failed = 0
    details = []

    for rfile in receipt_files:
        checked += 1
        verdict, issues = _validate_single(rfile)
        if verdict != VERDICT_PASS:
            failed += 1
            details.append({"file": rfile.name, "verdict": verdict, "issues": issues})

    overall = VERDICT_PASS if failed == 0 else VERDICT_FAIL
    return _result(overall, checked, failed, details)


def _validate_single(path: Path) -> tuple:
    """
    단일 fallback receipt 검증 (P3-T4 입력 계약 6개).
    반환: (verdict, issues[])
    CC=7
    """
    # F1: 파싱 가능
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return VERDICT_UNKNOWN, [f"F1_PARSE_FAILED: {exc}"]

    issues = []
    event_id = data.get("event_id", "")

    # F2: source_failure_record 필드 존재 + 비어있지 않음
    source_ref = data.get("source_failure_record", "")
    if not source_ref:
        issues.append("F2_SOURCE_FAILURE_RECORD_MISSING")

    # F3: FAIL-{event_id}.PROCESSED 마커 존재 (atomic rename 완료 증거)
    if not event_id:
        issues.append("F3_EVENT_ID_MISSING")
    else:
        processed_path = FAILURE_RECORD_DIR / f"FAIL-{event_id}.PROCESSED"
        if not processed_path.exists():
            issues.append(f"F3_PROCESSED_MARKER_NOT_FOUND: FAIL-{event_id}.PROCESSED")

    # F4: payload_hash 유효 + PROCESSED 파일과 교차 확인
    receipt_hash = data.get("payload_hash", "")
    if not receipt_hash:
        issues.append("F4_PAYLOAD_HASH_MISSING")
    elif event_id:
        source_hash = _load_source_payload_hash(event_id)
        if source_hash is not None and source_hash != receipt_hash:
            issues.append(
                f"F4_PAYLOAD_HASH_MISMATCH: receipt={receipt_hash[:8]}... "
                f"source={source_hash[:8]}..."
            )

    # F5: result enum 유효
    result_val = data.get("result", "")
    if result_val not in VALID_RESULT_ENUM:
        issues.append(f"F5_RESULT_ENUM_INVALID: {result_val!r}")

    # F6: session 유효 (양수 정수)
    session_val = data.get("session")
    if not isinstance(session_val, int) or session_val <= 0:
        issues.append(f"F6_SESSION_INVALID: {session_val!r}")

    if issues:
        return VERDICT_FAIL, issues
    return VERDICT_PASS, []


def _load_source_payload_hash(event_id: str) -> Optional[str]:
    """
    FAIL-{event_id}.PROCESSED 에서 payload_hash 추출.
    파일 없거나 파싱 실패 시 None (교차 확인 스킵 — UNKNOWN 아님).
    CC=3
    """
    processed_path = FAILURE_RECORD_DIR / f"FAIL-{event_id}.PROCESSED"
    if not processed_path.exists():
        return None
    try:
        data = json.loads(processed_path.read_text(encoding="utf-8"))
        return data.get("payload_hash")
    except (json.JSONDecodeError, OSError):
        return None


def _result(verdict: str, checked: int, failed: int, details: list) -> dict:
    """결과 딕셔너리 빌드. CC=1"""
    return {
        "validator": "fallback",
        "verdict": verdict,
        "checked": checked,
        "failed": failed,
        "details": details,
    }


def get_validator_status() -> dict:
    """Fallback Validator 상태 요약 (관측/감사용). CC=1"""
    count = 0
    if FALLBACK_RECEIPT_DIR.exists():
        count = len(list(FALLBACK_RECEIPT_DIR.glob("FB-*.json")))
    return {
        "component": "fallback_validator",
        "layer": "sync_layer/validator",
        "p3_task": "P3-T5",
        "receipt_dir": str(FALLBACK_RECEIPT_DIR),
        "failure_record_dir": str(FAILURE_RECORD_DIR),
        "receipt_count": count,
        "p3t4_contract_items": 6,
        "evidence_source": "receipt_based (SC-3 해소)",
    }

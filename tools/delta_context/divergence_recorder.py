ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/divergence_recorder.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# PT-S66-001: Shadow Mode Phase 2 — Divergence Recorder

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))
DIVERGENCE_LOG_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/divergence_log.json"

SEVERITY_HIGH = "HIGH"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_LOW = "LOW"

PHASE3_BLOCKING_SEVERITIES = {SEVERITY_HIGH}

REQUIRED_FIELDS = [
    "divergence_id",
    "session_number",
    "severity",
    "detected_at",
    "candidate_hash",
    "ssot_hash",
    "hash_match",
    "timestamp_diff_seconds",
    "mutation_violations",
    "phase3_blocked",
]


def _kst_now() -> str:
    now = datetime.now(KST)
    ms = now.strftime("%f")[:3]
    return now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), indent=None, allow_nan=False,
    )


def _load_log() -> list:
    if not os.path.exists(DIVERGENCE_LOG_PATH):
        return []
    with open(DIVERGENCE_LOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_log(entries: list) -> None:
    tmp = DIVERGENCE_LOG_PATH + ".tmp"
    os.makedirs(os.path.dirname(DIVERGENCE_LOG_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_canonical_dumps(entries))
    os.replace(tmp, DIVERGENCE_LOG_PATH)


def _determine_severity(contract: dict) -> str:
    """
    comparison_contract 결과 기반 severity 판정.
    - hash mismatch + mutation violation → HIGH
    - hash mismatch only → HIGH
    - timestamp window 초과만 → MEDIUM
    - mutation violation만 → MEDIUM
    - BLOCKED_VALIDATION → HIGH
    """
    if contract.get("contract") == "BLOCKED_VALIDATION":
        return SEVERITY_HIGH

    reasons = contract.get("reasons", [])
    has_hash = any("hash" in r for r in reasons)
    has_mutation = any("mutation" in r for r in reasons)
    has_ts = any("timestamp" in r for r in reasons)

    if has_hash or has_mutation:
        return SEVERITY_HIGH
    if has_ts:
        return SEVERITY_MEDIUM
    return SEVERITY_LOW


def record_divergence(
    session_number: int,
    contract: dict,
    sequence: int | None = None,
) -> dict:
    """
    comparison_contract FAIL/BLOCKED_VALIDATION 시 divergence 기록.

    Returns:
        {
            "success": True,
            "divergence_id": str,
            "severity": str,
            "phase3_blocked": bool,
        }
        {"success": False, "reason": str}
    """
    if contract.get("contract") == "PASS":
        return {"success": False, "reason": "contract PASS — divergence 기록 불필요"}

    try:
        seq_str = f"{sequence:04d}" if sequence is not None else "0000"
        detected_at = _kst_now()
        divergence_id = f"DIV-S{session_number}-{seq_str}-{detected_at[11:19].replace(':', '')}"

        severity = _determine_severity(contract)
        phase3_blocked = severity in PHASE3_BLOCKING_SEVERITIES

        ts_result = contract.get("timestamp_window", {})

        entry = {
            "divergence_id": divergence_id,
            "session_number": session_number,
            "severity": severity,
            "detected_at": detected_at,
            "candidate_hash": contract.get("candidate_hash", ""),
            "ssot_hash": contract.get("ssot_hash", ""),
            "hash_match": contract.get("normalized_payload_hash_match", False),
            "timestamp_diff_seconds": ts_result.get("diff_seconds"),
            "mutation_violations": contract.get("mutation_prohibition", {}).get("violations", []),
            "phase3_blocked": phase3_blocked,
            "contract_result": contract.get("contract"),
            "reasons": contract.get("reasons", []),
        }

        # 10개 필수 필드 검증
        missing = [f for f in REQUIRED_FIELDS if f not in entry]
        if missing:
            return {"success": False, "reason": f"필수 필드 누락: {missing}"}

        log = _load_log()
        log.append(entry)
        _save_log(log)

        return {
            "success": True,
            "divergence_id": divergence_id,
            "severity": severity,
            "phase3_blocked": phase3_blocked,
        }

    except Exception as e:
        return {"success": False, "reason": f"divergence 기록 실패: {e}"}


def get_divergence_summary(session_number: int | None = None) -> dict:
    """세션별 또는 전체 divergence 현황 조회"""
    log = _load_log()
    if session_number is not None:
        log = [e for e in log if e.get("session_number") == session_number]

    high = [e for e in log if e.get("severity") == SEVERITY_HIGH]
    medium = [e for e in log if e.get("severity") == SEVERITY_MEDIUM]
    low = [e for e in log if e.get("severity") == SEVERITY_LOW]

    return {
        "total": len(log),
        "high": len(high),
        "medium": len(medium),
        "low": len(low),
        "phase3_blocked": any(e.get("phase3_blocked") for e in log),
        "entries": log,
    }

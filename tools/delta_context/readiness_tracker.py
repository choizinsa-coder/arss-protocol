ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/readiness_tracker.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# PT-S66-001: Shadow Mode Phase 2 — Phase 2 Readiness Tracker

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))
READINESS_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/phase2_readiness.json"

# 5개 상태
STATE_NOT_READY = "NOT_READY"
STATE_OBSERVING = "OBSERVING"
STATE_CANDIDATE_READY = "CANDIDATE_READY"
STATE_READY_FOR_EAG_REVIEW = "READY_FOR_EAG_REVIEW"
STATE_BLOCKED_BY_DIVERGENCE = "BLOCKED_BY_DIVERGENCE"

VALID_STATES = {
    STATE_NOT_READY,
    STATE_OBSERVING,
    STATE_CANDIDATE_READY,
    STATE_READY_FOR_EAG_REVIEW,
    STATE_BLOCKED_BY_DIVERGENCE,
}

# Readiness metrics 10개
METRIC_KEYS = [
    "total_sessions_observed",
    "consecutive_pass_sessions",
    "consecutive_fail_sessions",
    "total_divergences",
    "high_severity_divergences",
    "medium_severity_divergences",
    "low_severity_divergences",
    "phase3_block_count",
    "last_contract_result",
    "last_session_number",
]

# CANDIDATE_READY 진입 기준
CANDIDATE_READY_MIN_SESSIONS = 5
CANDIDATE_READY_MIN_CONSECUTIVE_PASS = 5

# READY_FOR_EAG_REVIEW 진입 기준
EAG_REVIEW_MIN_SESSIONS = 10
EAG_REVIEW_MIN_CONSECUTIVE_PASS = 10


def _kst_now() -> str:
    now = datetime.now(KST)
    ms = now.strftime("%f")[:3]
    return now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), indent=None, allow_nan=False,
    )


def _load_tracker() -> dict:
    if not os.path.exists(READINESS_PATH):
        return _default_tracker()
    with open(READINESS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_tracker() -> dict:
    return {
        "schema_version": "1.0",
        "state": STATE_NOT_READY,
        "metrics": {k: 0 for k in METRIC_KEYS},
        "last_updated": None,
    }


def _save_tracker(tracker: dict) -> None:
    tmp = READINESS_PATH + ".tmp"
    os.makedirs(os.path.dirname(READINESS_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_canonical_dumps(tracker))
    os.replace(tmp, READINESS_PATH)


def _determine_state(metrics: dict, phase3_blocked: bool) -> str:
    if phase3_blocked or metrics["high_severity_divergences"] > 0:
        return STATE_BLOCKED_BY_DIVERGENCE

    total = metrics["total_sessions_observed"]
    consec = metrics["consecutive_pass_sessions"]

    if total >= EAG_REVIEW_MIN_SESSIONS and consec >= EAG_REVIEW_MIN_CONSECUTIVE_PASS:
        return STATE_READY_FOR_EAG_REVIEW
    if total >= CANDIDATE_READY_MIN_SESSIONS and consec >= CANDIDATE_READY_MIN_CONSECUTIVE_PASS:
        return STATE_CANDIDATE_READY
    if total > 0:
        return STATE_OBSERVING
    return STATE_NOT_READY


def record_session(
    session_number: int,
    contract_result: str,
    divergence_summary: dict,
) -> dict:
    """
    Phase 2 세션 결과 기록 및 상태 전이.

    contract_result: "PASS" | "FAIL" | "BLOCKED_VALIDATION"
    divergence_summary: get_divergence_summary() 반환값

    Returns:
        {"success": True, "state": str, "metrics": dict}
        {"success": False, "reason": str}
    """
    try:
        tracker = _load_tracker()
        m = tracker["metrics"]

        m["total_sessions_observed"] = m.get("total_sessions_observed", 0) + 1
        m["last_session_number"] = session_number
        m["last_contract_result"] = contract_result

        if contract_result == "PASS":
            m["consecutive_pass_sessions"] = m.get("consecutive_pass_sessions", 0) + 1
            m["consecutive_fail_sessions"] = 0
        else:
            m["consecutive_fail_sessions"] = m.get("consecutive_fail_sessions", 0) + 1
            m["consecutive_pass_sessions"] = 0

        m["total_divergences"] = divergence_summary.get("total", 0)
        m["high_severity_divergences"] = divergence_summary.get("high", 0)
        m["medium_severity_divergences"] = divergence_summary.get("medium", 0)
        m["low_severity_divergences"] = divergence_summary.get("low", 0)
        m["phase3_block_count"] = m.get("phase3_block_count", 0) + (
            1 if divergence_summary.get("phase3_blocked") else 0
        )

        phase3_blocked = divergence_summary.get("phase3_blocked", False)
        new_state = _determine_state(m, phase3_blocked)

        tracker["state"] = new_state
        tracker["metrics"] = m
        tracker["last_updated"] = _kst_now()

        _save_tracker(tracker)

        return {
            "success": True,
            "state": new_state,
            "metrics": m,
        }

    except Exception as e:
        return {"success": False, "reason": f"readiness tracker 기록 실패: {e}"}


def get_readiness_state() -> dict:
    """현재 Phase 2 readiness 상태 조회"""
    tracker = _load_tracker()
    return {
        "state": tracker["state"],
        "metrics": tracker["metrics"],
        "last_updated": tracker["last_updated"],
    }

ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/switch_readiness_tracker.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# BK-4: Canonical Switch GATE-1~6 자동 점검

import json
import os
from typing import Any

TRACKER_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/switch_readiness.json"


def _load_tracker() -> dict:
    if not os.path.exists(TRACKER_PATH):
        return {
            "schema_version": "1.0",
            "canonical_switch_allowed": False,
            "gates": {
                "GATE_1": {"desc": "최근 연속 10세션 shadow write 실패 = 0회",
                           "consecutive_clean": 0, "required": 10, "pass": False},
                "GATE_2": {"desc": "최근 연속 10세션 index_validator PASS",
                           "consecutive_pass": 0, "required": 10, "pass": False},
                "GATE_3": {"desc": "전체 delta chain parent_hash 100% 일치",
                           "chain_clean": False, "pass": False},
                "GATE_4": {"desc": "최근 연속 3세션 MERGE_VALIDATOR PASS",
                           "consecutive_pass": 0, "required": 3, "pass": False},
                "GATE_5": {"desc": "최근 연속 5세션 divergence_report 미생성",
                           "consecutive_clean": 0, "required": 5, "pass": False},
                "GATE_6": {"desc": "최근 10세션 RECONSTRUCTION_MODE 미발동",
                           "consecutive_clean": 0, "required": 10, "pass": False},
            },
            "gate_7_note": "GATE-7: 비오(Joshua) EAG 명시 승인 — 자동 점검 불가. 수동 확인 필수.",
            "last_updated": None,
        }
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_tracker(tracker: dict) -> None:
    tmp = TRACKER_PATH + ".tmp"
    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(tracker, f, sort_keys=True, ensure_ascii=True,
                  separators=(",", ":"), indent=2)
    os.replace(tmp, TRACKER_PATH)


def _evaluate_gates(tracker: dict) -> bool:
    """GATE-1~6 전부 pass 여부 반환 (GATE-7은 수동)"""
    gates = tracker["gates"]
    return all(g["pass"] for g in gates.values())


def record_session_result(
    session_number: int,
    shadow_write_success: bool,
    index_validator_pass: bool,
    chain_clean: bool,
    merge_validator_pass: bool,
    divergence_generated: bool,
    reconstruction_activated: bool,
    generated_at: str,
) -> dict:
    """
    세션 종료 후 GATE-1~6 카운터 갱신.
    BK-4 차단 조건 발동 시 해당 GATE 카운트 리셋.

    Returns:
        {"success": True, "canonical_switch_allowed": bool, "gates": dict}
        {"success": False, "reason": str}
    """
    try:
        tracker = _load_tracker()
        gates = tracker["gates"]

        # GATE-1: shadow write 실패 2회 → 리셋
        if shadow_write_success:
            gates["GATE_1"]["consecutive_clean"] = min(
                gates["GATE_1"]["consecutive_clean"] + 1, 10
            )
        else:
            gates["GATE_1"]["consecutive_clean"] = 0
        gates["GATE_1"]["pass"] = (
            gates["GATE_1"]["consecutive_clean"] >= gates["GATE_1"]["required"]
        )

        # GATE-2: index_validator FAIL 1회 → 리셋
        if index_validator_pass:
            gates["GATE_2"]["consecutive_pass"] = min(
                gates["GATE_2"]["consecutive_pass"] + 1, 10
            )
        else:
            gates["GATE_2"]["consecutive_pass"] = 0
        gates["GATE_2"]["pass"] = (
            gates["GATE_2"]["consecutive_pass"] >= gates["GATE_2"]["required"]
        )

        # GATE-3: chain 불일치 1건 → 리셋
        if chain_clean:
            gates["GATE_3"]["chain_clean"] = True
        else:
            gates["GATE_3"]["chain_clean"] = False
        gates["GATE_3"]["pass"] = gates["GATE_3"]["chain_clean"]

        # GATE-4: MERGE_VALIDATOR FAIL → 리셋
        if merge_validator_pass:
            gates["GATE_4"]["consecutive_pass"] = min(
                gates["GATE_4"]["consecutive_pass"] + 1, 3
            )
        else:
            gates["GATE_4"]["consecutive_pass"] = 0
        gates["GATE_4"]["pass"] = (
            gates["GATE_4"]["consecutive_pass"] >= gates["GATE_4"]["required"]
        )

        # GATE-5: divergence_report 생성 1회 → 리셋
        if not divergence_generated:
            gates["GATE_5"]["consecutive_clean"] = min(
                gates["GATE_5"]["consecutive_clean"] + 1, 5
            )
        else:
            gates["GATE_5"]["consecutive_clean"] = 0
        gates["GATE_5"]["pass"] = (
            gates["GATE_5"]["consecutive_clean"] >= gates["GATE_5"]["required"]
        )

        # GATE-6: RECONSTRUCTION_MODE 발동 1회 → 리셋
        if not reconstruction_activated:
            gates["GATE_6"]["consecutive_clean"] = min(
                gates["GATE_6"]["consecutive_clean"] + 1, 10
            )
        else:
            gates["GATE_6"]["consecutive_clean"] = 0
        gates["GATE_6"]["pass"] = (
            gates["GATE_6"]["consecutive_clean"] >= gates["GATE_6"]["required"]
        )

        tracker["canonical_switch_allowed"] = _evaluate_gates(tracker)
        tracker["last_updated"] = generated_at
        _save_tracker(tracker)

        return {
            "success":                  True,
            "canonical_switch_allowed": tracker["canonical_switch_allowed"],
            "gates":                    gates,
        }

    except Exception as e:
        return {"success": False, "reason": f"tracker 갱신 실패: {e}"}


def get_readiness_report() -> dict:
    """현재 GATE 상태 조회"""
    tracker = _load_tracker()
    return {
        "canonical_switch_allowed": tracker["canonical_switch_allowed"],
        "gates":                    tracker["gates"],
        "gate_7_note":              tracker["gate_7_note"],
        "last_updated":             tracker["last_updated"],
    }


# ── Phase 2 readiness_state 스키마 ────────────────────────────────────────────

PHASE2_READINESS_SCHEMA = {
    "state_values": [
        "NOT_READY",
        "OBSERVING",
        "CANDIDATE_READY",
        "READY_FOR_EAG_REVIEW",
        "BLOCKED_BY_DIVERGENCE",
    ],
    "metric_keys": [
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
    ],
    "phase3_block_condition": "high_severity_divergences > 0 OR phase3_block_count > 0",
    "eag_review_condition": "total_sessions_observed >= 10 AND consecutive_pass_sessions >= 10",
    "candidate_ready_condition": "total_sessions_observed >= 5 AND consecutive_pass_sessions >= 5",
}


def get_phase2_readiness_schema() -> dict:
    """Phase 2 readiness_state 스키마 반환"""
    return PHASE2_READINESS_SCHEMA

# tools/delta_context/atomic_sync.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Final_Ack + divergence check — silent drift 방지

import json
import os
import hashlib
from typing import Any

DELTA_LOG_BASE = "/opt/arss/engine/arss-protocol/DELTA_LOG"
INDEX_PATH = os.path.join(DELTA_LOG_BASE, "INDEX.json")
DIVERGENCE_LOG_PATH = os.path.join(DELTA_LOG_BASE, "divergence_reports")


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        indent=None,
        allow_nan=False,
    )


def _load_json(path: str) -> dict | None:
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_divergence_report(session_number: int, reason: str, detail: dict) -> str:
    os.makedirs(DIVERGENCE_LOG_PATH, exist_ok=True)
    report_path = os.path.join(
        DIVERGENCE_LOG_PATH, f"divergence_S{session_number}.json"
    )
    report = {
        "session_number": session_number,
        "reason":         reason,
        "detail":         detail,
    }
    tmp = report_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, ensure_ascii=True,
                  separators=(",", ":"), indent=2)
    os.replace(tmp, report_path)
    return report_path


def verify_chain_integrity(session_number: int, written_deltas: list[dict]) -> dict:
    """
    delta chain parent_hash 연속성 확인.
    불일치 1건 → HARD STOP + divergence_report 생성.

    Returns:
        {"valid": True}
        {"valid": False, "hard_stop": True, "reason": str, "report_path": str}
    """
    if not written_deltas:
        return {"valid": True}

    sorted_deltas = sorted(written_deltas, key=lambda d: d["sequence_number"])

    for i, delta in enumerate(sorted_deltas):
        if i == 0:
            continue

        prev = sorted_deltas[i - 1]
        expected_parent_payload = {
            "prev_content_hash": prev["content_hash"],
            "prev_delta_id":     prev["delta_id"],
        }
        expected_parent_hash = hashlib.sha256(
            _canonical_dumps(expected_parent_payload).encode("utf-8")
        ).hexdigest()

        actual_parent_hash = delta.get("parent_hash", "")

        if actual_parent_hash != expected_parent_hash:
            detail = {
                "delta_id":             delta["delta_id"],
                "expected_parent_hash": expected_parent_hash,
                "actual_parent_hash":   actual_parent_hash,
                "prev_delta_id":        prev["delta_id"],
            }
            report_path = _write_divergence_report(
                session_number,
                "CHAIN_INTEGRITY_VIOLATION",
                detail,
            )
            return {
                "valid":       False,
                "hard_stop":   True,
                "reason":      f"parent_hash 불일치: delta_id={delta['delta_id']}",
                "detail":      detail,
                "report_path": report_path,
            }

    return {"valid": True}


def verify_index_consistency(session_number: int, written_deltas: list[dict]) -> dict:
    """
    INDEX.json과 written_deltas 일치 확인.
    불일치 → HARD STOP + divergence_report 생성.

    Returns:
        {"valid": True}
        {"valid": False, "hard_stop": True, "reason": str, "report_path": str}
    """
    index = _load_json(INDEX_PATH)
    if index is None:
        detail = {"reason": "INDEX.json 미존재"}
        report_path = _write_divergence_report(
            session_number, "INDEX_MISSING", detail
        )
        return {
            "valid":       False,
            "hard_stop":   True,
            "reason":      "INDEX.json 미존재 — divergence",
            "report_path": report_path,
        }

    s_key = f"S{session_number}"

    for delta in written_deltas:
        domain = delta["domain"]
        delta_id = delta["delta_id"]
        content_hash = delta["content_hash"]

        domain_entry = index.get("domains", {}).get(domain)
        if domain_entry is None:
            detail = {"domain": domain, "delta_id": delta_id}
            report_path = _write_divergence_report(
                session_number, "INDEX_DOMAIN_MISSING", detail
            )
            return {
                "valid":       False,
                "hard_stop":   True,
                "reason":      f"INDEX domain 미존재: {domain}",
                "report_path": report_path,
            }

        session_deltas = domain_entry.get("sessions", {}).get(s_key, [])
        matched = any(
            d["delta_id"] == delta_id and d["content_hash"] == content_hash
            for d in session_deltas
        )

        if not matched:
            detail = {
                "domain":       domain,
                "delta_id":     delta_id,
                "content_hash": content_hash,
            }
            report_path = _write_divergence_report(
                session_number, "INDEX_DELTA_MISMATCH", detail
            )
            return {
                "valid":       False,
                "hard_stop":   True,
                "reason":      f"INDEX delta 불일치: {delta_id}",
                "report_path": report_path,
            }

    return {"valid": True}


def final_ack(session_number: int, written_deltas: list[dict]) -> dict:
    """
    세션 종료 Final_Ack — chain + index 동시 검증.
    둘 중 하나라도 실패 → HARD STOP.

    Returns:
        {"success": True}
        {"success": False, "hard_stop": True, "reason": str}
    """
    # chain integrity 확인
    chain_result = verify_chain_integrity(session_number, written_deltas)
    if not chain_result["valid"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    chain_result["reason"],
            "stage":     "CHAIN_INTEGRITY",
        }

    # index consistency 확인
    index_result = verify_index_consistency(session_number, written_deltas)
    if not index_result["valid"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    index_result["reason"],
            "stage":     "INDEX_CONSISTENCY",
        }

    return {"success": True}

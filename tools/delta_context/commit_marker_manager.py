# tools/delta_context/commit_marker_manager.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# FIX-2: TX without COMMIT = 세션 종료 전 HARD STOP

import json
import os

COMMIT_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/commits"
TX_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/transactions"


def _atomic_write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, sort_keys=True, ensure_ascii=True,
                  separators=(",", ":"), indent=2)
    os.replace(tmp, path)


def create_commit(
    session_number: int,
    tx_id: str,
    transaction_hash: str,
    committed_by: str,
    generated_at: str,
) -> dict:
    """
    COMMIT-S{n}.json 생성.

    Returns:
        {"success": True, "commit_id": str, "path": str}
        {"success": False, "reason": str}
    """
    if committed_by != "caddy":
        return {
            "success": False,
            "reason": f"committed_by must be 'caddy', got {committed_by!r}",
        }

    commit_id = f"COMMIT-S{session_number}"
    commit = {
        "commit_id":        commit_id,
        "session_number":   session_number,
        "tx_id":            tx_id,
        "transaction_hash": transaction_hash,
        "committed_by":     committed_by,
        "generated_at":     generated_at,
        "status":           "COMMITTED",
    }

    path = os.path.join(COMMIT_BASE_PATH, f"{commit_id}.json")

    try:
        _atomic_write(path, commit)
    except Exception as e:
        return {"success": False, "reason": f"COMMIT atomic write 실패: {e}"}

    return {"success": True, "commit_id": commit_id, "path": path}


def verify_commit_exists(session_number: int) -> dict:
    """
    FIX-2: 세션 종료 gate — COMMIT 존재 확인.
    TX 존재 + COMMIT 미존재 → HARD STOP 반환.

    Returns:
        {"exists": True}
        {"exists": False, "hard_stop": True, "reason": str}
        {"exists": False, "hard_stop": False, "reason": str}
    """
    commit_id = f"COMMIT-S{session_number}"
    commit_path = os.path.join(COMMIT_BASE_PATH, f"{commit_id}.json")
    tx_id = f"TX-S{session_number}"
    tx_path = os.path.join(TX_BASE_PATH, f"{tx_id}.json")

    if os.path.exists(commit_path):
        return {"exists": True}

    tx_exists = os.path.exists(tx_path)

    if tx_exists:
        return {
            "exists":    False,
            "hard_stop": True,
            "reason": (
                f"FIX-2 VIOLATION: {tx_id} 존재하나 {commit_id} 미존재. "
                "세션 종료 HARD STOP. TX/delta INCOMPLETE/PENDING_VOID 마킹 필요. "
                "비오님 보고 필수."
            ),
        }

    return {
        "exists":    False,
        "hard_stop": False,
        "reason":    "TX 미존재 — delta 없는 세션 (정상)",
    }

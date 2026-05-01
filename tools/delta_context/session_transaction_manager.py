# tools/delta_context/session_transaction_manager.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# TX-S{n}.json 생성 및 관리

import json
import os
import hashlib
from typing import Any

TX_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/transactions"


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        indent=None,
        allow_nan=False,
    )


def compute_transaction_hash(
    session_number: int,
    committed_by: str,
    included_deltas: list[dict],
) -> str:
    """
    BK-1: transaction_hash 입력
      session_number / committed_by /
      included_deltas(sequence_number 오름차순) / all_delta_hashes
    """
    sorted_deltas = sorted(included_deltas, key=lambda d: d["sequence_number"])
    all_delta_hashes = [d["content_hash"] for d in sorted_deltas]

    payload = {
        "all_delta_hashes":  all_delta_hashes,
        "committed_by":      committed_by,
        "included_deltas":   [
            {
                "delta_id":        d["delta_id"],
                "sequence_number": d["sequence_number"],
            }
            for d in sorted_deltas
        ],
        "session_number":    session_number,
    }
    raw = _canonical_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, sort_keys=True, ensure_ascii=True,
                           separators=(",", ":"), indent=2))
    os.replace(tmp, path)


def create_transaction(
    session_number: int,
    committed_by: str,
    included_deltas: list[dict],
    generated_at: str,
) -> dict:
    """
    TX-S{n}.json 생성.

    included_deltas: write_delta() 반환 delta 객체 리스트
    committed_by: "caddy" 고정

    Returns:
        {"success": True, "tx_id": str, "path": str, "transaction_hash": str}
        {"success": False, "reason": str}
    """
    if not included_deltas:
        return {
            "success": False,
            "reason": "included_deltas가 비어 있음 — TX 생성 불가 (BK-5 CASE-C 방지)",
        }

    if committed_by != "caddy":
        return {
            "success": False,
            "reason": f"committed_by must be 'caddy', got {committed_by!r}",
        }

    tx_id = f"TX-S{session_number}"

    try:
        tx_hash = compute_transaction_hash(
            session_number, committed_by, included_deltas
        )
    except Exception as e:
        return {"success": False, "reason": f"transaction_hash 계산 실패: {e}"}

    sorted_deltas = sorted(included_deltas, key=lambda d: d["sequence_number"])

    tx = {
        "tx_id":             tx_id,
        "session_number":    session_number,
        "committed_by":      committed_by,
        "status":            "PENDING",
        "transaction_hash":  tx_hash,
        "generated_at":      generated_at,
        "included_deltas": [
            {
                "delta_id":        d["delta_id"],
                "domain":          d["domain"],
                "sequence_number": d["sequence_number"],
                "content_hash":    d["content_hash"],
            }
            for d in sorted_deltas
        ],
    }

    path = os.path.join(TX_BASE_PATH, f"{tx_id}.json")

    try:
        _atomic_write(path, tx)
    except Exception as e:
        return {"success": False, "reason": f"TX atomic write 실패: {e}"}

    return {
        "success":          True,
        "tx_id":            tx_id,
        "path":             path,
        "transaction_hash": tx_hash,
        "tx":               tx,
    }


def mark_incomplete(session_number: int, reason: str) -> dict:
    """
    BK-5 CASE-B: TX exists, COMMIT 없음 → TX.status = INCOMPLETE
    FIX-2 적용: 세션 종료 시 HARD STOP 전 호출
    """
    tx_id = f"TX-S{session_number}"
    path = os.path.join(TX_BASE_PATH, f"{tx_id}.json")

    if not os.path.exists(path):
        return {"success": False, "reason": f"{tx_id}.json 미존재"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            tx = json.load(f)
        tx["status"] = "INCOMPLETE"
        tx["incomplete_reason"] = reason
        _atomic_write(path, tx)
        return {"success": True, "tx_id": tx_id, "status": "INCOMPLETE"}
    except Exception as e:
        return {"success": False, "reason": f"INCOMPLETE 마킹 실패: {e}"}

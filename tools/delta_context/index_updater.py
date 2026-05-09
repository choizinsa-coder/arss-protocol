ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/index_updater.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# FIX-1: index_updater 실패 시 delta 즉시 QUARANTINED — half-valid state 금지

import json
import os
import shutil
from typing import Any

INDEX_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/INDEX.json"
QUARANTINE_BASE = "/opt/arss/engine/arss-protocol/DELTA_LOG/quarantine"


def _load_index() -> dict:
    if not os.path.exists(INDEX_PATH):
        return {
            "schema_version": "1.0",
            "domains": {},
            "last_updated": None,
        }
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_index(index: dict) -> None:
    tmp = INDEX_PATH + ".tmp"
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(index, f, sort_keys=True, ensure_ascii=True,
                  separators=(",", ":"), indent=2)
    os.replace(tmp, INDEX_PATH)


def _quarantine_delta(delta_path: str, delta_id: str, reason: str) -> dict:
    """
    FIX-1: delta를 quarantine으로 이동 + status = QUARANTINED 마킹.
    quarantine 이동 실패 시에도 HARD STOP 상태 유지 — 자동 복구 금지.
    """
    try:
        os.makedirs(QUARANTINE_BASE, exist_ok=True)
        dest = os.path.join(QUARANTINE_BASE, os.path.basename(delta_path))

        # delta 파일 읽어서 status 갱신 후 이동
        if os.path.exists(delta_path):
            with open(delta_path, "r", encoding="utf-8") as f:
                delta_data = json.load(f)
            delta_data["status"] = "QUARANTINED"
            delta_data["quarantine_reason"] = reason
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(delta_data, f, sort_keys=True, ensure_ascii=True,
                          separators=(",", ":"), indent=2)
            os.remove(delta_path)

        return {"quarantined": True, "dest": dest}
    except Exception as e:
        # quarantine 이동 자체 실패 — HARD STOP 유지, 자동 복구 금지
        return {"quarantined": False, "error": str(e)}


def update_index(delta: dict, delta_path: str) -> dict:
    """
    INDEX.json에 delta 등록.

    FIX-1 적용:
    - 실패 시 delta 즉시 QUARANTINED
    - TX/COMMIT 생성 진입 금지
    - HARD STOP + 비오 보고 필요

    Returns:
        {"success": True}
        {"success": False, "hard_stop": True, "reason": str, "quarantine": dict}
    """
    domain = delta["domain"]
    delta_id = delta["delta_id"]
    session_number = delta["session_number"]
    sequence_number = delta["sequence_number"]
    content_hash = delta["content_hash"]
    event_type = delta["event_type"]
    target_key = delta["target_key"]
    generated_at = delta["generated_at"]

    try:
        index = _load_index()

        if domain not in index["domains"]:
            index["domains"][domain] = {
                "latest_delta_id": None,
                "latest_content_hash": None,
                "delta_count": 0,
                "sessions": {},
                "latest_summary": {
                    "event_type": None,
                    "target_key": None,
                    "generated_at": None,
                },
            }

        domain_entry = index["domains"][domain]

        # 세션 엔트리 초기화
        s_key = f"S{session_number}"
        if s_key not in domain_entry["sessions"]:
            domain_entry["sessions"][s_key] = []

        domain_entry["sessions"][s_key].append({
            "delta_id":        delta_id,
            "sequence_number": sequence_number,
            "content_hash":    content_hash,
            "event_type":      event_type,
            "target_key":      target_key,
            "generated_at":    generated_at,
        })

        domain_entry["latest_delta_id"]    = delta_id
        domain_entry["latest_content_hash"] = content_hash
        domain_entry["delta_count"]        += 1
        domain_entry["latest_summary"] = {
            "event_type":   event_type,
            "target_key":   target_key,
            "generated_at": generated_at,
        }

        index["last_updated"] = generated_at
        _save_index(index)

        return {"success": True}

    except Exception as e:
        # FIX-1: index_updater 실패 → delta 즉시 QUARANTINED
        reason = f"index_updater 실패: {e}"
        quarantine_result = _quarantine_delta(delta_path, delta_id, reason)

        return {
            "success":    False,
            "hard_stop":  True,
            "reason":     reason,
            "quarantine": quarantine_result,
            "message":    (
                "HARD STOP: index_updater 실패로 delta QUARANTINED. "
                "TX/COMMIT 생성 진입 금지. 비오님 보고 필요."
            ),
        }

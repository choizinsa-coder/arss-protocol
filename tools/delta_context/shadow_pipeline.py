ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/shadow_pipeline.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Shadow sidecar -- SESSION_CONTEXT.json is still SSOT
# CORE+DELTA is non-canonical shadow structure

import os
import json
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.delta_writer import write_delta
from tools.delta_context.index_updater import update_index
from tools.delta_context.session_transaction_manager import mutate_create_transaction, mark_incomplete
from tools.delta_context.commit_marker_manager import create_commit, verify_commit_exists
from tools.delta_context.phase2_validator import run_with_collapse_gate
from tools.delta_context.stage0_idempotency_classifier import classify_stage0
from tools.delta_context.divergence_recorder import record_divergence, get_divergence_summary
from tools.delta_context.readiness_tracker import record_session

KST = timezone(timedelta(hours=9))

DELTA_LOG_BASE   = "/opt/arss/engine/arss-protocol/DELTA_LOG"
TX_BASE_PATH     = "/opt/arss/engine/arss-protocol/DELTA_LOG/transactions"
COMMIT_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/commits"

# diagnostic/log timestamp only -- do not use as generated_at source
def _runtime_observed_at():
    now = datetime.now(KST)
    ms = now.strftime("%f")[:3]
    return now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")


def run_shadow_pipeline(
    session_number,
    delta_requests,
    generated_at,
    ssot_payload_provider=None,
):
    """
    Shadow Mode session close pipeline.

    Returns:
        {"success": True, "commit_id": str, "delta_count": int}
        {"success": False, "hard_stop": True, "reason": str, "stage": str}
    """
    # PRECONDITION: generated_at validation
    if not isinstance(generated_at, str) or not generated_at:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "generated_at missing or empty",
            "stage":     "PRECONDITION_GATE",
        }
    try:
        datetime.fromisoformat(generated_at)
    except ValueError:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"generated_at ISO8601 parse failed: {repr(generated_at)}",
            "stage":     "PRECONDITION_GATE",
        }

    if not delta_requests:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "delta_requests empty",
            "stage":     "PRE_CHECK",
        }

    committed_by = "caddy"
    written_deltas = []

    # Stage 0: PRE_DELTA_IDEMPOTENCY_GATE
    domains = list({req["domain"] for req in delta_requests})
    stage0_result = classify_stage0(
        session_number=session_number,
        domains=domains,
        delta_log_base=DELTA_LOG_BASE,
        tx_base_path=TX_BASE_PATH,
        commit_base_path=COMMIT_BASE_PATH,
    )
    if stage0_result["gate"] == "ALLOW_ALREADY_COMPLETED":
        return {
            "success": True,
            "reason":  "ALREADY_COMPLETED",
            "stage":   "PRE_DELTA_IDEMPOTENCY_GATE",
        }
    if stage0_result["gate"] == "FAIL_CLOSED":
        return {
            "success":    False,
            "hard_stop":  True,
            "reason":     stage0_result["reason"],
            "state":      stage0_result["state"],
            "hash_check": stage0_result.get("hash_check", {}),
            "stage":      "PRE_DELTA_IDEMPOTENCY_GATE",
        }
    # gate == "ALLOW_NEW_RUN" -> fall-through to Stage 1+

    # Stage 1+2: DELTA_WRITE + INDEX_UPDATE
    for req in delta_requests:
        write_result = write_delta(
            domain=req["domain"],
            session_number=session_number,
            sequence_number=req["sequence_number"],
            event_type=req["event_type"],
            target_key=req["target_key"],
            new_value=req["new_value"],
            cross_ref=req["cross_ref"],
            prev_delta_id=req["prev_delta_id"],
            prev_content_hash=req["prev_content_hash"],
        )
        if not write_result["success"]:
            return {
                "success":    False,
                "hard_stop":  True,
                "reason":     f"delta_writer failed: {write_result.get(chr(39)+'reason'+chr(39))}",
                "stage":      "DELTA_WRITE",
                "failed_req": req,
            }
        delta = write_result["delta"]
        delta_path = write_result["path"]
        index_result = update_index(delta, delta_path)
        if not index_result["success"]:
            return {
                "success":    False,
                "hard_stop":  True,
                "reason":     index_result["reason"],
                "stage":      "INDEX_UPDATE",
                "quarantine": index_result.get("quarantine"),
                "message":    index_result.get("message"),
            }
        written_deltas.append(delta)

    # Stage 3: TX_CREATE
    tx_result = mutate_create_transaction(
        session_number=session_number,
        committed_by=committed_by,
        included_deltas=written_deltas,
        generated_at=generated_at,
    )
    if not tx_result["success"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"TX create failed: {tx_result.get(chr(39)+'reason'+chr(39))}",
            "stage":     "TX_CREATE",
        }
    tx_id = tx_result["tx_id"]
    transaction_hash = tx_result["transaction_hash"]

    # Stage 4: COMMIT_CREATE
    commit_result = create_commit(
        session_number=session_number,
        tx_id=tx_id,
        transaction_hash=transaction_hash,
        committed_by=committed_by,
        generated_at=generated_at,
    )
    if not commit_result["success"]:
        mark_incomplete(session_number, f"COMMIT create failed: {commit_result.get(chr(39)+'reason'+chr(39))}")
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"COMMIT create failed: {commit_result.get(chr(39)+'reason'+chr(39))}",
            "stage":     "COMMIT_CREATE",
        }

    # Stage 5: PRE_COMMIT_GATE
    pre_commit_check = verify_commit_exists(session_number)
    if pre_commit_check.get("hard_stop"):
        mark_incomplete(session_number, pre_commit_check["reason"])
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    pre_commit_check["reason"],
            "stage":     "PRE_COMMIT_GATE",
        }

    # Stage 6: POST_COMMIT_VERIFY
    final_check = verify_commit_exists(session_number)
    if not final_check["exists"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "COMMIT existence check failed after creation",
            "stage":     "POST_COMMIT_VERIFY",
        }

    # Stage 6.5: TX COMMITTED update
    try:
        tx_file_path = os.path.join(TX_BASE_PATH, f"{tx_id}.json")
        with open(tx_file_path, "r", encoding="utf-8") as f:
            tx_data = json.load(f)
        tx_data["status"] = "COMMITTED"
        with open(tx_file_path, "w", encoding="utf-8") as f:
            json.dump(tx_data, f, sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2)
    except Exception as e:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "TX_COMMIT_UPDATE_FAILED",
            "stage":     "TX_COMMIT_UPDATE",
            "error":     str(e),
        }

    # Stage 6.5: INDEX transaction registration
    try:
        index_path = os.path.join(DELTA_LOG_BASE, "INDEX.json")
        with open(index_path, "r", encoding="utf-8") as f:
            index_data = json.load(f)
        if "transactions" not in index_data:
            index_data["transactions"] = []
        if not any(t.get("tx_id") == tx_id for t in index_data["transactions"]):
            index_data["transactions"].append({"tx_id": tx_id, "status": "COMMITTED"})
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f, sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2)
    except Exception as e:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "INDEX_TRANSACTION_REGISTER_FAILED",
            "stage":     "INDEX_TRANSACTION_REGISTER",
            "error":     str(e),
        }

    # Stage 7: Phase 2 Validator
    candidate_payload = {d["target_key"]: d["new_value"] for d in written_deltas}
    candidate_payload["generated_at"] = generated_at

    if ssot_payload_provider is None:
        from tools.delta_context.ssot_time_payload_provider import provide as _default_provider
        ssot_payload_provider = _default_provider
    try:
        ssot_payload = ssot_payload_provider(
            session_number=session_number,
            written_deltas=written_deltas,
            generated_at=generated_at,
        )
    except Exception as e:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "SSOT_PAYLOAD_PROVIDER_EXCEPTION",
            "stage":     "PHASE2_VALIDATION",
            "error":     str(e),
        }
    if ssot_payload is None or not isinstance(ssot_payload, dict):
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "SSOT_PAYLOAD_PROVIDER_INVALID_RETURN",
            "stage":     "PHASE2_VALIDATION",
        }
    stl = ssot_payload.get("session_time_lock")
    if stl is None or not isinstance(stl, dict):
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "SSOT_PAYLOAD_FIELD_MISSING",
            "stage":     "PHASE2_VALIDATION",
            "missing":   "session_time_lock",
        }
    for _field in ("source", "timezone", "generated_at", "observed_at"):
        if not stl.get(_field) or not isinstance(stl[_field], str):
            return {
                "success":   False,
                "hard_stop": True,
                "reason":    "SSOT_PAYLOAD_FIELD_MISSING",
                "stage":     "PHASE2_VALIDATION",
                "missing":   f"session_time_lock.{_field}",
            }
    import re as _re
    _ISO8601_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
    for _ts_field in ("generated_at", "observed_at"):
        if not _ISO8601_RE.match(stl[_ts_field]):
            return {
                "success":   False,
                "hard_stop": True,
                "reason":    "SSOT_PAYLOAD_TIMESTAMP_INVALID",
                "stage":     "PHASE2_VALIDATION",
                "field":     f"session_time_lock.{_ts_field}",
            }
    if not isinstance(stl.get("epoch_ms"), int):
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "SSOT_PAYLOAD_FIELD_TYPE_INVALID",
            "stage":     "PHASE2_VALIDATION",
            "field":     "session_time_lock.epoch_ms",
        }

    phase2_ctx = {
        "shadow_mode":       True,
        "index_loaded":      True,
        "delta_count":       len(written_deltas),
        "session_number":    session_number,
        "phase1_complete":   True,
        "candidate_payload": candidate_payload,
        "ssot_payload":      ssot_payload,
        "source": {
            "candidate": "written_deltas",
            "ssot":      "ssot_payload_provider",
        },
    }
    phase2_result = run_with_collapse_gate(phase2_ctx)
    contract = phase2_result.get("contract") or {}
    contract_result = contract.get("contract", "PASS")

    divergence_id = None
    phase3_blocked = False
    if contract_result != "PASS":
        div_result = record_divergence(
            session_number=session_number,
            contract=contract,
        )
        divergence_id = div_result.get("divergence_id")
        phase3_blocked = div_result.get("phase3_blocked", False)

    div_summary = get_divergence_summary(session_number)
    record_session(
        session_number=session_number,
        contract_result=contract_result,
        divergence_summary=div_summary,
    )

    return {
        "success":         True,
        "commit_id":       commit_result["commit_id"],
        "tx_id":           tx_id,
        "delta_count":     len(written_deltas),
        "generated_at":    generated_at,
        "phase2_valid":    phase2_result["phase2_valid"],
        "phase2_contract": contract_result,
        "divergence_id":   divergence_id,
        "phase3_blocked":  phase3_blocked,
    }

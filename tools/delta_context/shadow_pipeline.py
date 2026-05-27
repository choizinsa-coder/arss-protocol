ACTIVE_VERSION = "2.0.0"
VERSION_STATUS = "active"
# tools/delta_context/shadow_pipeline.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Shadow sidecar -- SESSION_CONTEXT.json is still SSOT
# CORE+DELTA is non-canonical shadow structure
# F-A RULE-5 Remediation: Orchestrator/Stage decomposition (EAG S158)

import os
import json
import sys
import re as _re
from datetime import datetime, timezone, timedelta

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


# ---------------------------------------------------------------------------
# Stage 0: PRE_DELTA_IDEMPOTENCY_GATE
# Input : session_number, delta_requests, generated_at
# Output: gate_status, gate_reason, stage0_metadata  (success)
#         success=False contract                      (failure)
# ---------------------------------------------------------------------------
def _run_pre_delta_gate(session_number, delta_requests, generated_at):
    # PRECONDITION: generated_at
    if not isinstance(generated_at, str) or not generated_at:
        return {
            "success": False, "stage": 0,
            "pipeline_stage": "PRECONDITION_GATE",
            "reason": "generated_at missing or empty",
            "commit_id": None, "delta_count": 0, "rollback_status": None,
        }
    try:
        datetime.fromisoformat(generated_at)
    except ValueError:
        return {
            "success": False, "stage": 0,
            "pipeline_stage": "PRECONDITION_GATE",
            "reason": f"generated_at ISO8601 parse failed: {repr(generated_at)}",
            "commit_id": None, "delta_count": 0, "rollback_status": None,
        }

    # PRECONDITION: delta_requests
    if not delta_requests:
        return {
            "success": False, "stage": 0,
            "pipeline_stage": "PRE_CHECK",
            "reason": "delta_requests empty",
            "commit_id": None, "delta_count": 0, "rollback_status": None,
        }

    domains = list({req["domain"] for req in delta_requests})
    stage0_result = classify_stage0(
        session_number=session_number,
        domains=domains,
        delta_log_base=DELTA_LOG_BASE,
        tx_base_path=TX_BASE_PATH,
        commit_base_path=COMMIT_BASE_PATH,
    )
    gate = stage0_result["gate"]

    if gate == "ALLOW_ALREADY_COMPLETED":
        return {
            "success": True,
            "gate_status": "ALLOW_ALREADY_COMPLETED",
            "gate_reason": "ALREADY_COMPLETED",
            "stage0_metadata": stage0_result,
        }
    if gate == "FAIL_CLOSED":
        return {
            "success": False, "stage": 0,
            "pipeline_stage": "PRE_DELTA_IDEMPOTENCY_GATE",
            "reason": stage0_result["reason"],
            "commit_id": None, "delta_count": 0, "rollback_status": None,
            "state": stage0_result.get("state"),
            "hash_check": stage0_result.get("hash_check", {}),
        }

    # gate == "ALLOW_NEW_RUN"
    return {
        "success": True,
        "gate_status": "ALLOW_NEW_RUN",
        "gate_reason": None,
        "stage0_metadata": stage0_result,
    }


# ---------------------------------------------------------------------------
# Stage 1+2: DELTA_WRITE + INDEX_UPDATE
# Input : session_number, delta_requests, generated_at, stage0_metadata
# Output: delta_count, delta_results, index_update_results  (success)
#         success=False contract                             (failure)
# ---------------------------------------------------------------------------
def _execute_delta_write_pipeline(session_number, delta_requests, generated_at, stage0_metadata):
    written_deltas = []
    index_results  = []

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
                "success": False, "stage": "1_2",
                "reason": f"delta_writer failed: {write_result.get('reason')}",
                "commit_id": None, "delta_count": len(written_deltas), "rollback_status": None,
                "failed_req": req,
            }
        delta      = write_result["delta"]
        delta_path = write_result["path"]

        index_result = update_index(delta, delta_path)
        if not index_result["success"]:
            return {
                "success": False, "stage": "1_2",
                "reason": index_result["reason"],
                "commit_id": None, "delta_count": len(written_deltas), "rollback_status": None,
                "quarantine": index_result.get("quarantine"),
                "message": index_result.get("message"),
            }
        written_deltas.append(delta)
        index_results.append(index_result)

    return {
        "success": True,
        "delta_count": len(written_deltas),
        "delta_results": written_deltas,
        "index_update_results": index_results,
    }


# ---------------------------------------------------------------------------
# Stage 3~6: TX_CREATE + COMMIT_CREATE + PRE/POST_COMMIT_VERIFY
# Input : session_number, delta_count, delta_results, index_update_results, generated_at
# Output: tx_id, commit_id, pre_commit_verified, post_commit_verified  (success)
#         success=False contract                                        (failure)
# ---------------------------------------------------------------------------
def _execute_transaction_commit_flow(
    session_number, delta_count, delta_results, index_update_results, generated_at
):
    committed_by = "caddy"

    # Stage 3: TX_CREATE
    tx_result = mutate_create_transaction(
        session_number=session_number,
        committed_by=committed_by,
        included_deltas=delta_results,
        generated_at=generated_at,
    )
    if not tx_result["success"]:
        return {
            "success": False, "stage": "3_6",
            "reason": f"TX create failed: {tx_result.get('reason')}",
            "commit_id": None, "delta_count": delta_count, "rollback_status": None,
        }
    tx_id            = tx_result["tx_id"]
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
        mark_incomplete(session_number, f"COMMIT create failed: {commit_result.get('reason')}")
        return {
            "success": False, "stage": "3_6",
            "reason": f"COMMIT create failed: {commit_result.get('reason')}",
            "commit_id": None, "delta_count": delta_count, "rollback_status": None,
        }
    commit_id = commit_result["commit_id"]

    # Stage 5: PRE_COMMIT_GATE
    pre_commit_check = verify_commit_exists(session_number)
    if pre_commit_check.get("hard_stop"):
        mark_incomplete(session_number, pre_commit_check["reason"])
        return {
            "success": False, "stage": "3_6",
            "reason": pre_commit_check["reason"],
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
        }

    # Stage 6: POST_COMMIT_VERIFY
    final_check = verify_commit_exists(session_number)
    if not final_check["exists"]:
        return {
            "success": False, "stage": "3_6",
            "reason": "COMMIT existence check failed after creation",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
        }

    return {
        "success": True,
        "tx_id": tx_id,
        "commit_id": commit_id,
        "pre_commit_verified": True,
        "post_commit_verified": True,
    }


# ---------------------------------------------------------------------------
# Stage 6.5: COMMIT_METADATA_REGISTRATION  [HIGH RISK — atomic pair]
# Input : tx_id, commit_id, delta_count, generated_at
# Output: registration_status, rollback_status, metadata_result  (success)
#         success=False contract + rollback_status               (failure)
# ---------------------------------------------------------------------------
def _rollback_stage65(tx_file_path, tx_snapshot, index_file_path, index_snapshot):
    """Restore TX and INDEX to pre-mutation snapshots. Returns rollback_status."""
    try:
        with open(index_file_path, "w", encoding="utf-8") as f:
            json.dump(
                index_snapshot, f,
                sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2,
            )
        with open(tx_file_path, "w", encoding="utf-8") as f:
            json.dump(
                tx_snapshot, f,
                sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2,
            )
        return "RESTORED"
    except Exception:
        return "ROLLBACK_FAILED"


def _register_commit_metadata(tx_id, commit_id, delta_count, generated_at):
    tx_file_path    = os.path.join(TX_BASE_PATH, f"{tx_id}.json")
    index_file_path = os.path.join(DELTA_LOG_BASE, "INDEX.json")

    # --- Snapshot (pre-mutation state) ---
    try:
        with open(tx_file_path, "r", encoding="utf-8") as f:
            tx_snapshot = json.load(f)
    except Exception as e:
        return {
            "success": False, "stage": "6_5",
            "reason": f"TX snapshot failed: {e}",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
        }
    try:
        with open(index_file_path, "r", encoding="utf-8") as f:
            index_snapshot = json.load(f)
    except Exception as e:
        return {
            "success": False, "stage": "6_5",
            "reason": f"INDEX snapshot failed: {e}",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
        }

    # --- TX status update (first mutation) ---
    try:
        tx_data = json.loads(json.dumps(tx_snapshot))
        tx_data["status"] = "COMMITTED"
        with open(tx_file_path, "w", encoding="utf-8") as f:
            json.dump(
                tx_data, f,
                sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2,
            )
    except Exception as e:
        # TX write failed — no partial mutation; snapshot still intact
        return {
            "success": False, "stage": "6_5",
            "reason": "TX_COMMIT_UPDATE_FAILED",
            "commit_id": commit_id, "delta_count": delta_count,
            "rollback_status": None,
            "error": str(e),
        }

    # --- INDEX tx registration (second mutation) ---
    try:
        index_data = json.loads(json.dumps(index_snapshot))
        if "transactions" not in index_data:
            index_data["transactions"] = []
        if not any(t.get("tx_id") == tx_id for t in index_data["transactions"]):
            index_data["transactions"].append({"tx_id": tx_id, "status": "COMMITTED"})
        with open(index_file_path, "w", encoding="utf-8") as f:
            json.dump(
                index_data, f,
                sort_keys=True, ensure_ascii=True, separators=(",", ":"), indent=2,
            )
    except Exception as e:
        # INDEX write failed — TX already mutated; attempt full rollback
        rollback_status = _rollback_stage65(
            tx_file_path=tx_file_path,
            tx_snapshot=tx_snapshot,
            index_file_path=index_file_path,
            index_snapshot=index_snapshot,
        )
        result = {
            "success": False, "stage": "6_5",
            "reason": "INDEX_TRANSACTION_REGISTER_FAILED",
            "commit_id": commit_id, "delta_count": delta_count,
            "rollback_status": rollback_status,
            "error": str(e),
        }
        if rollback_status == "ROLLBACK_FAILED":
            result["state_risk"] = "UNSAFE_PARTIAL_MUTATION"
        return result

    return {
        "success": True,
        "registration_status": "COMMITTED",
        "rollback_status": None,
        "metadata_result": {"tx_id": tx_id, "commit_id": commit_id},
    }


# ---------------------------------------------------------------------------
# Stage 7: PHASE2_VALIDATION
# Input : session_number, commit_id, delta_count, delta_results, ssot_payload, generated_at
# Output: phase2_status, readiness_status, divergence_status  (success)
#         success=False contract                               (failure)
# ---------------------------------------------------------------------------
def _run_phase2_validation(
    session_number, commit_id, delta_count, delta_results, ssot_payload, generated_at
):
    _ISO8601_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    # ssot_payload structural validation
    if ssot_payload is None or not isinstance(ssot_payload, dict):
        return {
            "success": False, "stage": 7,
            "reason": "SSOT_PAYLOAD_PROVIDER_INVALID_RETURN",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
        }
    stl = ssot_payload.get("session_time_lock")
    if stl is None or not isinstance(stl, dict):
        return {
            "success": False, "stage": 7,
            "reason": "SSOT_PAYLOAD_FIELD_MISSING",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
            "missing": "session_time_lock",
        }
    for _field in ("source", "timezone", "generated_at", "observed_at"):
        if not stl.get(_field) or not isinstance(stl[_field], str):
            return {
                "success": False, "stage": 7,
                "reason": "SSOT_PAYLOAD_FIELD_MISSING",
                "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
                "missing": f"session_time_lock.{_field}",
            }
    for _ts_field in ("generated_at", "observed_at"):
        if not _ISO8601_RE.match(stl[_ts_field]):
            return {
                "success": False, "stage": 7,
                "reason": "SSOT_PAYLOAD_TIMESTAMP_INVALID",
                "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
                "field": f"session_time_lock.{_ts_field}",
            }
    if not isinstance(stl.get("epoch_ms"), int):
        return {
            "success": False, "stage": 7,
            "reason": "SSOT_PAYLOAD_FIELD_TYPE_INVALID",
            "commit_id": commit_id, "delta_count": delta_count, "rollback_status": None,
            "field": "session_time_lock.epoch_ms",
        }

    candidate_payload = {d["target_key"]: d["new_value"] for d in delta_results}
    candidate_payload["generated_at"] = generated_at

    phase2_ctx = {
        "shadow_mode":       True,
        "index_loaded":      True,
        "delta_count":       delta_count,
        "session_number":    session_number,
        "phase1_complete":   True,
        "candidate_payload": candidate_payload,
        "ssot_payload":      ssot_payload,
        "source": {
            "candidate": "written_deltas",
            "ssot":      "ssot_payload_provider",
        },
    }
    phase2_result  = run_with_collapse_gate(phase2_ctx)
    contract       = phase2_result.get("contract") or {}
    contract_result = contract.get("contract", "PASS")

    divergence_id  = None
    phase3_blocked = False
    if contract_result != "PASS":
        div_result     = record_divergence(session_number=session_number, contract=contract)
        divergence_id  = div_result.get("divergence_id")
        phase3_blocked = div_result.get("phase3_blocked", False)

    div_summary = get_divergence_summary(session_number)
    record_session(
        session_number=session_number,
        contract_result=contract_result,
        divergence_summary=div_summary,
    )

    return {
        "success": True,
        "phase2_status":    phase2_result,
        "readiness_status": contract_result,
        "divergence_status": {
            "divergence_id": divergence_id,
            "phase3_blocked": phase3_blocked,
            "div_summary":   div_summary,
        },
        "phase2_valid":    phase2_result["phase2_valid"],
        "phase2_contract": contract_result,
        "divergence_id":   divergence_id,
        "phase3_blocked":  phase3_blocked,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
def run_shadow_pipeline(
    session_number,
    delta_requests,
    generated_at,
    ssot_payload_provider=None,
):
    """
    Shadow Mode session close pipeline.

    Returns:
        {"success": True, "commit_id": str, "delta_count": int, ...}
        {"success": False, "hard_stop": True, "reason": str, "stage": str}
    """
    # Stage 0
    gate_result = _run_pre_delta_gate(session_number, delta_requests, generated_at)
    if not gate_result["success"]:
        _gate_fail = {
            "success":   False,
            "hard_stop": True,
            "reason":    gate_result["reason"],
            "stage":     gate_result.get("pipeline_stage", "PRE_DELTA_IDEMPOTENCY_GATE"),
        }
        if "state" in gate_result:
            _gate_fail["state"] = gate_result["state"]
        if "hash_check" in gate_result:
            _gate_fail["hash_check"] = gate_result["hash_check"]
        return _gate_fail
    if gate_result["gate_status"] == "ALLOW_ALREADY_COMPLETED":
        return {
            "success": True,
            "reason":  "ALREADY_COMPLETED",
            "stage":   "PRE_DELTA_IDEMPOTENCY_GATE",
        }

    # Stage 1+2
    write_result = _execute_delta_write_pipeline(
        session_number=session_number,
        delta_requests=delta_requests,
        generated_at=generated_at,
        stage0_metadata=gate_result["stage0_metadata"],
    )
    if not write_result["success"]:
        return {
            "success":    False,
            "hard_stop":  True,
            "reason":     write_result["reason"],
            "stage":      str(write_result["stage"]),
            "failed_req": write_result.get("failed_req"),
            "quarantine": write_result.get("quarantine"),
            "message":    write_result.get("message"),
        }
    written_deltas = write_result["delta_results"]
    delta_count    = write_result["delta_count"]

    # Stage 3~6
    tx_result = _execute_transaction_commit_flow(
        session_number=session_number,
        delta_count=delta_count,
        delta_results=written_deltas,
        index_update_results=write_result["index_update_results"],
        generated_at=generated_at,
    )
    if not tx_result["success"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    tx_result["reason"],
            "stage":     str(tx_result["stage"]),
        }
    tx_id     = tx_result["tx_id"]
    commit_id = tx_result["commit_id"]

    # Stage 6.5
    meta_result = _register_commit_metadata(
        tx_id=tx_id,
        commit_id=commit_id,
        delta_count=delta_count,
        generated_at=generated_at,
    )
    if not meta_result["success"]:
        result = {
            "success":         False,
            "hard_stop":       True,
            "reason":          meta_result["reason"],
            "stage":           "6.5",
            "commit_id":       meta_result.get("commit_id"),
            "delta_count":     meta_result.get("delta_count"),
            "rollback_status": meta_result.get("rollback_status"),
        }
        if meta_result.get("rollback_status") == "ROLLBACK_FAILED":
            result["state_risk"] = "UNSAFE_PARTIAL_MUTATION"
        return result

    # Stage 7: ssot_payload 준비
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

    phase2_result = _run_phase2_validation(
        session_number=session_number,
        commit_id=commit_id,
        delta_count=delta_count,
        delta_results=written_deltas,
        ssot_payload=ssot_payload,
        generated_at=generated_at,
    )
    if not phase2_result["success"]:
        _p2_fail = {
            "success":   False,
            "hard_stop": True,
            "reason":    phase2_result["reason"],
            "stage":     str(phase2_result["stage"]),
        }
        if "missing" in phase2_result:
            _p2_fail["missing"] = phase2_result["missing"]
        if "field" in phase2_result:
            _p2_fail["field"] = phase2_result["field"]
        return _p2_fail

    return {
        "success":         True,
        "commit_id":       commit_id,
        "tx_id":           tx_id,
        "delta_count":     delta_count,
        "generated_at":    generated_at,
        "phase2_valid":    phase2_result["phase2_valid"],
        "phase2_contract": phase2_result["phase2_contract"],
        "divergence_id":   phase2_result["divergence_id"],
        "phase3_blocked":  phase2_result["phase3_blocked"],
    }

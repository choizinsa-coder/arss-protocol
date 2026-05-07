ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/stage0_idempotency_classifier.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Stage 0 PRE_DELTA_IDEMPOTENCY_GATE — classifier/validator module
# Separated from shadow_pipeline.py per PT-S73-003 FINAL DESIGN + ADDENDUM
#
# State Model:
#   COMPLETED    : DELTA valid + COMMIT valid
#   INVALID      : DELTA valid + COMMIT missing
#   PARTIAL_STATE: DELTA missing + COMMIT valid
#   NOT_STARTED  : DELTA missing + COMMIT missing
#   UNKNOWN      : unreadable / zero-byte / malformed / required field missing / exception
#
# Judgment order (fixed):
#   detect -> basic_integrity_check -> optional_hash_check
#   -> classify -> validate -> gate decision
#
# Race Condition Defense scope (IMPORTANT):
#   _LOCKED_FAIL_SESSIONS is an in-process memory set.
#   Defense is limited to: same-process / same-pipeline-invocation re-escalation prevention.
#   This set is cleared on process restart.
#   Persistent cross-process lock is NOT implemented in this version.
#   If persistent lock is required, a separate design change must be filed.
#
# Hash verification method (IMPORTANT):
#   optional_hash_check compares expected_hash against hash-related fields
#   INSIDE the target file ("hash", "content_hash", "delta_hash").
#   It does NOT compute a content hash of the file bytes.
#   Limitation: if the file contains no hash field, result is SKIPPED
#   regardless of expected_hash. This is intentional per design addendum --
#   absence of a hash field in the file means no verifiable anchor is available.

import os
import json

# ---------------------------------------------------------------------------
# Race Condition Defense
# In-process memory only. Scope: same-process / same-pipeline-invocation.
# Does NOT persist across process restarts.
# ---------------------------------------------------------------------------
_LOCKED_FAIL_SESSIONS: set = set()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_file_integrity(path: str, required_fields: list) -> dict:
    """
    single file basic_integrity_check.

    Checks: existence, zero-byte, readability, JSON format, required fields.

    Returns:
        {"valid": bool, "reason": str | None}
    """
    if not os.path.exists(path):
        return {"valid": False, "reason": "FILE_MISSING"}

    try:
        size = os.path.getsize(path)
    except OSError:
        return {"valid": False, "reason": "UNREADABLE"}

    if size == 0:
        return {"valid": False, "reason": "ZERO_BYTE"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return {"valid": False, "reason": "UNREADABLE"}

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"valid": False, "reason": "MALFORMED"}

    if required_fields:
        for field in required_fields:
            if field not in data:
                return {"valid": False, "reason": f"MISSING_REQUIRED_FIELD:{field}"}

    return {"valid": True, "reason": None}


def _optional_hash_check(path: str, expected_hash) -> dict:
    """
    optional_hash_check -- file-internal hash field comparison.

    Rules:
      - expected_hash is None  -> SKIPPED (no reference provided)
      - expected_hash provided, file has hash field -> compare
      - expected_hash provided, file has NO hash field -> SKIPPED
        (no verifiable anchor; treated same as no reference)
      - mismatch -> MISMATCH -> caller triggers UNKNOWN + FAIL-CLOSED

    NOTE: Does NOT hash file bytes. Compares expected_hash against
    "hash" / "content_hash" / "delta_hash" fields found inside the file.

    Returns:
        {"result": "PASS" | "MISMATCH" | "SKIPPED", "detail": str | None}
    """
    if expected_hash is None:
        return {"result": "SKIPPED", "detail": "no_reference_provided"}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"result": "MISMATCH", "detail": "unreadable_for_hash_check"}

    actual_hash = (
        data.get("hash")
        or data.get("content_hash")
        or data.get("delta_hash")
    )

    if actual_hash is None:
        return {"result": "SKIPPED", "detail": "hash_field_not_present_in_file"}

    if actual_hash != expected_hash:
        return {
            "result": "MISMATCH",
            "detail": f"expected={expected_hash} actual={actual_hash}",
        }

    return {"result": "PASS", "detail": None}


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------
DELTA_REQUIRED_FIELDS  = ["session_number", "domain"]
COMMIT_REQUIRED_FIELDS = ["session_number"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_stage0(
    session_number: int,
    domains: list,
    delta_log_base: str,
    tx_base_path: str,
    commit_base_path: str,
    expected_delta_hash=None,
    expected_commit_hash=None,
) -> dict:
    """
    Stage 0 PRE_DELTA_IDEMPOTENCY_GATE classification.

    Fixed judgment order:
      detect -> basic_integrity_check -> optional_hash_check
      -> classify -> validate -> gate decision

    Gate values:
      "ALLOW_ALREADY_COMPLETED" : state=COMPLETED, block re-run
      "ALLOW_NEW_RUN"           : state=NOT_STARTED, allow new run
      "FAIL_CLOSED"             : state=INVALID/PARTIAL_STATE/UNKNOWN, block execution

    Race Condition Defense:
      Once FAIL_CLOSED is returned for a session_number within the same process,
      that session is locked in _LOCKED_FAIL_SESSIONS.
      Re-calls in the same process will return FAIL_CLOSED regardless of file state.
      Lock clears on process restart (in-process memory only).

    Returns:
        {
            "state":      str,
            "gate":       str,
            "reason":     str,
            "hash_check": {"delta": {...}, "commit": {...}},
            "stage":      "PRE_DELTA_IDEMPOTENCY_GATE",
        }
    """
    stage = "PRE_DELTA_IDEMPOTENCY_GATE"

    # Race Condition Defense
    if session_number in _LOCKED_FAIL_SESSIONS:
        return {
            "state":      "UNKNOWN",
            "gate":       "FAIL_CLOSED",
            "reason":     "RACE_CONDITION_LOCKED",
            "hash_check": {},
            "stage":      stage,
        }

    # ------------------------------------------------------------------
    # STEP 1: detect
    # ------------------------------------------------------------------
    delta_dir_exists = any(
        os.path.isdir(os.path.join(delta_log_base, domain, f"S{session_number}"))
        for domain in domains
    )
    tx_path     = os.path.join(tx_base_path,     f"TX-S{session_number}.json")
    commit_path = os.path.join(commit_base_path, f"COMMIT-S{session_number}.json")

    tx_exists     = os.path.exists(tx_path)
    commit_exists = os.path.exists(commit_path)

    hash_check_result = {}

    # ------------------------------------------------------------------
    # STEP 2: basic_integrity_check
    # ------------------------------------------------------------------
    delta_integrity  = {"valid": True, "reason": None}
    commit_integrity = {"valid": True, "reason": None}

    try:
        if delta_dir_exists and not tx_exists:
            # delta directory exists but TX file missing -> integrity fail
            delta_integrity = {"valid": False, "reason": "TX_FILE_MISSING"}
        elif delta_dir_exists and tx_exists:
            delta_integrity = _check_file_integrity(tx_path, DELTA_REQUIRED_FIELDS)

        if commit_exists:
            commit_integrity = _check_file_integrity(commit_path, COMMIT_REQUIRED_FIELDS)

    except Exception as e:
        _LOCKED_FAIL_SESSIONS.add(session_number)
        return {
            "state":      "UNKNOWN",
            "gate":       "FAIL_CLOSED",
            "reason":     f"INTEGRITY_CHECK_EXCEPTION:{e}",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    if delta_dir_exists and not delta_integrity["valid"]:
        _LOCKED_FAIL_SESSIONS.add(session_number)
        return {
            "state":      "UNKNOWN",
            "gate":       "FAIL_CLOSED",
            "reason":     f"DELTA_INTEGRITY_FAIL:{delta_integrity['reason']}",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    if commit_exists and not commit_integrity["valid"]:
        _LOCKED_FAIL_SESSIONS.add(session_number)
        return {
            "state":      "UNKNOWN",
            "gate":       "FAIL_CLOSED",
            "reason":     f"COMMIT_INTEGRITY_FAIL:{commit_integrity['reason']}",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    # ------------------------------------------------------------------
    # STEP 3: optional_hash_check
    # ------------------------------------------------------------------
    try:
        delta_hash_result  = {"result": "SKIPPED", "detail": "delta_not_present"}
        commit_hash_result = {"result": "SKIPPED", "detail": "commit_not_present"}

        delta_file_present = delta_dir_exists and tx_exists

        if delta_file_present and delta_integrity["valid"]:
            delta_hash_result = _optional_hash_check(tx_path, expected_delta_hash)

        if commit_exists and commit_integrity["valid"]:
            commit_hash_result = _optional_hash_check(commit_path, expected_commit_hash)

        hash_check_result = {
            "delta":  delta_hash_result,
            "commit": commit_hash_result,
        }

        if delta_hash_result["result"] == "MISMATCH":
            _LOCKED_FAIL_SESSIONS.add(session_number)
            return {
                "state":      "UNKNOWN",
                "gate":       "FAIL_CLOSED",
                "reason":     f"DELTA_HASH_MISMATCH:{delta_hash_result['detail']}",
                "hash_check": hash_check_result,
                "stage":      stage,
            }

        if commit_hash_result["result"] == "MISMATCH":
            _LOCKED_FAIL_SESSIONS.add(session_number)
            return {
                "state":      "UNKNOWN",
                "gate":       "FAIL_CLOSED",
                "reason":     f"COMMIT_HASH_MISMATCH:{commit_hash_result['detail']}",
                "hash_check": hash_check_result,
                "stage":      stage,
            }

    except Exception as e:
        _LOCKED_FAIL_SESSIONS.add(session_number)
        return {
            "state":      "UNKNOWN",
            "gate":       "FAIL_CLOSED",
            "reason":     f"HASH_CHECK_EXCEPTION:{e}",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    # ------------------------------------------------------------------
    # STEP 4: classify
    # ------------------------------------------------------------------
    delta_valid  = delta_dir_exists and tx_exists and delta_integrity["valid"]
    commit_valid = commit_exists                   and commit_integrity["valid"]

    if delta_valid and commit_valid:
        state = "COMPLETED"
    elif delta_valid and not commit_valid:
        state = "INVALID"
    elif not delta_valid and commit_valid:
        state = "PARTIAL_STATE"
    elif not delta_valid and not commit_valid:
        state = "NOT_STARTED"
    else:
        state = "UNKNOWN"

    # ------------------------------------------------------------------
    # STEP 5: validate + gate decision
    # ------------------------------------------------------------------
    if state == "COMPLETED":
        return {
            "state":      "COMPLETED",
            "gate":       "ALLOW_ALREADY_COMPLETED",
            "reason":     "DELTA_AND_COMMIT_VALID",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    if state == "NOT_STARTED":
        return {
            "state":      "NOT_STARTED",
            "gate":       "ALLOW_NEW_RUN",
            "reason":     "NO_DELTA_NO_COMMIT",
            "hash_check": hash_check_result,
            "stage":      stage,
        }

    # INVALID / PARTIAL_STATE / UNKNOWN -> FAIL-CLOSED
    _LOCKED_FAIL_SESSIONS.add(session_number)
    return {
        "state":      state,
        "gate":       "FAIL_CLOSED",
        "reason":     f"STATE_{state}_DETECTED",
        "hash_check": hash_check_result,
        "stage":      stage,
    }

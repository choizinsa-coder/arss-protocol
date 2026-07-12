#!/usr/bin/env python3
"""
record_eag_gates.py v1.0.0
S395 Decision Ledger wiring -- record this session's EAG gates as DC-3 entries.
EAG: EAG-S395-DECISION-LEDGER-WIRING-IMPL-001

Design: Domi v3 + Caddy IMPLEMENTABLE corrections.
  - read (dedup) and write both key off area_11.LOG_PATH
    -> a single monkeypatch of dl.LOG_PATH isolates tests from the production ledger.
  - missing / empty input key -> WARN on stdout (no silent miss).
  - stdout: one machine-readable line, captured by the close wrapper into
    session_close_result.json (the wrapper stores the generator's full stdout).
  - the EAG-ID validator is INJECTED by the caller (session_close_generator
    ._validate_approval_id) to reuse the proven contract without a circular import.
"""
import json
import sys
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.governance import area_11_decision_ledger as dl

STDOUT_PREFIX = "[EAG-LEDGER]"


def _load_recorded_eag_ids() -> set:
    """Existing EAG ids in the ledger. Resolved from dl.LOG_PATH at call time."""
    ids = set()
    path = Path(dl.LOG_PATH)
    if not path.exists():
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            eid = entry.get("eag")
            if eid:
                ids.add(eid)
    return ids


def _emit(result: dict) -> None:
    print(STDOUT_PREFIX + " " + json.dumps(result, ensure_ascii=False))


def record_eag_gates(session_id, eag_gates, validator) -> dict:
    """Record each EAG gate string of the session as a DC-3 decision.

    session_id : int   -- generator's n
    eag_gates  : list[str] | None -- delta caddy_governance_record.eag_gates_this_session
    validator  : callable(str) -> bool -- EAG ID format validator (injected)

    Returns {session, recorded, skipped, errors(int), error_detail(list), warn(str)}.
    Never raises: CLOSE must not fail because of an audit record.
    """
    result = {
        "session": session_id,
        "recorded": 0,
        "skipped": 0,
        "errors": 0,
        "error_detail": [],
        "warn": "",
    }

    if not eag_gates:
        result["warn"] = "eag_gates_this_session missing or empty"
        _emit(result)
        return result

    try:
        seen = _load_recorded_eag_ids()
    except Exception as exc:
        result["errors"] += 1
        result["error_detail"].append("ledger_read_failed: " + str(exc))
        _emit(result)
        return result

    for gate in eag_gates:
        raw = str(gate).strip()
        parts = raw.split()
        eag_id = parts[0] if parts else ""
        if not validator(eag_id):
            result["errors"] += 1
            result["error_detail"].append("invalid_eag_id: " + raw[:80])
            continue
        if eag_id in seen:
            result["skipped"] += 1
            continue
        try:
            dl.record_decision(
                dc=dl.DecisionClass.DC3,
                subject="S" + str(session_id) + " EAG gate: " + eag_id,
                rationale=raw,
                eag=eag_id,
                actor="beo",
            )
        except Exception as exc:
            result["errors"] += 1
            result["error_detail"].append(eag_id + ": " + str(exc))
            continue
        seen.add(eag_id)
        result["recorded"] += 1

    _emit(result)
    return result

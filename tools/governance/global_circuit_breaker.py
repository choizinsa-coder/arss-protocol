# global_circuit_breaker.py -- AIBA Global Circuit Breaker (GCB)
# EAG-S335-GCB-001
# System-wide emergency stop above per-agent circuit breakers.
# Scope: autonomous components only (domi/jeni runtimes, WF-05 loop).
# Trip: no-progress repetition + cascading failure without recovery.
# Recovery: EAG only. No auto-resume.
import fcntl
import json
import os
import time
from datetime import datetime, timezone

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
GCB_STATE_PATH = os.path.join(ARSS_ROOT, "runtime/governance/gcb/global_circuit_breaker_state.json")
GCB_SCHEMA = "GCB_STATE_v1"

NO_PROGRESS_TRIP_N = int(os.environ.get("AIBA_GCB_NO_PROGRESS_N", "5"))
CASCADE_WINDOW_SEC = int(os.environ.get("AIBA_GCB_CASCADE_WINDOW", "60"))
CASCADE_MIN_COMPONENTS = int(os.environ.get("AIBA_GCB_CASCADE_MIN", "2"))

STATE_CLOSED = "CLOSED"
STATE_TRIPPED = "TRIPPED"


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _default_state():
    return {
        "schema": GCB_SCHEMA,
        "state": STATE_CLOSED,
        "triggered_at": None,
        "triggered_by": None,
        "reason": None,
        "no_progress": {},
        "cascade_events": [],
        "updated_at": _utc_now_iso(),
    }


def _read_state():
    try:
        with open(GCB_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or data.get("schema") != GCB_SCHEMA:
            return _default_state()
        return data
    except Exception:
        return _default_state()


def _atomic_write(state):
    os.makedirs(os.path.dirname(GCB_STATE_PATH), exist_ok=True)
    state["updated_at"] = _utc_now_iso()
    tmp = GCB_STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, GCB_STATE_PATH)


def _with_lock(fn):
    os.makedirs(os.path.dirname(GCB_STATE_PATH), exist_ok=True)
    lock_path = GCB_STATE_PATH + ".lock"
    with open(lock_path, "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def is_tripped():
    return _read_state().get("state") == STATE_TRIPPED


def gcb_check():
    return is_tripped()


def get_state():
    return _read_state()


def report_no_progress(component):
    def _op():
        state = _read_state()
        if state.get("state") == STATE_TRIPPED:
            return state
        counts = dict(state.get("no_progress", {}))
        counts[component] = int(counts.get(component, 0)) + 1
        state["no_progress"] = counts
        if counts[component] >= NO_PROGRESS_TRIP_N:
            state["state"] = STATE_TRIPPED
            state["triggered_at"] = _utc_now_iso()
            state["triggered_by"] = component
            state["reason"] = "NO_PROGRESS_REPETITION"
        _atomic_write(state)
        return state
    return _with_lock(_op)


def report_progress(component):
    def _op():
        state = _read_state()
        if state.get("state") == STATE_TRIPPED:
            return state
        counts = dict(state.get("no_progress", {}))
        if counts.get(component):
            counts[component] = 0
            state["no_progress"] = counts
            _atomic_write(state)
        return state
    return _with_lock(_op)


def report_failure(component):
    def _op():
        state = _read_state()
        if state.get("state") == STATE_TRIPPED:
            return state
        now = time.time()
        events = [e for e in state.get("cascade_events", []) if now - e[1] <= CASCADE_WINDOW_SEC]
        events.append([component, now])
        state["cascade_events"] = events
        distinct = set(e[0] for e in events)
        if len(distinct) >= CASCADE_MIN_COMPONENTS:
            state["state"] = STATE_TRIPPED
            state["triggered_at"] = _utc_now_iso()
            state["triggered_by"] = component
            state["reason"] = "CASCADING_FAILURE_NO_RECOVERY"
        _atomic_write(state)
        return state
    return _with_lock(_op)


def gcb_reset(eag_id):
    if not eag_id or not str(eag_id).startswith("EAG-"):
        raise ValueError("GCB reset requires a valid EAG id")
    def _op():
        state = _default_state()
        state["reset_by"] = eag_id
        state["reset_at"] = _utc_now_iso()
        _atomic_write(state)
        return state
    return _with_lock(_op)

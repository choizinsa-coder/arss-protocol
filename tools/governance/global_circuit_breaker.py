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
import urllib.request
from datetime import datetime, timezone

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
GCB_STATE_PATH = os.environ.get("AIBA_GCB_STATE_PATH") or os.path.join(  # EAG-S401
    ARSS_ROOT, "runtime/governance/gcb/global_circuit_breaker_state.json")
GCB_SCHEMA = "GCB_STATE_v1"

NO_PROGRESS_TRIP_N = int(os.environ.get("AIBA_GCB_NO_PROGRESS_N", "5"))
CASCADE_WINDOW_SEC = int(os.environ.get("AIBA_GCB_CASCADE_WINDOW", "60"))
CASCADE_MIN_COMPONENTS = int(os.environ.get("AIBA_GCB_CASCADE_MIN", "2"))
CONSECUTIVE_FAIL_TRIP_N = int(os.environ.get("AIBA_GCB_CONSEC_N", "3"))
GCB_SECRET_PATH = os.path.join(ARSS_ROOT, "runtime/governance/gcb/.gcb_secret")
GUARDIAN_VETO_URL = "http://127.0.0.1:8450/veto"

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
        "consecutive_failures": {},
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
            return state, False
        counts = dict(state.get("no_progress", {}))
        counts[component] = int(counts.get(component, 0)) + 1
        state["no_progress"] = counts
        tripped = False
        if counts[component] >= NO_PROGRESS_TRIP_N:
            state["state"] = STATE_TRIPPED
            state["triggered_at"] = _utc_now_iso()
            state["triggered_by"] = component
            state["reason"] = "NO_PROGRESS_REPETITION"
            tripped = True
        _atomic_write(state)
        return state, tripped
    state, tripped = _with_lock(_op)
    if tripped:
        _send_guardian_pause(component, "NO_PROGRESS_REPETITION")
    return state


def report_progress(component):
    def _op():
        state = _read_state()
        if state.get("state") == STATE_TRIPPED:
            return state
        changed = False
        counts = dict(state.get("no_progress", {}))
        if counts.get(component):
            counts[component] = 0
            state["no_progress"] = counts
            changed = True
        cf = dict(state.get("consecutive_failures", {}))
        if cf.get(component):
            cf[component] = 0
            state["consecutive_failures"] = cf
            changed = True
        if changed:
            _atomic_write(state)
        return state
    return _with_lock(_op)


def report_failure(component):
    def _op():
        state = _read_state()
        if state.get("state") == STATE_TRIPPED:
            return state, None
        now = time.time()
        events = [e for e in state.get("cascade_events", []) if now - e[1] <= CASCADE_WINDOW_SEC]
        events.append([component, now])
        state["cascade_events"] = events
        cf = dict(state.get("consecutive_failures", {}))
        cf[component] = int(cf.get(component, 0)) + 1
        state["consecutive_failures"] = cf
        distinct = set(e[0] for e in events)
        trip_reason = None
        if len(distinct) >= CASCADE_MIN_COMPONENTS:
            trip_reason = "CASCADING_FAILURE_NO_RECOVERY"
        elif cf[component] >= CONSECUTIVE_FAIL_TRIP_N:
            trip_reason = "CONSECUTIVE_FAILURE"
        if trip_reason:
            state["state"] = STATE_TRIPPED
            state["triggered_at"] = _utc_now_iso()
            state["triggered_by"] = component
            state["reason"] = trip_reason
            state["consecutive_failures"] = {}
        _atomic_write(state)
        return state, trip_reason
    state, trip_reason = _with_lock(_op)
    if trip_reason:
        _send_guardian_pause(component, trip_reason)
    return state


def _send_guardian_pause(component, reason):
    try:
        with open(GCB_SECRET_PATH, encoding="utf-8") as f:
            secret = f.read().strip()
    except Exception:
        return
    if not secret:
        return
    payload = json.dumps({"issued_by": "SYSTEM", "reason": "GCB_TRIP:" + str(reason) + ":" + str(component)}).encode("utf-8")
    req = urllib.request.Request(GUARDIAN_VETO_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-AIBA-Secret", secret)
    try:
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


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

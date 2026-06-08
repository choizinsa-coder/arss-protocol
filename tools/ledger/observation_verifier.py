"""
observation_verifier.py
AIBA Independent Observation Verifier — EAG-S208-WORM-002
EAG-2: audit-only 모드
"""
from __future__ import annotations
import json, os, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
OBSERVATION_DIR = Path(ARSS_ROOT) / "observation"
OBS_LOG_PATH   = OBSERVATION_DIR / "observation_log.jsonl"
OBS_ALERT_PATH = OBSERVATION_DIR / "observation_alerts.jsonl"
BATCH_INTERVAL_SECONDS = 300
KST = timezone(timedelta(hours=9))

def _now_iso(): return datetime.now(KST).isoformat()

def _append_obs(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

def observe_append(actor, seq, entry_hash, session):
    issues = []
    if not (isinstance(entry_hash, str) and len(entry_hash) == 64
            and all(c in "0123456789abcdef" for c in entry_hash)):
        issues.append(f"INVALID_ENTRY_HASH_FORMAT: {entry_hash!r}")
    if not isinstance(seq, int) or seq < 0:
        issues.append(f"INVALID_SEQ: {seq!r}")
    status = "ALERT" if issues else "PASS"
    _append_obs(OBS_LOG_PATH, {"obs_id": f"OBS-RT-{actor}-{seq}", "obs_type": "REALTIME_APPEND",
                                "actor": actor, "seq": seq, "entry_hash": entry_hash,
                                "session": session, "status": status,
                                "issues": issues, "timestamp": _now_iso()})
    if issues:
        _append_obs(OBS_ALERT_PATH, {"alert_type": "REALTIME_SCHEMA_VIOLATION",
                                      "actor": actor, "seq": seq,
                                      "issues": issues, "timestamp": _now_iso()})
    return {"status": status, "issues": issues}

def run_batch_verification():
    import sys as _sys
    lp = "/opt/arss/engine/arss-protocol/tools/ledger"
    if lp not in _sys.path: _sys.path.insert(0, lp)
    from ledger_verifier import verify_all_chains, verify_manifest
    chain_result = verify_all_chains()
    manifest_result = verify_manifest()
    all_pass = (chain_result.get("status") == "PASS"
                and manifest_result.get("status") == "PASS")
    status = "PASS" if all_pass else "ALERT"
    _append_obs(OBS_LOG_PATH, {"obs_id": f"OBS-BATCH-{int(time.time())}",
                                "obs_type": "BATCH_VERIFICATION",
                                "chain_result": chain_result,
                                "manifest_result": manifest_result,
                                "status": status, "timestamp": _now_iso()})
    if not all_pass:
        _append_obs(OBS_ALERT_PATH, {"alert_type": "BATCH_VERIFICATION_FAIL",
                                      "chain_result": chain_result,
                                      "manifest_result": manifest_result,
                                      "timestamp": _now_iso()})
    return {"status": status, "chain": chain_result, "manifest": manifest_result}

_scheduler_running = False
def start_batch_scheduler():
    global _scheduler_running
    if _scheduler_running: return
    _scheduler_running = True
    def _loop():
        while _scheduler_running:
            time.sleep(BATCH_INTERVAL_SECONDS)
            try: run_batch_verification()
            except Exception as e:
                _append_obs(OBS_ALERT_PATH, {"alert_type": "BATCH_SCHEDULER_ERROR",
                                              "error": str(e), "timestamp": _now_iso()})
    t = threading.Thread(target=_loop, daemon=True); t.start()
def stop_batch_scheduler():
    global _scheduler_running
    _scheduler_running = False

"""
observation_verifier.py
AIBA Independent Observation Verifier — EAG-S209-EAG3-001
EAG-3: 검증 결과(PASS/FAIL) 반환 전용.
상태 관리(eag3_state, fail_closed.flag)는 governance_manager.py 전담.

ARCHITECTURE RULE:
  observation_verifier.py → ledger_verifier.py (ALLOWED)
  observation_verifier.py → ledger_writer.py   (FORBIDDEN — 절대 금지)
"""
from __future__ import annotations
import json, os, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
OBSERVATION_DIR = Path(ARSS_ROOT) / "observation"
OBS_LOG_PATH   = OBSERVATION_DIR / "observation_log.jsonl"
OBS_ALERT_PATH = OBSERVATION_DIR / "observation_alerts.jsonl"
BATCH_INTERVAL_SECONDS = 300
KST = timezone(timedelta(hours=9))

def _now_iso(): return datetime.now(KST).isoformat()

def _append_obs(path, record):
    """Observation 전용 기록 — fail_closed 상태에서도 항상 허용."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

def observe_append(actor, seq, entry_hash, session):
    """실시간 append 관측 — 형식 검증 후 PASS/ALERT 반환."""
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

def run_batch_verification(session: str = None) -> dict:
    """
    Hash Chain + Manifest 검증 수행.
    결과를 observation_log에 기록하고 {status, chain, manifest} 반환.
    상태 반영(eag3_state 업데이트)은 governance_manager.record_session_verification() 호출 측 책임.
    """
    import sys as _sys
    lp = "/opt/arss/engine/arss-protocol/tools/ledger"
    if lp not in _sys.path: _sys.path.insert(0, lp)
    from ledger_verifier import verify_all_chains, verify_manifest

    chain_result = verify_all_chains()
    manifest_result = verify_manifest()
    all_pass = (chain_result.get("status") == "PASS"
                and manifest_result.get("status") == "PASS")
    status = "PASS" if all_pass else "FAIL"

    log_record = {
        "obs_id": f"OBS-BATCH-{int(time.time())}",
        "obs_type": "SESSION_VERIFICATION",
        "session": session,
        "chain_result": chain_result,
        "manifest_result": manifest_result,
        "status": status,
        "timestamp": _now_iso(),
    }
    _append_obs(OBS_LOG_PATH, log_record)

    if not all_pass:
        _append_obs(OBS_ALERT_PATH, {
            "alert_type": "BATCH_VERIFICATION_FAIL",
            "session": session,
            "chain_result": chain_result,
            "manifest_result": manifest_result,
            "timestamp": _now_iso(),
        })

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

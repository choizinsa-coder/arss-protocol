"""
ledger_verifier.py
AIBA WORM Ledger Verifier — EAG-S209-EAG3-001
결과 코드 표준화: governance_manager / observation_verifier 호출 호환
"""
from __future__ import annotations
import hashlib, json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
LEDGER_DIR = Path(ARSS_ROOT) / "ledger"
OBSERVATION_DIR = Path(ARSS_ROOT) / "observation"
LEDGER_PATHS = {
    "caddy": LEDGER_DIR / "state_ledger_caddy.jsonl",
    "domi":  LEDGER_DIR / "state_ledger_domi.jsonl",
    "jeni":  LEDGER_DIR / "state_ledger_jeni.jsonl",
}
MANIFEST_PATH  = LEDGER_DIR / "ledger_manifest.jsonl"
OBS_ALERT_PATH = OBSERVATION_DIR / "observation_alerts.jsonl"
GENESIS_PREV_HASH = "0" * 64
KST = timezone(timedelta(hours=9))

# 표준화된 결과 코드 상수
RC_PASS                         = "PASS"
RC_FAIL                         = "FAIL"
RC_GENESIS_SEQ_MISMATCH         = "GENESIS_SEQ_MISMATCH"
RC_GENESIS_PREV_HASH_MISMATCH   = "GENESIS_PREV_HASH_MISMATCH"
RC_SEQ_GAP                      = "SEQ_GAP"
RC_PREV_HASH_MISMATCH           = "PREV_HASH_MISMATCH"
RC_ENTRY_HASH_TAMPERED          = "ENTRY_HASH_TAMPERED"
RC_ENTRY_AFTER_FREEZE           = "ENTRY_AFTER_FREEZE"
RC_INVALID_ACTOR                = "INVALID_ACTOR"
RC_LEDGER_EMPTY                 = "LEDGER_EMPTY_OR_NOT_FOUND"
RC_MANIFEST_EMPTY               = "MANIFEST_EMPTY_OR_NOT_FOUND"
RC_MANIFEST_GENESIS_PH_MISMATCH = "MANIFEST_GENESIS_PREV_HASH_MISMATCH"
RC_MANIFEST_PREV_HASH_MISMATCH  = "MANIFEST_PREV_HASH_MISMATCH"
RC_MANIFEST_HASH_TAMPERED       = "MANIFEST_ENTRY_HASH_TAMPERED"
RC_MANIFEST_AFTER_FREEZE        = "MANIFEST_ENTRY_AFTER_FREEZE"
RC_MANIFEST_HEAD_MISMATCH       = "MANIFEST_HEAD_MISMATCH"

def _sha256(data): return hashlib.sha256(data.encode("utf-8")).hexdigest()
def _now_iso(): return datetime.now(KST).isoformat()

def _compute_entry_hash(entry):
    filtered = {k: v for k, v in entry.items() if k != "entry_hash"}
    return _sha256(json.dumps(filtered, sort_keys=True, ensure_ascii=False))

def _read_all_entries(path):
    if not path.exists(): return []
    entries = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: entries.append(json.loads(line))
                    except json.JSONDecodeError: pass
    except OSError: pass
    return entries

def _write_alert(alert_type, ledger, detail, entry_seq=None):
    OBS_ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"alert_type": alert_type, "ledger": ledger,
              "detail": detail, "timestamp": _now_iso()}
    if entry_seq is not None: record["entry_seq"] = entry_seq
    try:
        with open(OBS_ALERT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush(); os.fsync(f.fileno())
    except OSError: pass

def verify_chain(actor) -> dict:
    """단일 actor 체인 검증. 표준화된 reason 코드 반환."""
    if actor not in LEDGER_PATHS:
        return {"status": RC_FAIL, "actor": actor, "reason": RC_INVALID_ACTOR}
    entries = _read_all_entries(LEDGER_PATHS[actor])
    if not entries:
        return {"status": RC_FAIL, "actor": actor, "reason": RC_LEDGER_EMPTY}
    freeze_detected = False
    for i, entry in enumerate(entries):
        seq = entry.get("seq")
        if i == 0:
            if seq != 0:
                r = f"{RC_GENESIS_SEQ_MISMATCH}: expected=0 got={seq}"
                _write_alert("SEQ_MISMATCH", actor, r, seq)
                return {"status": RC_FAIL, "actor": actor, "reason": r, "entry_seq": seq}
            if entry.get("prev_hash") != GENESIS_PREV_HASH:
                _write_alert("HASH_MISMATCH", actor, RC_GENESIS_PREV_HASH_MISMATCH, seq)
                return {"status": RC_FAIL, "actor": actor,
                        "reason": RC_GENESIS_PREV_HASH_MISMATCH, "entry_seq": seq}
        else:
            exp_seq = entries[i-1].get("seq", -1) + 1
            if seq != exp_seq:
                r = f"{RC_SEQ_GAP}: expected={exp_seq} got={seq}"
                _write_alert("SEQ_GAP", actor, r, seq)
                return {"status": RC_FAIL, "actor": actor, "reason": r, "entry_seq": seq}
            exp_prev = entries[i-1].get("entry_hash", "")
            if entry.get("prev_hash") != exp_prev:
                r = f"{RC_PREV_HASH_MISMATCH} at seq={seq}"
                _write_alert("HASH_MISMATCH", actor, r, seq)
                return {"status": RC_FAIL, "actor": actor, "reason": r, "entry_seq": seq}
        recomputed = _compute_entry_hash(entry)
        if recomputed != entry.get("entry_hash"):
            r = f"{RC_ENTRY_HASH_TAMPERED} at seq={seq}"
            _write_alert("HASH_TAMPERED", actor, r, seq)
            return {"status": RC_FAIL, "actor": actor, "reason": r, "entry_seq": seq}
        if freeze_detected:
            r = f"{RC_ENTRY_AFTER_FREEZE} at seq={seq}"
            _write_alert("ENTRY_AFTER_FREEZE", actor, r, seq)
            return {"status": RC_FAIL, "actor": actor, "reason": r, "entry_seq": seq}
    return {"status": RC_PASS, "actor": actor, "entries": len(entries)}

def verify_all_chains() -> dict:
    """전체 actor 체인 검증. all_pass 여부 포함 반환."""
    results = {}
    all_pass = True
    for actor in LEDGER_PATHS:
        r = verify_chain(actor)
        results[actor] = r
        if r["status"] != RC_PASS: all_pass = False
    return {"status": RC_PASS if all_pass else RC_FAIL, "chains": results}

def verify_manifest() -> dict:
    """Manifest Hash Chain + HEAD 정합성 검증."""
    entries = _read_all_entries(MANIFEST_PATH)
    if not entries:
        return {"status": RC_FAIL, "reason": RC_MANIFEST_EMPTY}
    for i, entry in enumerate(entries):
        seq = entry.get("seq")
        if i == 0:
            if entry.get("prev_hash") != GENESIS_PREV_HASH:
                _write_alert("MANIFEST_HASH_MISMATCH", "manifest",
                             RC_MANIFEST_GENESIS_PH_MISMATCH, seq)
                return {"status": RC_FAIL, "reason": RC_MANIFEST_GENESIS_PH_MISMATCH}
        else:
            exp_prev = entries[i-1].get("entry_hash", "")
            if entry.get("prev_hash") != exp_prev:
                r = f"{RC_MANIFEST_PREV_HASH_MISMATCH} at seq={seq}"
                _write_alert("MANIFEST_HASH_MISMATCH", "manifest", r, seq)
                return {"status": RC_FAIL, "reason": r}
        recomputed = _compute_entry_hash(entry)
        if recomputed != entry.get("entry_hash"):
            r = f"{RC_MANIFEST_HASH_TAMPERED} at seq={seq}"
            _write_alert("MANIFEST_HASH_TAMPERED", "manifest", r, seq)
            return {"status": RC_FAIL, "reason": r}
    freeze_idx = None
    for i, entry in enumerate(entries):
        if entry.get("event") == "SESSION_FREEZE": freeze_idx = i
    if freeze_idx is not None and freeze_idx < len(entries) - 1:
        r = f"{RC_MANIFEST_AFTER_FREEZE} at seq={entries[freeze_idx+1].get('seq')}"
        _write_alert("ENTRY_AFTER_FREEZE", "manifest", r)
        return {"status": RC_FAIL, "reason": r}
    latest = entries[-1]
    mismatches = []
    for actor, path in LEDGER_PATHS.items():
        ents = _read_all_entries(path)
        actual = ents[-1]["entry_hash"] if ents else GENESIS_PREV_HASH
        manifest_h = latest.get(f"{actor}_head", "")
        if actual != manifest_h:
            mismatches.append({"actor": actor,
                                "manifest_head": manifest_h,
                                "actual_head": actual})
    if mismatches:
        r = f"{RC_MANIFEST_HEAD_MISMATCH}: {mismatches}"
        _write_alert("MANIFEST_HEAD_MISMATCH", "manifest", r)
        return {"status": RC_FAIL, "reason": r, "mismatches": mismatches}
    return {"status": RC_PASS, "manifest_entries": len(entries),
            "frozen": freeze_idx is not None,
            "freeze_session": latest.get("session") if freeze_idx is not None else None}

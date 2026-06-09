"""
ledger_writer.py
AIBA WORM Ledger Writer — EAG-S209-EAG3-001
Constitution 제4조(불변 장부) · 제5조(독립 관측) 구현
__write_to_disk() 단일 계층으로 fail_closed 검사 중앙화
"""
from __future__ import annotations
import hashlib, json, os, threading, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
LEDGER_DIR = Path(ARSS_ROOT) / "ledger"
OBSERVATION_DIR = Path(ARSS_ROOT) / "observation"
LEDGER_TOKEN_REGISTRY = Path(ARSS_ROOT) / "registry" / "ledger_tokens.json"
FAIL_CLOSED_FLAG = OBSERVATION_DIR / "fail_closed.flag"
LEDGER_PATHS = {
    "caddy": LEDGER_DIR / "state_ledger_caddy.jsonl",
    "domi":  LEDGER_DIR / "state_ledger_domi.jsonl",
    "jeni":  LEDGER_DIR / "state_ledger_jeni.jsonl",
}
MANIFEST_PATH  = LEDGER_DIR / "ledger_manifest.jsonl"
OBS_LOG_PATH   = OBSERVATION_DIR / "observation_log.jsonl"
OBS_ALERT_PATH = OBSERVATION_DIR / "observation_alerts.jsonl"
ALLOWED_ACTORS = frozenset({"caddy", "domi", "jeni"})
# write_type 상수 — private 가드용
_WT_LEDGER      = "LEDGER"
_WT_OBSERVATION = "OBSERVATION"
GENESIS_PREV_HASH = "0" * 64
SCHEMA_VERSION = "v1"
KST = timezone(timedelta(hours=9))

_ledger_locks = {
    "caddy": threading.Lock(), "domi": threading.Lock(),
    "jeni": threading.Lock(), "manifest": threading.Lock(),
}
_token_lock = threading.Lock()

def _sha256(data): return hashlib.sha256(data.encode("utf-8")).hexdigest()
def _now_iso(): return datetime.now(KST).isoformat()

def _compute_entry_hash(entry):
    filtered = {k: v for k, v in entry.items() if k != "entry_hash"}
    return _sha256(json.dumps(filtered, sort_keys=True, ensure_ascii=False))

# ── 단일 디스크 쓰기 계층 ─────────────────────────────────────────────────────

def __write_to_disk(path: Path, record: dict, write_type: str):
    """
    모든 파일 쓰기의 단일 진입점.
    write_type="OBSERVATION" → fail_closed 검사 없이 허용 (관측 레이어 독립성 보장)
    write_type="LEDGER"      → fail_closed.flag 존재 시 FailClosedError 발생
    write_type 파라미터는 이 모듈 내부 상수(_WT_*)만 사용할 것.
    """
    if write_type == _WT_LEDGER:
        if Path(FAIL_CLOSED_FLAG).exists():
            raise FailClosedError("FAIL_CLOSED_FLAG present — ledger write rejected")
    elif write_type != _WT_OBSERVATION:
        raise ValueError(f"INVALID_WRITE_TYPE: {write_type!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

class FailClosedError(Exception):
    pass

# ── 토큰 관리 ─────────────────────────────────────────────────────────────────

def _load_token_registry():
    if not LEDGER_TOKEN_REGISTRY.exists(): return {}
    try:
        with open(LEDGER_TOKEN_REGISTRY, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception: return {}

def _save_token_registry(registry):
    LEDGER_TOKEN_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER_TOKEN_REGISTRY.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, LEDGER_TOKEN_REGISTRY)

def register_ledger_token(token_id, actor, session, scope="append_only"):
    if actor not in ALLOWED_ACTORS:
        return {"ok": False, "error": f"INVALID_ACTOR: {actor}"}
    meta = {"token_id": token_id, "actor": actor, "session": session,
            "scope": scope, "issuer": "beo_loopback",
            "issued_at": _now_iso(), "revoked": False,
            "revoked_reason": None, "revoked_at": None}
    with _token_lock:
        reg = _load_token_registry()
        reg[token_id] = meta
        _save_token_registry(reg)
    return {"ok": True, "token_id": token_id, "actor": actor, "session": session}

def revoke_session_tokens(session, reason="SESSION_FREEZE"):
    count = 0
    with _token_lock:
        reg = _load_token_registry()
        for tid, meta in reg.items():
            if meta.get("session") == session and not meta.get("revoked"):
                meta["revoked"] = True
                meta["revoked_reason"] = reason
                meta["revoked_at"] = _now_iso()
                count += 1
        if count > 0: _save_token_registry(reg)
    return count

def validate_ledger_token(token_id, actor):
    with _token_lock: reg = _load_token_registry()
    meta = reg.get(token_id)
    if meta is None: return False, "TOKEN_NOT_FOUND"
    if meta.get("revoked"): return False, f"TOKEN_REVOKED: {meta.get('revoked_reason','unknown')}"
    if meta.get("actor") != actor: return False, f"TOKEN_ACTOR_MISMATCH: expected={meta.get('actor')} got={actor}"
    if meta.get("scope") != "append_only": return False, "TOKEN_SCOPE_INVALID"
    return True, "OK"

# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _read_last_entry(path):
    if not path.exists(): return None
    last = None
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try: last = json.loads(line)
                    except json.JSONDecodeError: pass
    except OSError: return None
    return last

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

def _is_manifest_frozen():
    last = _read_last_entry(MANIFEST_PATH)
    if last and last.get("event") == "SESSION_FREEZE":
        return True, last.get("session")
    return False, None

def _update_manifest(session, chain_tip):
    heads = {}
    for actor, path in LEDGER_PATHS.items():
        last = _read_last_entry(path)
        heads[f"{actor}_head"] = last["entry_hash"] if last else GENESIS_PREV_HASH
    last_m = _read_last_entry(MANIFEST_PATH)
    prev_hash = last_m["entry_hash"] if last_m else GENESIS_PREV_HASH
    seq = (last_m["seq"] + 1) if last_m and "seq" in last_m else 1
    entry = {"seq": seq, "timestamp": _now_iso(), "session": session,
             "chain_tip": chain_tip, **heads, "prev_hash": prev_hash}
    entry["entry_hash"] = _compute_entry_hash(entry)
    with _ledger_locks["manifest"]:
        __write_to_disk(MANIFEST_PATH, entry, _WT_LEDGER)

# ── 공개 API ──────────────────────────────────────────────────────────────────

def append_session_freeze(session, eag_id, chain_tip):
    frozen, es = _is_manifest_frozen()
    if frozen: return {"ok": False, "error": f"ALREADY_FROZEN: session={es}"}
    last_m = _read_last_entry(MANIFEST_PATH)
    prev_hash = last_m["entry_hash"] if last_m else GENESIS_PREV_HASH
    seq = (last_m["seq"] + 1) if last_m and "seq" in last_m else 1
    heads = {}
    for actor, path in LEDGER_PATHS.items():
        last = _read_last_entry(path)
        heads[f"{actor}_head"] = last["entry_hash"] if last else GENESIS_PREV_HASH
    entry = {"seq": seq, "event": "SESSION_FREEZE", "session": session,
             "eag_id": eag_id, "beo_signature": eag_id, "chain_tip": chain_tip,
             "timestamp": _now_iso(), **heads, "prev_hash": prev_hash}
    entry["entry_hash"] = _compute_entry_hash(entry)
    with _ledger_locks["manifest"]:
        try:
            __write_to_disk(MANIFEST_PATH, entry, _WT_LEDGER)
        except FailClosedError as e:
            return {"ok": False, "error": f"FAIL_CLOSED: {e}"}
    revoked = revoke_session_tokens(session, "SESSION_FREEZE")
    return {"ok": True, "event": "SESSION_FREEZE", "session": session,
            "eag_id": eag_id, "tokens_revoked": revoked, "entry_hash": entry["entry_hash"]}

def initialize_genesis(actor, session, chain_tip):
    if actor not in ALLOWED_ACTORS:
        return {"ok": False, "error": f"INVALID_ACTOR: {actor}"}
    path = LEDGER_PATHS[actor]
    if path.exists() and path.stat().st_size > 0:
        return {"ok": False, "error": "ALREADY_INITIALIZED", "path": str(path)}
    genesis = {"ledger_id": actor, "seq": 0, "timestamp": _now_iso(),
               "actor": actor, "action_type": "GENESIS",
               "payload_hash": _sha256("GENESIS"),
               "payload_ref": f"GENESIS/{session}",
               "prev_hash": GENESIS_PREV_HASH, "session": session,
               "chain_tip": chain_tip, "signature_version": SCHEMA_VERSION}
    genesis["entry_hash"] = _compute_entry_hash(genesis)
    try:
        __write_to_disk(path, genesis, _WT_LEDGER)
    except FailClosedError as e:
        return {"ok": False, "error": f"FAIL_CLOSED: {e}"}
    return {"ok": True, "actor": actor, "entry_hash": genesis["entry_hash"]}

def append_entry(actor, action_type, payload, session, chain_tip, token_id, payload_ref=""):
    if actor not in ALLOWED_ACTORS:
        return {"ok": False, "error": f"INVALID_ACTOR: {actor}"}
    valid, reason = validate_ledger_token(token_id, actor)
    if not valid:
        return {"ok": False, "error": f"FAIL_CLOSED: {reason}"}
    frozen, fs = _is_manifest_frozen()
    if frozen:
        return {"ok": False, "error": f"FAIL_CLOSED: MANIFEST_FROZEN session={fs}"}
    path = LEDGER_PATHS[actor]
    with _ledger_locks[actor]:
        last = _read_last_entry(path)
        if last is None:
            return {"ok": False, "error": "FAIL_CLOSED: LEDGER_NOT_INITIALIZED"}
        prev_hash = last["entry_hash"]
        last_seq = last.get("seq", -1)
        new_seq = last_seq + 1
        payload_hash = _sha256(payload)
        entry = {"ledger_id": actor, "seq": new_seq, "timestamp": _now_iso(),
                 "actor": actor, "action_type": action_type,
                 "payload_hash": payload_hash,
                 "payload_ref": payload_ref or f"{action_type}/{session}/{new_seq}",
                 "prev_hash": prev_hash, "session": session,
                 "chain_tip": chain_tip, "signature_version": SCHEMA_VERSION}
        entry["entry_hash"] = _compute_entry_hash(entry)
        try:
            __write_to_disk(path, entry, _WT_LEDGER)
        except FailClosedError as e:
            return {"ok": False, "error": f"FAIL_CLOSED: {e}"}
    _update_manifest(session, chain_tip)
    __write_to_disk(OBS_LOG_PATH, {"obs_type": "APPEND", "actor": actor,
                                    "seq": new_seq, "entry_hash": entry["entry_hash"],
                                    "session": session, "timestamp": _now_iso()},
                    _WT_OBSERVATION)
    return {"ok": True, "actor": actor, "seq": new_seq,
            "entry_hash": entry["entry_hash"], "prev_hash": prev_hash}

#!/usr/bin/env python3
"""
arss_gatekeeper.py v3.0
AIBA EAG Enforcement Layer — eag_approval record 기반 검증
설계: 도미 v3.0
EAG-1: 비오(Joshua) 2026-04-12 Session 25
EAG-2: 비오(Joshua) 2026-04-12 Session 25
"""

import hashlib, json, os, stat, sys, pathlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

BASE_DIR        = pathlib.Path("/opt/arss/engine/arss-protocol")
TOKEN_PATH      = BASE_DIR / ".approval_token"
RECEIPTS_DIR    = BASE_DIR / "evidence" / "receipts"
EAG_APPROVALS   = BASE_DIR / "evidence" / "eag_approvals"
KST             = timezone(timedelta(hours=9))
SCHEMA_TYPE     = "approval_token"
SCHEMA_VERSION  = "3.0"
APPROVAL_SCOPE  = "RPU_ISSUE"
APPROVED_BY     = "Beo"
CANONICAL_ISSUER= str(BASE_DIR / "tools" / "rpu_atomic_issuer.py")

REQUIRED_FIELDS = [
    "schema_type","schema_version","approval_scope","approved_by",
    "approved_at_kst","session_id","event_hash","issuer_path",
    "ttl_seconds","expires_at_kst","nonce","approval_hash","status","token_hash"
]
HASH_FIELDS = [
    "schema_type","schema_version","approval_scope","approved_by",
    "approved_at_kst","session_id","event_hash","issuer_path",
    "ttl_seconds","expires_at_kst","nonce","approval_hash","status"
]

@dataclass
class GatekeeperResult:
    approved: bool
    reason: str
    receipt_path: str = ""

def _now_kst():
    return datetime.now(KST)

def _derive_session_id(session_count):
    return _now_kst().strftime(f"AIBA-%Y-%m-%d-S{session_count}")

def _compute_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"

def _compute_approval_hash(session_id, event_hash, issuer_path, approved_at_kst):
    raw = session_id + event_hash + issuer_path + approved_at_kst
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _compute_token_hash(token):
    payload = {k: token[k] for k in sorted(HASH_FIELDS) if k in token}
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",",":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _write_receipt(approved, session_id, reason, extra=None):
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _now_kst().strftime("%Y%m%dT%H%M%S")
    fname = RECEIPTS_DIR / f"receipt_{ts}_{session_id}.json"
    payload = {"timestamp_kst": _now_kst().isoformat(), "session_id": session_id,
               "approved": approved, "reason": reason, "gatekeeper_version": "v3.0"}
    if extra:
        payload.update(extra)
    fname.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.chmod(fname, stat.S_IRUSR)
    return str(fname)

def _fail(reason, session_id, extra=None):
    receipt = _write_receipt(False, session_id, reason, extra)
    return GatekeeperResult(approved=False, reason=reason, receipt_path=receipt)

def _load_eag_approval(session_id, event_hash, issuer_path):
    if not EAG_APPROVALS.exists():
        return None
    for f in sorted(EAG_APPROVALS.glob("*.json"), reverse=True):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if (rec.get("type") == "eag_approval" and rec.get("stage") == "EAG-2" and
                    rec.get("session_id") == session_id and rec.get("event_hash") == event_hash and
                    rec.get("issuer_path") == issuer_path and rec.get("approved_by") == APPROVED_BY):
                return rec
        except Exception:
            continue
    return None

def validate(event_file_path, approval_token_path, session_count, issuer_path=CANONICAL_ISSUER):
    session_id = _derive_session_id(session_count)
    token_p = pathlib.Path(approval_token_path)
    if not token_p.exists():
        return _fail("APPROVAL_TOKEN_NOT_FOUND", session_id)
    try:
        token = json.loads(token_p.read_text(encoding="utf-8"))
    except Exception:
        return _fail("APPROVAL_TOKEN_JSON_PARSE_FAILED", session_id)
    if token.get("schema_type") != SCHEMA_TYPE or token.get("schema_version") != SCHEMA_VERSION:
        return _fail("APPROVAL_TOKEN_SCHEMA_MISMATCH", session_id)
    for field in REQUIRED_FIELDS:
        if field not in token:
            return _fail("APPROVAL_TOKEN_REQUIRED_FIELD_MISSING", session_id, {"missing_field": field})
    for tf in ("approved_at_kst","expires_at_kst"):
        try: datetime.fromisoformat(token[tf])
        except: return _fail("APPROVAL_TOKEN_VALUE_INVALID", session_id, {"field": tf})
    for hf in ("event_hash","approval_hash","token_hash"):
        if not token[hf].startswith("sha256:"):
            return _fail("APPROVAL_TOKEN_VALUE_INVALID", session_id, {"field": hf})
    if token["status"] not in ("unused","used","void"):
        return _fail("APPROVAL_TOKEN_VALUE_INVALID", session_id, {"field": "status"})
    if not isinstance(token["ttl_seconds"], int):
        return _fail("APPROVAL_TOKEN_VALUE_INVALID", session_id, {"field": "ttl_seconds"})
    computed_approval = _compute_approval_hash(token["session_id"], token["event_hash"],
                                               token["issuer_path"], token["approved_at_kst"])
    if computed_approval != token["approval_hash"]:
        return _fail("APPROVAL_TOKEN_APPROVAL_HASH_MISMATCH", session_id)
    if token["approval_scope"] != APPROVAL_SCOPE:
        return _fail("APPROVAL_TOKEN_SCOPE_MISMATCH", session_id)
    event_p = pathlib.Path(event_file_path)
    if not event_p.exists():
        return _fail("EVENT_FILE_NOT_FOUND", session_id, {"event_file_path": event_file_path})
    with open(event_file_path, 'r', encoding='utf-8') as _ef:
        _ev = json.load(_ef)
    _payload_str = json.dumps({
        'actor_id':   _ev.get('actor_id', ''),
        'content':    _ev.get('content', ''),
        'event_type': _ev.get('event_type', ''),
    }, sort_keys=True, ensure_ascii=False)
    actual = 'sha256:' + hashlib.sha256(_payload_str.encode()).hexdigest()
    if actual != token["event_hash"]:
        return _fail("APPROVAL_TOKEN_EVENT_HASH_MISMATCH", session_id,
                     {"expected": token["event_hash"], "actual": actual})
    if token["issuer_path"] != issuer_path:
        return _fail("APPROVAL_TOKEN_ISSUER_PATH_MISMATCH", session_id)
    if token["session_id"] != session_id:
        return _fail("APPROVAL_TOKEN_SESSION_ID_MISMATCH", session_id,
                     {"expected": session_id, "actual": token["session_id"]})
    try:
        expires = datetime.fromisoformat(token["expires_at_kst"])
        if _now_kst() > expires:
            return _fail("APPROVAL_TOKEN_EXPIRED", session_id)
    except:
        return _fail("APPROVAL_TOKEN_VALUE_INVALID", session_id, {"field": "expires_at_kst"})
    if token["status"] != "unused":
        return _fail("APPROVAL_TOKEN_STATUS_INVALID", session_id, {"status": token["status"]})
    rec = _load_eag_approval(session_id, token["event_hash"], issuer_path)
    if rec is None:
        return _fail("EAG_APPROVAL_RECORD_NOT_FOUND", session_id)
    rec_hash = _compute_approval_hash(rec["session_id"], rec["event_hash"],
                                      rec["issuer_path"], rec["approved_at_kst"])
    if rec_hash != rec.get("approval_hash"):
        return _fail("EAG_APPROVAL_RECORD_HASH_MISMATCH", session_id)
    computed_token = _compute_token_hash(token)
    if computed_token != token["token_hash"]:
        return _fail("APPROVAL_TOKEN_HASH_MISMATCH", session_id)
    receipt = _write_receipt(True, session_id, "EAG_APPROVED",
                             {"token_hash": token["token_hash"], "approval_hash": token["approval_hash"]})
    return GatekeeperResult(approved=True, reason="EAG_APPROVED", receipt_path=receipt)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AIBA EAG Gatekeeper v3.0")
    parser.add_argument("--event-file", required=True)
    parser.add_argument("--approval-token", required=True)
    parser.add_argument("--session-count", type=int, required=True)
    parser.add_argument("--issuer-path", default=CANONICAL_ISSUER)
    args = parser.parse_args()
    result = validate(args.event_file, args.approval_token, args.session_count, args.issuer_path)
    print(json.dumps({"approved": result.approved, "reason": result.reason,
                      "receipt_path": result.receipt_path}, ensure_ascii=False, indent=2))
    sys.exit(0 if result.approved else 1)

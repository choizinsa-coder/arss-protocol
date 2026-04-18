#!/usr/bin/env python3
"""
create_approval_token.py
EAG-2 승인 직후 eag_approval record 기반 approval_token v3.0 생성
비오(Joshua) 직접 실행
"""

import hashlib, json, os, stat, sys, pathlib, uuid
from datetime import datetime, timezone, timedelta

BASE_DIR         = pathlib.Path("/opt/arss/engine/arss-protocol")
TOKEN_PATH       = BASE_DIR / ".approval_token"
EAG_APPROVALS    = BASE_DIR / "evidence" / "eag_approvals"
KST              = timezone(timedelta(hours=9))
CANONICAL_ISSUER = str(BASE_DIR / "tools" / "rpu_atomic_issuer.py")

HASH_FIELDS = [
    "schema_type", "schema_version", "approval_scope",
    "approved_by", "approved_at_kst", "session_id",
    "event_hash", "issuer_path", "ttl_seconds",
    "expires_at_kst", "nonce", "approval_hash", "status"
]

def compute_token_hash(token: dict) -> str:
    payload = {k: token[k] for k in sorted(HASH_FIELDS) if k in token}
    canonical = json.dumps(payload, ensure_ascii=False,
                           separators=(",", ":"), sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def load_eag_approval(session_id, event_hash, issuer_path):
    if not EAG_APPROVALS.exists():
        return None
    for f in sorted(EAG_APPROVALS.glob("*.json"), reverse=True):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            if (rec.get("type") == "eag_approval" and
                    rec.get("stage") == "EAG-2" and
                    rec.get("session_id") == session_id and
                    rec.get("event_hash") == event_hash and
                    rec.get("issuer_path") == issuer_path and
                    rec.get("approved_by") == "Beo"):
                return rec
        except Exception:
            continue
    return None

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file",    required=True)
    parser.add_argument("--session-count", type=int, required=True)
    parser.add_argument("--issuer-path",   default=CANONICAL_ISSUER)
    parser.add_argument("--ttl",           type=int, default=7200)
    args = parser.parse_args()

    now_kst    = datetime.now(KST)
    session_id = now_kst.strftime(f"AIBA-%Y-%m-%d-S{args.session_count}")

    # event_hash 계산
    with open(args.event_file, 'r', encoding='utf-8') as _ef:
        _ev = json.load(_ef)
    _payload_str = json.dumps({
        'actor_id':   _ev.get('actor_id', ''),
        'content':    _ev.get('content', ''),
        'event_type': _ev.get('event_type', ''),
    }, sort_keys=True, ensure_ascii=False)
    event_hash = 'sha256:' + hashlib.sha256(_payload_str.encode()).hexdigest()

    rec = load_eag_approval(session_id, event_hash, args.issuer_path)
    if rec is None:
        print("ERROR: EAG_APPROVAL_RECORD_NOT_FOUND")
        print(f"  session_id: {session_id}")
        print(f"  event_hash: {event_hash}")
        sys.exit(1)

    approved_at  = now_kst.isoformat()  # 재발급 시 현재 시각 기준
    approval_hash = rec["approval_hash"]
    expires_at   = (now_kst +
                    timedelta(seconds=args.ttl)).isoformat()

    token = {
        "schema_type":    "approval_token",
        "schema_version": "3.0",
        "approval_scope": "RPU_ISSUE",
        "approved_by":    "Beo",
        "approved_at_kst": approved_at,
        "session_id":     session_id,
        "event_hash":     event_hash,
        "issuer_path":    args.issuer_path,
        "ttl_seconds":    args.ttl,
        "expires_at_kst": expires_at,
        "nonce":          str(uuid.uuid4()),
        "approval_hash":  approval_hash,
        "status":         "unused",
        "token_hash":     ""
    }
    token["token_hash"] = compute_token_hash(token)

    TOKEN_PATH.write_text(json.dumps(token, ensure_ascii=False, indent=2))
    os.chmod(TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)

    print(json.dumps({
        "status":        "created",
        "schema_version": "3.0",
        "session_id":    session_id,
        "event_hash":    event_hash,
        "approval_hash": approval_hash,
        "token_hash":    token["token_hash"],
        "expires_at_kst": expires_at,
        "path":          str(TOKEN_PATH)
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

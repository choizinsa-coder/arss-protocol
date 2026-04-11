#!/usr/bin/env python3
"""
create_eag_approval.py
EAG-2 승인 직후 비오(Joshua) 직접 실행
evidence/eag_approvals/ 에 approval record 생성
"""

import hashlib, json, os, stat, sys, pathlib, uuid
from datetime import datetime, timezone, timedelta

BASE_DIR      = pathlib.Path("/opt/arss/engine/arss-protocol")
EAG_APPROVALS = BASE_DIR / "evidence" / "eag_approvals"
KST           = timezone(timedelta(hours=9))
CANONICAL_ISSUER = str(BASE_DIR / "tools" / "rpu_atomic_issuer.py")

def compute_approval_hash(session_id, event_hash, issuer_path, approved_at_kst):
    raw = session_id + event_hash + issuer_path + approved_at_kst
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()

def compute_file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file",    required=True)
    parser.add_argument("--session-count", type=int, required=True)
    parser.add_argument("--issuer-path",   default=CANONICAL_ISSUER)
    args = parser.parse_args()

    now_kst      = datetime.now(KST)
    session_id   = now_kst.strftime(f"AIBA-%Y-%m-%d-S{args.session_count}")
    approved_at  = now_kst.isoformat()
    event_hash   = compute_file_sha256(args.event_file)
    approval_id  = "eag-" + str(uuid.uuid4())

    approval_hash = compute_approval_hash(
        session_id, event_hash, args.issuer_path, approved_at
    )

    record = {
        "type":          "eag_approval",
        "stage":         "EAG-2",
        "approval_id":   approval_id,
        "approved_by":   "Beo",
        "approved_at_kst": approved_at,
        "session_id":    session_id,
        "event_hash":    event_hash,
        "issuer_path":   args.issuer_path,
        "approval_hash": approval_hash
    }

    EAG_APPROVALS.mkdir(parents=True, exist_ok=True)
    ts    = now_kst.strftime("%Y%m%dT%H%M%S")
    fname = EAG_APPROVALS / f"eag_approval_{ts}_{session_id}.json"
    fname.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    os.chmod(fname, stat.S_IRUSR | stat.S_IRGRP)

    print(json.dumps({
        "status":        "created",
        "approval_id":   approval_id,
        "session_id":    session_id,
        "event_hash":    event_hash,
        "approval_hash": approval_hash,
        "path":          str(fname)
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

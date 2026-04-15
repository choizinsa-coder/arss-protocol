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


def _fetch_session_count_from_status() -> int:
    """GET http://159.203.125.1:8000/status → data.session_count 자동 획득 (DIS-044)"""
    import urllib.request as _urllib_req
    import json as _json_inner
    try:
        _req = _urllib_req.Request(
            'http://159.203.125.1:8000/status',
            headers={'Authorization': 'Bearer ' + os.environ['AIBA_TOKEN_CADDY']}
        )
        with _urllib_req.urlopen(_req, timeout=5) as resp:
            _body = _json_inner.loads(resp.read().decode())
        return int(_body['data']['session_count'])
    except Exception as e:
        raise RuntimeError(f'[session_count auto-fetch 실패] {e}')

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-file",    required=True)
    parser.add_argument("--session-count", type=int, required=False, default=None, help='미입력 시 GET /status auto-fetch (DIS-044)')
    parser.add_argument("--issuer-path",   default=CANONICAL_ISSUER)
    args = parser.parse_args()

    now_kst      = datetime.now(KST)
    if args.session_count is None:
        args.session_count = _fetch_session_count_from_status()
    session_id   = now_kst.strftime(f"AIBA-%Y-%m-%d-S{args.session_count}")
    approved_at  = now_kst.isoformat()
    # R4 canonical payload hash (DIS-044 / LESSON-016)
    import json as _json_ev
    with open(args.event_file, 'r', encoding='utf-8') as _ef:
        _event_data = _json_ev.load(_ef)
    _payload_str = _json_ev.dumps({
        'actor_id':   _event_data.get('actor_id', ''),
        'content':    _event_data.get('content', ''),
        'event_type': _event_data.get('event_type', ''),
    }, sort_keys=True, ensure_ascii=False)
    event_hash = 'sha256:' + hashlib.sha256(_payload_str.encode()).hexdigest()
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
        "actor_id":      _event_data.get('actor_id', ''),
        "content":       _event_data.get('content', ''),
        "event_type":    _event_data.get('event_type', ''),
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

"""
session_journal_writer.py
AIBA Phase 1 Shared Memory — Decision Memory Layer
EAG-S217-PHASE1-001

설계 근거:
  - 도미 3차 설계 + 캐디 IMPLEMENTABLE + 제니 TRUST_READY (S217)
  - ledger_writer.py _compute_entry_hash / GENESIS_PREV_HASH 방식 그대로 재사용
  - session_journal은 caddy/domi/jeni ledger와 완전 독립 체인
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 경로 정의 ────────────────────────────────────────────────────────────────
ARSS_ROOT = "/opt/arss/engine/arss-protocol"
JOURNAL_DIR = Path(ARSS_ROOT) / "session_journal"
JOURNAL_PATH = JOURNAL_DIR / "session_journal.jsonl"

# ── 상수 ─────────────────────────────────────────────────────────────────────
GENESIS_PREV_HASH = "0" * 64
ALLOWED_ACTORS = frozenset({"caddy", "domi", "jeni", "beo", "session_journal"})
ALLOWED_EVENT_TYPES = frozenset({"DECISION", "INCIDENT", "EAG", "OI"})
SCHEMA_VERSION = "v1"
KST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _compute_entry_hash(entry: dict) -> str:
    """ledger_writer.py _compute_entry_hash와 동일한 방식."""
    filtered = {k: v for k, v in entry.items() if k != "entry_hash"}
    return _sha256(json.dumps(filtered, sort_keys=True, ensure_ascii=False))


def _read_last_entry() -> Optional[dict]:
    """session_journal의 마지막 항목 반환. 없으면 None."""
    if not JOURNAL_PATH.exists():
        return None
    last = None
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except json.JSONDecodeError:
                        pass
    except OSError:
        return None
    return last


def _read_all_entries() -> list:
    """session_journal 전체 항목 반환."""
    if not JOURNAL_PATH.exists():
        return []
    entries = []
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return entries


def _append_to_disk(record: dict) -> None:
    """단일 디스크 쓰기. 디렉토리 자동 생성."""
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


# ── 공개 API ──────────────────────────────────────────────────────────────────

def initialize_genesis() -> dict:
    """
    session_journal genesis 항목 생성.
    이미 초기화된 경우 ALREADY_INITIALIZED 반환.
    """
    if JOURNAL_PATH.exists() and JOURNAL_PATH.stat().st_size > 0:
        return {"ok": False, "error": "ALREADY_INITIALIZED", "path": str(JOURNAL_PATH)}

    genesis = {
        "session_id": "GENESIS",
        "timestamp": _now_iso(),
        "actor": "session_journal",
        "event_type": "DECISION",
        "details": {
            "note": "session_journal GENESIS — Phase 1 Shared Memory EAG-S217-PHASE1-001"
        },
        "prev_hash": GENESIS_PREV_HASH,
        "schema_version": SCHEMA_VERSION,
    }
    genesis["entry_hash"] = _compute_entry_hash(genesis)

    _append_to_disk(genesis)
    return {"ok": True, "entry_hash": genesis["entry_hash"], "path": str(JOURNAL_PATH)}


def append_journal_entry(
    session_id: str,
    actor: str,
    event_type: str,
    details: dict,
) -> dict:
    """
    session_journal에 새 항목 추가.
    prev_hash는 직전 항목의 entry_hash를 자동으로 연결.
    """
    if actor not in ALLOWED_ACTORS:
        return {"ok": False, "error": f"INVALID_ACTOR: {actor}"}
    if event_type not in ALLOWED_EVENT_TYPES:
        return {"ok": False, "error": f"INVALID_EVENT_TYPE: {event_type}"}

    last = _read_last_entry()
    if last is None:
        return {"ok": False, "error": "JOURNAL_NOT_INITIALIZED — run initialize_genesis() first"}

    prev_hash = last["entry_hash"]

    entry = {
        "session_id": session_id,
        "timestamp": _now_iso(),
        "actor": actor,
        "event_type": event_type,
        "details": details,
        "prev_hash": prev_hash,
        "schema_version": SCHEMA_VERSION,
    }
    entry["entry_hash"] = _compute_entry_hash(entry)

    _append_to_disk(entry)
    return {
        "ok": True,
        "session_id": session_id,
        "entry_hash": entry["entry_hash"],
        "prev_hash": prev_hash,
    }


def migrate_seed_data(seed_entries: list[dict]) -> dict:
    """
    S210~S216 key_decisions seed 데이터 일괄 로드.
    seed_entries: [{"session_id": "S210", "event_type": "DECISION",
                    "actor": "beo", "details": {"decision": "..."}}]
    genesis가 없으면 자동 생성 후 연속 로드.
    """
    # genesis 없으면 자동 초기화
    if not JOURNAL_PATH.exists() or JOURNAL_PATH.stat().st_size == 0:
        result = initialize_genesis()
        if not result["ok"]:
            return {"ok": False, "error": f"GENESIS_FAILED: {result['error']}"}

    results = []
    for entry_data in seed_entries:
        r = append_journal_entry(
            session_id=entry_data["session_id"],
            actor=entry_data.get("actor", "beo"),
            event_type=entry_data.get("event_type", "DECISION"),
            details=entry_data.get("details", {}),
        )
        results.append(r)
        if not r["ok"]:
            return {
                "ok": False,
                "error": f"MIGRATION_FAILED at {entry_data['session_id']}: {r['error']}",
                "completed": results,
            }

    return {
        "ok": True,
        "migrated_count": len(results),
        "last_entry_hash": results[-1]["entry_hash"] if results else None,
    }


def get_recent_decisions(n: int = 3) -> list[dict]:
    """
    최근 n개 DECISION 항목 반환.
    recent_decisions 자동 생성용 (OI-P1-003 활용도 검증 대상).
    """
    entries = _read_all_entries()
    decisions = [e for e in entries if e.get("event_type") == "DECISION"]
    return decisions[-n:]


def verify_chain_integrity() -> dict:
    """
    session_journal 해시 체인 무결성 검증.
    전체 항목 순회 — prev_hash 연결 확인.
    """
    entries = _read_all_entries()
    if not entries:
        return {"ok": False, "error": "JOURNAL_EMPTY"}

    errors = []
    for i, entry in enumerate(entries):
        # entry_hash 재계산
        computed = _compute_entry_hash(entry)
        if computed != entry.get("entry_hash"):
            errors.append({
                "seq": i,
                "session_id": entry.get("session_id"),
                "error": "ENTRY_HASH_MISMATCH",
                "expected": computed,
                "actual": entry.get("entry_hash"),
            })
        # prev_hash 체인 검증 (genesis 제외)
        if i > 0:
            expected_prev = entries[i - 1]["entry_hash"]
            if entry.get("prev_hash") != expected_prev:
                errors.append({
                    "seq": i,
                    "session_id": entry.get("session_id"),
                    "error": "PREV_HASH_BROKEN",
                    "expected": expected_prev,
                    "actual": entry.get("prev_hash"),
                })

    if errors:
        return {"ok": False, "error_count": len(errors), "errors": errors}

    return {
        "ok": True,
        "total_entries": len(entries),
        "last_entry_hash": entries[-1]["entry_hash"],
    }

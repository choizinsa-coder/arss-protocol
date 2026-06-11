"""
append_visibility_metrics.py
Visibility Metrics를 session_journal.jsonl에 WORM append하는 CLI 스크립트
EAG: EAG-S223-JOURNAL-001
Version: 1.0.0

사용법:
  python append_visibility_metrics.py --session 222

원칙:
- SESSION_CONTEXT_S{n}_FINAL.json 에서 visibility_metrics_s{n} 블록 추출
- session_journal.jsonl 마지막 entry_hash를 prev_hash로 사용
- entry_hash = SHA256(json.dumps(payload_without_entry_hash, sort_keys=True))
- WORM append (open 'a' 모드만 허용, 사후 5단계 검증)
- 중복 항목(VISIBILITY_METRICS_S{n}) 존재 시 SKIP
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── 경로 상수 ──────────────────────────────────────────────────────
VPS_ROOT     = Path("/opt/arss/engine/arss-protocol")
JOURNAL_PATH = VPS_ROOT / "session_journal" / "session_journal.jsonl"
SC_ROOT      = VPS_ROOT

SCHEMA_VERSION = "v1"


# ── 유틸 ──────────────────────────────────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


# ── SC_FINAL 로드 ──────────────────────────────────────────────────

def load_sc_final(session_num: int, sc_root: Path = SC_ROOT) -> dict:
    """SESSION_CONTEXT_S{n}_FINAL.json 로드."""
    path = sc_root / f"SESSION_CONTEXT_S{session_num}_FINAL.json"
    if not path.exists():
        raise FileNotFoundError(
            f"SC_FINAL not found: {path}"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_visibility_metrics(sc_final: dict, session_num: int) -> dict:
    """visibility_metrics_s{n} 블록 추출."""
    key = f"visibility_metrics_s{session_num}"
    if key not in sc_final:
        raise KeyError(
            f"Key '{key}' not found in SC_FINAL "
            f"(session_count={sc_final.get('session_count')})"
        )
    return sc_final[key]


# ── journal 읽기 ──────────────────────────────────────────────────

def load_last_journal_entry(journal_path: Path) -> dict:
    """journal의 마지막 유효 entry 반환."""
    if not journal_path.exists():
        raise FileNotFoundError(f"Journal not found: {journal_path}")
    last = None
    with open(journal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
    if last is None:
        raise RuntimeError("Journal is empty or has no valid entries")
    return last


def visibility_entry_exists(journal_path: Path, session_num: int) -> bool:
    """해당 세션의 VISIBILITY_METRICS 항목이 이미 존재하는지 확인."""
    target_id = f"VISIBILITY_METRICS_S{session_num}"
    if not journal_path.exists():
        return False
    with open(journal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                details = entry.get("details", {})
                if details.get("id") == target_id:
                    return True
            except json.JSONDecodeError:
                continue
    return False


# ── entry 생성 ────────────────────────────────────────────────────

def build_visibility_journal_entry(
    session_num: int,
    metrics: dict,
    prev_hash: str,
    timestamp: str,
) -> dict:
    """
    journal entry 생성.
    실제 journal 구조: session_id/timestamp/actor/event_type/details/prev_hash/schema_version
    entry_hash = SHA256(json.dumps(payload_without_entry_hash, sort_keys=True))
    """
    details = {"id": f"VISIBILITY_METRICS_S{session_num}"}
    details.update(metrics)

    payload = {
        "session_id":     f"S{session_num}",
        "timestamp":      timestamp,
        "actor":          "caddy",
        "event_type":     "OI",
        "details":        details,
        "prev_hash":      prev_hash,
        "schema_version": SCHEMA_VERSION,
    }

    entry_hash = compute_entry_hash(payload)
    payload["entry_hash"] = entry_hash
    return payload


def compute_entry_hash(payload_without_entry_hash: dict) -> str:
    """
    entry_hash 계산.
    payload에 entry_hash 키가 없는 상태에서 호출해야 함.
    """
    assert "entry_hash" not in payload_without_entry_hash, (
        "entry_hash must NOT be present in payload before hash computation"
    )
    return _sha256(json.dumps(payload_without_entry_hash, sort_keys=True))


def verify_hash_chain(entry: dict, expected_prev_hash: str) -> bool:
    """entry의 prev_hash가 expected_prev_hash와 일치하는지 확인."""
    return entry.get("prev_hash") == expected_prev_hash


# ── WORM append ───────────────────────────────────────────────────

def worm_append(journal_path: Path, entry: dict) -> None:
    """
    WORM 5단계 append:
    1. append 전 파일 크기 및 마지막 entry_hash 기록
    2. 'a' 모드로만 open하여 append
    3. append 후 파일 크기 증가 확인
    4. 마지막 entry 재조회하여 entry_hash 일치 확인
    5. prev_hash 체인 연속성 확인
       (신규 entry의 prev_hash == append 전 마지막 entry의 entry_hash)
    """
    # 단계 1: before_size + 기존 마지막 entry_hash 기록
    before_size = journal_path.stat().st_size if journal_path.exists() else 0
    before_last_entry = load_last_journal_entry(journal_path)
    expected_prev_hash = before_last_entry.get("entry_hash", "")

    # 단계 2: append only
    json_line = json.dumps(entry, ensure_ascii=False)
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(json_line + "\n")

    # 단계 3: 파일 크기 증가 확인
    after_size = journal_path.stat().st_size
    if after_size <= before_size:
        raise RuntimeError(
            f"WORM append failed: file size did not increase "
            f"(before={before_size}, after={after_size})"
        )

    # 단계 4: 마지막 entry 재조회 및 entry_hash 확인
    tail_entry = load_last_journal_entry(journal_path)
    if tail_entry.get("entry_hash") != entry.get("entry_hash"):
        raise RuntimeError(
            f"WORM verification failed: entry_hash mismatch after append. "
            f"expected={entry.get('entry_hash')[:12]}... "
            f"got={tail_entry.get('entry_hash', '')[:12]}..."
        )

    # 단계 5: prev_hash 체인 연속성 확인
    # 신규 entry의 prev_hash는 반드시 append 전 마지막 entry의 entry_hash와 일치해야 함
    if entry.get("prev_hash") != expected_prev_hash:
        raise RuntimeError(
            f"Chain continuity failed: entry.prev_hash does not match "
            f"pre-append last entry_hash. "
            f"expected={expected_prev_hash[:12]}... "
            f"got={entry.get('prev_hash', '')[:12]}..."
        )


# ── main ──────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Append Visibility Metrics to session_journal.jsonl"
    )
    parser.add_argument(
        "--session", type=int, required=True,
        help="Session number (e.g. 222)"
    )
    parser.add_argument(
        "--journal", type=str, default=None,
        help="Override journal path (for testing)"
    )
    parser.add_argument(
        "--sc-root", type=str, default=None,
        help="Override SC_FINAL root path (for testing)"
    )
    args = parser.parse_args()

    journal_path = Path(args.journal) if args.journal else JOURNAL_PATH
    sc_root      = Path(args.sc_root) if args.sc_root else SC_ROOT

    session_num = args.session

    # 중복 확인
    if visibility_entry_exists(journal_path, session_num):
        print(f"[SKIP] VISIBILITY_METRICS_S{session_num} already exists in journal.")
        return 0

    # SC_FINAL 로드
    try:
        sc_final = load_sc_final(session_num, sc_root)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    # visibility_metrics 추출
    try:
        metrics = extract_visibility_metrics(sc_final, session_num)
    except KeyError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 2

    # 마지막 journal entry 로드
    try:
        last_entry = load_last_journal_entry(journal_path)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    prev_hash = last_entry.get("entry_hash", "")
    if not prev_hash:
        print("[ERROR] Last journal entry has no entry_hash", file=sys.stderr)
        return 1

    # entry 생성
    timestamp = _now_iso()
    entry = build_visibility_journal_entry(
        session_num=session_num,
        metrics=metrics,
        prev_hash=prev_hash,
        timestamp=timestamp,
    )

    # WORM append
    try:
        worm_append(journal_path, entry)
    except RuntimeError as e:
        print(f"[ERROR] WORM append failed: {e}", file=sys.stderr)
        return 1

    print(
        f"[OK] VISIBILITY_METRICS_S{session_num} appended. "
        f"entry_hash={entry['entry_hash'][:16]}..."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

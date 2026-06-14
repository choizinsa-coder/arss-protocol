"""
append_auto_route.py
AUTO_ROUTE 항목을 session_journal.jsonl에 WORM append하는 CLI 스크립
EAG: EAG-S244-DEP-G2-003-001
Version: 1.0.0

구조: append_decision.py WORM 구조 복제 (prev_hash 체인, entry_hash SHA256, 5단계 검증, 'a' 모드 only)
사용법:
  python append_auto_route.py --session 244 --route-id AR-S244-001 \
      --prompt-summary "도미 출력 요약" --jeni-ok true --error-occurred false
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

VPS_ROOT     = Path("/opt/arss/engine/arss-protocol")
JOURNAL_PATH = VPS_ROOT / "session_journal" / "session_journal.jsonl"
SCHEMA_VERSION = "v1"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_last_journal_entry(journal_path: Path) -> dict:
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


def auto_route_entry_exists(journal_path: Path, route_id: str) -> bool:
    if not journal_path.exists():
        return False
    with open(journal_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("details", {}).get("id") == route_id:
                    return True
            except json.JSONDecodeError:
                continue
    return False


def compute_entry_hash(payload_without_entry_hash: dict) -> str:
    assert "entry_hash" not in payload_without_entry_hash, (
        "entry_hash must NOT be present in payload before hash computation"
    )
    return _sha256(json.dumps(payload_without_entry_hash, sort_keys=True))


def build_auto_route_entry(
    session_num: int,
    route_id: str,
    prompt_summary: str,
    jeni_ok: bool,
    error_occurred: bool,
    prev_hash: str,
    timestamp: str,
) -> dict:
    details = {
        "id":             route_id,
        "prompt_summary": prompt_summary,
        "jeni_ok":        jeni_ok,
        "error_occurred": error_occurred,
    }
    payload = {
        "session_id":     f"S{session_num}",
        "timestamp":      timestamp,
        "actor":          "caddy",
        "event_type":     "AUTO_ROUTE",
        "details":        details,
        "prev_hash":      prev_hash,
        "schema_version": SCHEMA_VERSION,
    }
    payload["entry_hash"] = compute_entry_hash(payload)
    return payload


def worm_append(journal_path: Path, entry: dict) -> None:
    """WORM 5단계 append + 즉시 검증 (append_decision.py 동일). 실패 시 RuntimeError."""
    before_size = journal_path.stat().st_size if journal_path.exists() else 0
    before_last_entry = load_last_journal_entry(journal_path)
    expected_prev_hash = before_last_entry.get("entry_hash", "")

    json_line = json.dumps(entry, ensure_ascii=False)
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write(json_line + "\n")

    after_size = journal_path.stat().st_size
    if after_size <= before_size:
        raise RuntimeError(f"WORM append failed: size not increased (before={before_size}, after={after_size})")

    tail_entry = load_last_journal_entry(journal_path)
    if tail_entry.get("entry_hash") != entry.get("entry_hash"):
        raise RuntimeError("WORM verification failed: entry_hash mismatch after append")

    if entry.get("prev_hash") != expected_prev_hash:
        raise RuntimeError("Chain continuity failed: prev_hash mismatch")


def _str2bool(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Append AUTO_ROUTE entry to session_journal.jsonl")
    parser.add_argument("--session", type=int, required=True)
    parser.add_argument("--route-id", type=str, required=True)
    parser.add_argument("--prompt-summary", type=str, required=True)
    parser.add_argument("--jeni-ok", type=str, required=True)
    parser.add_argument("--error-occurred", type=str, required=True)
    parser.add_argument("--journal", type=str, default=None)
    args = parser.parse_args()

    journal_path = Path(args.journal) if args.journal else JOURNAL_PATH
    route_id = args.route_id

    if auto_route_entry_exists(journal_path, route_id):
        print(f"[SKIP] {route_id} already exists in journal.")
        return 0

    try:
        last_entry = load_last_journal_entry(journal_path)
    except (FileNotFoundError, RuntimeError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    prev_hash = last_entry.get("entry_hash", "")
    if not prev_hash:
        print("[ERROR] Last journal entry has no entry_hash", file=sys.stderr)
        return 1

    entry = build_auto_route_entry(
        session_num=args.session,
        route_id=route_id,
        prompt_summary=args.prompt_summary,
        jeni_ok=_str2bool(args.jeni_ok),
        error_occurred=_str2bool(args.error_occurred),
        prev_hash=prev_hash,
        timestamp=_now_iso(),
    )

    try:
        worm_append(journal_path, entry)
    except RuntimeError as e:
        print(f"[ERROR] WORM append failed: {e}", file=sys.stderr)
        return 1

    print(f"[OK] {route_id} appended. entry_hash={entry['entry_hash'][:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())

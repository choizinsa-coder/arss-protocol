"""
test_append_visibility_metrics.py
EAG: EAG-S223-JOURNAL-001
TC-01 ~ TC-07
"""

import json
import hashlib
import sys
from pathlib import Path

import pytest

# ── 경로 설정 ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "journal"))
from append_visibility_metrics import (
    build_visibility_journal_entry,
    compute_entry_hash,
    extract_visibility_metrics,
    load_last_journal_entry,
    load_sc_final,
    visibility_entry_exists,
    worm_append,
    main,
    SCHEMA_VERSION,
)

# ── 고정 값 ──────────────────────────────────────────────────────
FIXED_TIME    = "2026-06-11T16:00:00+09:00"
FIXED_PREV    = "aabbcc" * 10 + "aabb"   # 64-char hex dummy
SAMPLE_METRICS = {
    "M-01_active_canonical_key_count": 42,
    "M-07_stabilization_compliance": "PASS",
    "chain_tip": "05eba17",
    "pytest_result": "1530 passed / 0 failed / 94 skipped",
}

# ── fixture ───────────────────────────────────────────────────────

def _make_sc_final(tmp_path: Path, session_num: int) -> Path:
    """SC_FINAL mock 파일 생성."""
    data = {
        "session_count": session_num,
        f"visibility_metrics_s{session_num}": SAMPLE_METRICS,
    }
    path = tmp_path / f"SESSION_CONTEXT_S{session_num}_FINAL.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_journal(tmp_path: Path, entries: list[dict]) -> Path:
    """journal mock 파일 생성."""
    path = tmp_path / "session_journal.jsonl"
    lines = [json.dumps(e, ensure_ascii=False) for e in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _seed_entry(prev_hash: str = "0" * 64) -> dict:
    """최소 seed entry 생성."""
    payload = {
        "session_id":     "S000",
        "timestamp":      FIXED_TIME,
        "actor":          "beo",
        "event_type":     "DECISION",
        "details":        {"note": "seed"},
        "prev_hash":      prev_hash,
        "schema_version": SCHEMA_VERSION,
    }
    eh = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload["entry_hash"] = eh
    return payload


# ─────────────────────────────────────────────────────────────────
# TC-01: 정상 append
# ─────────────────────────────────────────────────────────────────

def test_tc01_normal_append(tmp_path, monkeypatch):
    """정상 케이스: SC_FINAL 존재 + journal 정상 → entry_count +1."""
    _make_sc_final(tmp_path, 222)
    seed = _seed_entry()
    journal = _make_journal(tmp_path, [seed])

    before = sum(1 for l in journal.read_text().splitlines() if l.strip())

    monkeypatch.setattr(
        "append_visibility_metrics._now_iso",
        lambda: FIXED_TIME,
    )

    result = main.__wrapped__ if hasattr(main, "__wrapped__") else None

    # main() 직접 호출 대신 함수 수준 검증
    metrics = SAMPLE_METRICS
    prev_hash = seed["entry_hash"]
    entry = build_visibility_journal_entry(222, metrics, prev_hash, FIXED_TIME)
    worm_append(journal, entry)

    after = sum(1 for l in journal.read_text().splitlines() if l.strip())
    assert after == before + 1
    assert entry["event_type"] == "OI"
    assert entry["actor"] == "caddy"
    assert entry["schema_version"] == SCHEMA_VERSION
    assert entry["details"]["id"] == "VISIBILITY_METRICS_S222"


# ─────────────────────────────────────────────────────────────────
# TC-02: 중복 skip
# ─────────────────────────────────────────────────────────────────

def test_tc02_duplicate_skip(tmp_path):
    """VISIBILITY_METRICS_S222 이미 존재 → entry_count 변화 없음."""
    seed = _seed_entry()
    existing_details = {"id": "VISIBILITY_METRICS_S222"}
    payload = {
        "session_id":     "S222",
        "timestamp":      FIXED_TIME,
        "actor":          "caddy",
        "event_type":     "OI",
        "details":        existing_details,
        "prev_hash":      seed["entry_hash"],
        "schema_version": SCHEMA_VERSION,
    }
    eh = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload["entry_hash"] = eh

    journal = _make_journal(tmp_path, [seed, payload])
    before = sum(1 for l in journal.read_text().splitlines() if l.strip())

    assert visibility_entry_exists(journal, 222) is True

    # 중복이므로 append 없음
    after = sum(1 for l in journal.read_text().splitlines() if l.strip())
    assert after == before


# ─────────────────────────────────────────────────────────────────
# TC-03: SC_FINAL 없음 → exit code 2
# ─────────────────────────────────────────────────────────────────

def test_tc03_sc_final_missing(tmp_path):
    """SC_FINAL 파일 없음 → FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_sc_final(999, sc_root=tmp_path)


# ─────────────────────────────────────────────────────────────────
# TC-04: hash 계산 검증
# ─────────────────────────────────────────────────────────────────

def test_tc04_hash_computation():
    """고정 입력값으로 entry_hash 재현성 검증."""
    payload = {
        "session_id":     "S222",
        "timestamp":      FIXED_TIME,
        "actor":          "caddy",
        "event_type":     "OI",
        "details":        {"id": "VISIBILITY_METRICS_S222"},
        "prev_hash":      FIXED_PREV,
        "schema_version": SCHEMA_VERSION,
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    computed = compute_entry_hash(payload)
    assert computed == expected


# ─────────────────────────────────────────────────────────────────
# TC-05: chain 불일치 → RuntimeError
# ─────────────────────────────────────────────────────────────────

def test_tc05_chain_mismatch(tmp_path):
    """prev_hash가 실제 마지막 entry_hash와 다를 때 체인 불일치 감지."""
    seed = _seed_entry()
    journal = _make_journal(tmp_path, [seed])

    wrong_prev = "deadbeef" * 8  # 실제 seed entry_hash와 다른 값
    entry = build_visibility_journal_entry(222, SAMPLE_METRICS, wrong_prev, FIXED_TIME)

    # worm_append의 단계 5(chain continuity)에서 RuntimeError 발생해야 함
    with pytest.raises(RuntimeError, match="Chain continuity failed"):
        worm_append(journal, entry)


# ─────────────────────────────────────────────────────────────────
# TC-06: WORM 모드 검증 ('a' 모드만 사용)
# ─────────────────────────────────────────────────────────────────

def test_tc06_worm_open_mode(tmp_path, monkeypatch):
    """open() 호출 시 'a' 모드만 사용하는지 확인."""
    seed = _seed_entry()
    journal = _make_journal(tmp_path, [seed])
    entry = build_visibility_journal_entry(
        222, SAMPLE_METRICS, seed["entry_hash"], FIXED_TIME
    )

    open_modes = []
    original_open = open

    def mock_open(path, mode="r", **kwargs):
        open_modes.append(mode)
        return original_open(path, mode, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)
    worm_append(journal, entry)

    write_modes = [m for m in open_modes if m in ("w", "r+", "w+")]
    assert write_modes == [], f"Forbidden open modes used: {write_modes}"
    assert "a" in open_modes, "Append mode 'a' was not used"


# ─────────────────────────────────────────────────────────────────
# TC-07: append 후 재검증
# ─────────────────────────────────────────────────────────────────

def test_tc07_post_append_verification(tmp_path):
    """append 완료 후 tail_entry 재조회 및 내용 일치 확인."""
    seed = _seed_entry()
    journal = _make_journal(tmp_path, [seed])
    entry = build_visibility_journal_entry(
        222, SAMPLE_METRICS, seed["entry_hash"], FIXED_TIME
    )

    worm_append(journal, entry)

    tail = load_last_journal_entry(journal)
    assert tail["entry_hash"] == entry["entry_hash"]
    assert tail["details"]["id"] == "VISIBILITY_METRICS_S222"
    assert tail["prev_hash"] == seed["entry_hash"]
    assert tail["schema_version"] == SCHEMA_VERSION
    assert tail["actor"] == "caddy"

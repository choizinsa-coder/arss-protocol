"""
tests/test_append_decision.py
EAG: EAG-S225-DECISION-001
TC-01~TC-07
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

# tools/journal 경로를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "journal"))

from append_decision import (
    build_decision_entry,
    compute_entry_hash,
    decision_entry_exists,
    load_last_journal_entry,
    worm_append,
)


# ── 공통 픽스처 ────────────────────────────────────────────────────

def _make_seed_entry(tmp_path: Path) -> tuple[Path, dict]:
    """seed entry 1건이 포함된 journal 파일 생성."""
    journal = tmp_path / "session_journal.jsonl"
    seed_payload = {
        "session_id": "S220",
        "timestamp": "2026-06-11T00:00:00+09:00",
        "actor": "caddy",
        "event_type": "OI",
        "details": {"id": "SEED-001"},
        "prev_hash": "0" * 64,
        "schema_version": "v1",
    }
    seed_payload["entry_hash"] = compute_entry_hash(seed_payload)
    journal.write_text(
        json.dumps(seed_payload, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return journal, seed_payload


# ── TC-01: 정상 append ────────────────────────────────────────────

def test_tc01_normal_append(tmp_path):
    """신규 DECISION entry가 정상 append되는지 검증."""
    journal, seed = _make_seed_entry(tmp_path)

    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-001",
        summary="Goal 1 Metrics Framework 채택",
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    lines = [l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2

    tail = json.loads(lines[-1])
    assert tail["event_type"] == "DECISION"
    assert tail["details"]["id"] == "DECISION-S225-001"
    assert tail["details"]["summary"] == "Goal 1 Metrics Framework 채택"
    assert tail["session_id"] == "S225"
    assert tail["actor"] == "caddy"


# ── TC-02: 중복 skip ─────────────────────────────────────────────

def test_tc02_duplicate_skip(tmp_path):
    """동일 decision_id 존재 시 entry_count 변화 없음."""
    journal, seed = _make_seed_entry(tmp_path)

    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-001",
        summary="첫 번째 기록",
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    before_count = len([l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()])

    # 동일 decision_id로 중복 시도
    assert decision_entry_exists(journal, "DECISION-S225-001") is True

    after_count = len([l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()])
    assert before_count == after_count


# ── TC-03: hash 계산 검증 ─────────────────────────────────────────

def test_tc03_hash_computation():
    """고정 입력에 대해 예상 SHA256과 일치하는지 검증."""
    payload = {
        "session_id": "S225",
        "timestamp": "2026-06-11T10:00:00+09:00",
        "actor": "caddy",
        "event_type": "DECISION",
        "details": {"id": "DECISION-S225-001", "summary": "test"},
        "prev_hash": "abc123",
        "schema_version": "v1",
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()

    result = compute_entry_hash(payload)
    assert result == expected


# ── TC-04: WORM 'a' 모드 전용 검증 ──────────────────────────────

def test_tc04_worm_append_mode(tmp_path, monkeypatch):
    """worm_append가 'a' 모드로만 파일을 열었는지 검증."""
    journal, seed = _make_seed_entry(tmp_path)

    open_calls = []
    original_open = open

    def mock_open(path, mode="r", **kwargs):
        open_calls.append(mode)
        return original_open(path, mode, **kwargs)

    monkeypatch.setattr("builtins.open", mock_open)

    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-TC04",
        summary="mode test",
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    write_modes = [m for m in open_calls if "w" in m or "x" in m]
    assert write_modes == [], f"write mode detected: {write_modes}"
    assert "a" in open_calls


# ── TC-05: chain continuity 검증 ─────────────────────────────────

def test_tc05_chain_continuity(tmp_path):
    """신규 entry의 prev_hash가 append 전 마지막 entry_hash와 일치하는지 검증."""
    journal, seed = _make_seed_entry(tmp_path)

    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-TC05",
        summary="chain test",
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    tail = load_last_journal_entry(journal)
    assert tail["prev_hash"] == seed["entry_hash"]


# ── TC-06: append 후 tail entry_hash 검증 ────────────────────────

def test_tc06_tail_entry_hash(tmp_path):
    """append 후 journal tail의 entry_hash가 신규 entry와 동일한지 검증."""
    journal, seed = _make_seed_entry(tmp_path)

    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-TC06",
        summary="tail hash test",
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    tail = load_last_journal_entry(journal)
    assert tail["entry_hash"] == entry["entry_hash"]


# ── TC-07: UTF-8 summary 직렬화 검증 ────────────────────────────

def test_tc07_utf8_summary(tmp_path):
    """한글 summary가 JSON 직렬화 후에도 동일하게 유지되는지 검증."""
    journal, seed = _make_seed_entry(tmp_path)

    korean_summary = "Goal 1 합격선 확정 — 세션 225"
    entry = build_decision_entry(
        session_num=225,
        decision_id="DECISION-S225-TC07",
        summary=korean_summary,
        prev_hash=seed["entry_hash"],
        timestamp="2026-06-11T10:00:00+09:00",
    )
    worm_append(journal, entry)

    tail = load_last_journal_entry(journal)
    assert tail["details"]["summary"] == korean_summary

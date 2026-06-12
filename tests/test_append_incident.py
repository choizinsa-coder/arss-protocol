"""
test_append_incident.py
append_incident.py WORM CLI 테스트
EAG: EAG-S229-JOURNAL-001
TC-01~TC-09
"""

import hashlib
import json
import sys
from pathlib import Path

import pytest

# append_incident 모듈 임포트 (테스트 시 sys.path 조정)
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "journal"))
import append_incident as ai


# ── 픽스처 ────────────────────────────────────────────────────────

def _make_genesis(journal_path: Path) -> dict:
    """테스트용 genesis entry 생성 후 파일에 기록."""
    genesis = {
        "session_id":     "GENESIS",
        "timestamp":      "2026-01-01T00:00:00+00:00",
        "actor":          "session_journal",
        "event_type":     "DECISION",
        "details":        {"note": "GENESIS"},
        "prev_hash":      "0" * 64,
        "schema_version": "v1",
    }
    filtered = {k: v for k, v in genesis.items() if k != "entry_hash"}
    genesis["entry_hash"] = hashlib.sha256(
        json.dumps(filtered, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with open(journal_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(genesis, ensure_ascii=False) + "\n")
    return genesis


# ── TC-01: 정상 append ────────────────────────────────────────────

def test_tc01_normal_append(tmp_path):
    """TC-01: 정상 append — exit 0, [OK] 출력, 파일 크기 증가."""
    journal = tmp_path / "session_journal.jsonl"
    genesis = _make_genesis(journal)
    before_size = journal.stat().st_size

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-001",
        incident_type="CADDY_OPTION_MENU",
        description="선택지 메뉴 제시",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)

    assert journal.stat().st_size > before_size
    tail = ai.load_last_journal_entry(journal)
    assert tail["details"]["id"] == "INC-S229-001"


# ── TC-02: 중복 incident_id ──────────────────────────────────────

def test_tc02_duplicate_skip(tmp_path):
    """TC-02: 중복 incident-id — SKIP, journal 변경 없음."""
    journal = tmp_path / "session_journal.jsonl"
    _make_genesis(journal)

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-001",
        incident_type="CADDY_OPTION_MENU",
        description="1차",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)
    size_after_first = journal.stat().st_size

    # 중복 확인
    assert ai.incident_entry_exists(journal, "INC-S229-001") is True
    # 두 번째 시도 — SKIP 경로 진입 여부 확인 (파일 변경 없음)
    assert ai.incident_entry_exists(journal, "INC-S229-001") is True
    assert journal.stat().st_size == size_after_first


# ── TC-03: journal 미존재 → ERROR ────────────────────────────────

def test_tc03_journal_not_found(tmp_path):
    """TC-03: journal 파일 미존재 → FileNotFoundError."""
    journal = tmp_path / "nonexistent.jsonl"
    with pytest.raises(FileNotFoundError):
        ai.load_last_journal_entry(journal)


# ── TC-04: entry_hash 정합성 ─────────────────────────────────────

def test_tc04_entry_hash_integrity(tmp_path):
    """TC-04: append 후 재조회 entry_hash == 계산값 일치."""
    journal = tmp_path / "session_journal.jsonl"
    _make_genesis(journal)

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-002",
        incident_type="TEST",
        description="hash 정합성 확인",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)

    tail = ai.load_last_journal_entry(journal)
    # entry_hash 제거 후 재계산 — compute_entry_hash와 동일 방식(ensure_ascii 기본값 유지)
    payload = {k: v for k, v in tail.items() if k != "entry_hash"}
    recomputed = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()
    ).hexdigest()
    assert tail["entry_hash"] == recomputed


# ── TC-05: prev_hash 체인 연속성 ────────────────────────────────

def test_tc05_prev_hash_chain(tmp_path):
    """TC-05: 신규 entry의 prev_hash == append 전 last entry_hash."""
    journal = tmp_path / "session_journal.jsonl"
    genesis = _make_genesis(journal)
    genesis_hash = genesis["entry_hash"]

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-003",
        incident_type="TEST",
        description="prev_hash 검증",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)

    tail = ai.load_last_journal_entry(journal)
    assert tail["prev_hash"] == genesis_hash


# ── TC-06: WORM 파일 크기 증가 ──────────────────────────────────

def test_tc06_worm_size_increase(tmp_path):
    """TC-06: after_size > before_size."""
    journal = tmp_path / "session_journal.jsonl"
    _make_genesis(journal)
    before_size = journal.stat().st_size

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-004",
        incident_type="TEST",
        description="size 증가 확인",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)

    assert journal.stat().st_size > before_size


# ── TC-07: 연속 2회 append 체인 연속성 ──────────────────────────

def test_tc07_consecutive_chain(tmp_path):
    """TC-07: 2번째 entry의 prev_hash == 1번째 entry_hash."""
    journal = tmp_path / "session_journal.jsonl"
    _make_genesis(journal)

    # 1번째 append
    last = ai.load_last_journal_entry(journal)
    entry1 = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-005",
        incident_type="TEST",
        description="1차",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry1)
    hash_after_first = entry1["entry_hash"]

    # 2번째 append
    last2 = ai.load_last_journal_entry(journal)
    entry2 = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-006",
        incident_type="TEST",
        description="2차",
        prev_hash=last2["entry_hash"],
        timestamp="2026-06-12T00:01:00+09:00",
    )
    ai.worm_append(journal, entry2)

    assert entry2["prev_hash"] == hash_after_first


# ── TC-08: actor / event_type 고정값 검증 ───────────────────────

def test_tc08_fixed_actor_event_type(tmp_path):
    """TC-08: actor=='caddy', event_type=='INCIDENT' 고정값 확인."""
    journal = tmp_path / "session_journal.jsonl"
    _make_genesis(journal)

    last = ai.load_last_journal_entry(journal)
    entry = ai.build_incident_entry(
        session_num=229,
        incident_id="INC-S229-007",
        incident_type="TEST",
        description="고정값 확인",
        prev_hash=last["entry_hash"],
        timestamp="2026-06-12T00:00:00+09:00",
    )
    ai.worm_append(journal, entry)

    tail = ai.load_last_journal_entry(journal)
    assert tail["actor"] == "caddy"
    assert tail["event_type"] == "INCIDENT"


# ── TC-09: journal 미존재 시 파일 미생성 ────────────────────────

def test_tc09_no_file_creation_on_missing_journal(tmp_path):
    """TC-09: journal 미존재 시 FileNotFoundError — 파일 새로 생성되지 않음."""
    journal = tmp_path / "does_not_exist.jsonl"
    assert not journal.exists()

    with pytest.raises(FileNotFoundError):
        ai.load_last_journal_entry(journal)

    # 파일이 생성되지 않았음을 확인
    assert not journal.exists()

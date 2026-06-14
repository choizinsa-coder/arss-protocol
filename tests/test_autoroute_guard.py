"""
tests/test_autoroute_guard.py
EAG: EAG-S244-DEP-G2-003-001
TC-01~TC-09: append_auto_route WORM + autoroute_caller 가드(B-2/B-3) + 격리
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "journal"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "autoroute"))

from append_auto_route import (
    build_auto_route_entry,
    compute_entry_hash,
    auto_route_entry_exists,
    load_last_journal_entry,
    worm_append,
)
import autoroute_caller as arc


def _make_seed_entry(tmp_path: Path):
    journal = tmp_path / "session_journal.jsonl"
    seed = {
        "session_id": "S243",
        "timestamp": "2026-06-14T00:00:00+09:00",
        "actor": "caddy",
        "event_type": "OI",
        "details": {"id": "SEED-AR-001"},
        "prev_hash": "0" * 64,
        "schema_version": "v1",
    }
    seed["entry_hash"] = compute_entry_hash(seed)
    journal.write_text(json.dumps(seed, ensure_ascii=False) + "\n", encoding="utf-8")
    return journal, seed


# ── TC-01: AUTO_ROUTE 정상 append ──
def test_tc01_auto_route_append(tmp_path):
    journal, seed = _make_seed_entry(tmp_path)
    entry = build_auto_route_entry(244, "AR-S244-001", "도미 출력 요약", True, False, seed["entry_hash"], "2026-06-14T10:00:00+09:00")
    worm_append(journal, entry)
    lines = [l for l in journal.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2
    tail = json.loads(lines[-1])
    assert tail["event_type"] == "AUTO_ROUTE"
    assert tail["details"]["id"] == "AR-S244-001"
    assert tail["details"]["jeni_ok"] is True
    assert tail["details"]["error_occurred"] is False


# ── TC-02: event_type 올바름 (INCIDENT 아님) ──
def test_tc02_event_type_is_auto_route(tmp_path):
    journal, seed = _make_seed_entry(tmp_path)
    entry = build_auto_route_entry(244, "AR-S244-002", "x", False, True, seed["entry_hash"], "2026-06-14T10:00:00+09:00")
    assert entry["event_type"] == "AUTO_ROUTE"
    assert entry["event_type"] != "INCIDENT"


# ── TC-03: hash 계산 검증 ──
def test_tc03_hash_computation():
    payload = {
        "session_id": "S244", "timestamp": "2026-06-14T10:00:00+09:00",
        "actor": "caddy", "event_type": "AUTO_ROUTE",
        "details": {"id": "AR-S244-003", "prompt_summary": "t", "jeni_ok": True, "error_occurred": False},
        "prev_hash": "abc123", "schema_version": "v1",
    }
    expected = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    assert compute_entry_hash(payload) == expected


# ── TC-04: WORM 'a' 모드 전용 ──
def test_tc04_worm_append_mode(tmp_path, monkeypatch):
    journal, seed = _make_seed_entry(tmp_path)
    open_calls = []
    orig = open
    def mock_open(path, mode="r", **kw):
        open_calls.append(mode)
        return orig(path, mode, **kw)
    monkeypatch.setattr("builtins.open", mock_open)
    entry = build_auto_route_entry(244, "AR-S244-TC04", "m", True, False, seed["entry_hash"], "2026-06-14T10:00:00+09:00")
    worm_append(journal, entry)
    write_modes = [m for m in open_calls if "w" in m or "x" in m]
    assert write_modes == []
    assert "a" in open_calls


# ── TC-05: chain continuity ──
def test_tc05_chain_continuity(tmp_path):
    journal, seed = _make_seed_entry(tmp_path)
    entry = build_auto_route_entry(244, "AR-S244-TC05", "c", True, False, seed["entry_hash"], "2026-06-14T10:00:00+09:00")
    worm_append(journal, entry)
    tail = load_last_journal_entry(journal)
    assert tail["prev_hash"] == seed["entry_hash"]


# ── TC-06: 가드 B-3 — 3회 초과 차단 ──
def test_tc06_guard_b3_max_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(arc, "RUNTIME_DIR", tmp_path)
    # 카운터를 3회 도달 상태로 설정
    arc.save_counter(999, {"session_id": "S999", "success_count": 2, "error_count": 1, "schema": arc.SCHEMA})
    result = arc.route(999, "prompt", "", 4)
    assert result["status"] == "BLOCKED_MAX_CALLS"


# ── TC-07: 가드 B-2 — error 누적 2회 기준 값 확인 ──
def test_tc07_guard_b2_constant():
    assert arc.MAX_ERRORS == 2
    assert arc.MAX_CALLS_PER_SESSION == 3


# ── TC-08: 카운터 저장/로드 완전 격리 (SSOT 미오염) ──
def test_tc08_counter_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(arc, "RUNTIME_DIR", tmp_path)
    arc.save_counter(244, {"session_id": "S244", "success_count": 1, "error_count": 0, "schema": arc.SCHEMA})
    loaded = arc.load_counter(244)
    assert loaded["schema"] == "autoroute_counter_v1"
    assert loaded["success_count"] == 1
    # 카운터 파일명에 SESSION_CONTEXT 미포함 (격리 파일명 규칙)
    cp = arc.counter_path(244)
    assert "autoroute_counter" in cp.name
    assert "SESSION_CONTEXT" not in cp.name


# ── TC-09: 신규 카운터 기본값 (0/0) ──
def test_tc09_counter_default(tmp_path, monkeypatch):
    monkeypatch.setattr(arc, "RUNTIME_DIR", tmp_path)
    c = arc.load_counter(555)
    assert c["success_count"] == 0
    assert c["error_count"] == 0
    assert c["schema"] == "autoroute_counter_v1"

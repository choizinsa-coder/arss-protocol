#!/usr/bin/env python3
"""
test_area15_resolved_s450.py
S450: Area 15 resolved(해결됨) 표시 기능 시험 계약 (TC-R1 ~ TC-R9)
EAG: EAG-S450-FAILURE-MEMORY-RESOLVED-001

제니 검증 TRUST_READY 반영본:
  V4-1 중복 키 -> TC-R6
  V4-2 캐시 제거 -> 전역 상태 없음(동일 프로세스 내 재읽기 보장)
  V2   기본값 False -> TC-R9
  C1   3축 키 -> TC-R7
  C2   빈 파일 no-op -> TC-R3 / TC-R4
"""
import inspect
import json

import pytest

import tools.governance.area_15_failure_memory as m15
from tools.governance.area_15_failure_memory import (
    FailureCategory,
    FailureMemoryError,
    get_failure_patterns,
    record_failure,
    record_resolution,
)

RC2 = FailureCategory.RC2
EC = "EXEC:FAIL:s450demo"


@pytest.fixture
def iso(tmp_path, monkeypatch):
    """실제 failure_memory.jsonl / resolved_entries.jsonl 오염 방지."""
    fm = tmp_path / "failure_memory.jsonl"
    rs = tmp_path / "resolved_entries.jsonl"
    monkeypatch.setattr(m15, "LOG_PATH", fm)
    monkeypatch.setattr(m15, "RESOLVED_PATH", rs)
    return fm, rs


def _fail(session, error_code=EC, component="caddy"):
    return record_failure(
        RC2, component, error_code, "s450 demo failure",
        context={"session": session}, actor="test",
    )


def _lines(path):
    if not path.exists():
        return []
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


# ---------------- TC-R1 ----------------
def test_r1_resolution_appended_without_touching_failure_memory(iso):
    fm, rs = iso
    _fail("401")
    _fail("402")
    fm_before = fm.read_text(encoding="utf-8")

    rec = record_resolution("S401", "caddy", EC, "caddy", "s450 demo resolved")

    assert rec["schema"] == "failure_resolution_v1"
    assert rec["session"] == "401"
    assert len(_lines(rs)) == 1
    # failure_memory.jsonl 무변경 (append-only 불변)
    assert fm.read_text(encoding="utf-8") == fm_before


# ---------------- TC-R2 ----------------
@pytest.mark.parametrize("args,missing", [
    (("", "caddy", EC, "caddy", "note"), "session"),
    (("401", "", EC, "caddy", "note"), "component"),
    (("401", "caddy", "", "caddy", "note"), "error_code"),
    (("401", "caddy", EC, "", "note"), "resolved_by"),
    (("401", "caddy", EC, "caddy", ""), "resolution_note"),
])
def test_r2_required_fields_enforced(iso, args, missing):
    with pytest.raises(FailureMemoryError, match=missing):
        record_resolution(*args)


def test_r2b_invalid_component_rejected(iso):
    with pytest.raises(FailureMemoryError, match="Invalid component"):
        record_resolution("401", "not_an_agent", EC, "caddy", "note")


# ---------------- TC-R3 ----------------
def test_r3_absent_resolved_file_is_noop(iso):
    fm, rs = iso
    for s in ("401", "402", "403"):
        _fail(s)
    assert not rs.exists()
    a = get_failure_patterns(window_minutes=1440, threshold=3)
    b = get_failure_patterns(window_minutes=1440, threshold=3, filter_resolved=True)
    assert a == b


# ---------------- TC-R4 ----------------
def test_r4_empty_resolved_file_is_noop(iso):
    fm, rs = iso
    for s in ("401", "402", "403"):
        _fail(s)
    rs.write_text("", encoding="utf-8")
    assert rs.exists()
    a = get_failure_patterns(window_minutes=1440, threshold=3)
    b = get_failure_patterns(window_minutes=1440, threshold=3, filter_resolved=True)
    assert a == b


# ---------------- TC-R5 (핵심 계약) ----------------
def test_r5_resolution_clears_cross_session_repeat(iso):
    fm, rs = iso
    for s in ("401", "402", "403"):
        _fail(s)

    before = get_failure_patterns(window_minutes=1440, threshold=3)
    hit = [c for c in before["cross_session_repeat"] if c["error_code"] == EC]
    assert len(hit) == 1
    assert hit[0]["distinct_sessions"] == 3

    record_resolution("401", "caddy", EC, "caddy", "resolved in s450")

    after = get_failure_patterns(window_minutes=1440, threshold=3,
                                filter_resolved=True)
    assert [c for c in after["cross_session_repeat"] if c["error_code"] == EC] == []

    # 필터 미적용 경로는 종전 그대로 (기존 호출자 무영향)
    unfiltered = get_failure_patterns(window_minutes=1440, threshold=3)
    assert [c for c in unfiltered["cross_session_repeat"]
            if c["error_code"] == EC][0]["distinct_sessions"] == 3


# ---------------- TC-R6 ----------------
def test_r6_duplicate_resolution_rows_are_idempotent(iso):
    fm, rs = iso
    for s in ("401", "402", "403"):
        _fail(s)
    for _ in range(3):
        record_resolution("401", "caddy", EC, "caddy", "dup")
    assert len(_lines(rs)) == 3
    assert len(m15._load_resolved_keys()) == 1

    single = tmp_equivalent = get_failure_patterns(
        window_minutes=1440, threshold=3, filter_resolved=True)
    assert [c for c in single["cross_session_repeat"]
            if c["error_code"] == EC] == []


# ---------------- TC-R7 (과잉 필터 회귀 방지) ----------------
def test_r7_key_requires_all_three_axes(iso):
    fm, rs = iso
    _fail("500", error_code="EC-A")
    _fail("500", error_code="EC-B")
    record_resolution("500", "caddy", "EC-A", "caddy", "only EC-A resolved")

    keys = m15._load_resolved_keys()
    assert ("500", "caddy", "EC-A") in keys

    entries = m15._load_all_entries()
    remaining = [e for e in entries if m15._resolution_key(e) not in keys]
    assert len(remaining) == 1
    assert remaining[0]["error_code"] == "EC-B"


def test_r7b_different_session_not_excluded(iso):
    fm, rs = iso
    _fail("600")
    _fail("601")
    record_resolution("600", "caddy", EC, "caddy", "only s600")
    keys = m15._load_resolved_keys()
    remaining = [e for e in m15._load_all_entries()
                 if m15._resolution_key(e) not in keys]
    assert len(remaining) == 1
    assert m15._entry_session(remaining[0]) == "601"


# ---------------- TC-R8 ----------------
def test_r8_record_failure_unaffected_after_resolution(iso):
    fm, rs = iso
    _fail("401")
    record_resolution("401", "caddy", EC, "caddy", "note")
    entry = _fail("404")
    assert entry["schema"] == "failure_memory_v1"
    assert len(_lines(fm)) == 2
    assert len(_lines(rs)) == 1


# ---------------- TC-R9 ----------------
def test_r9_filter_resolved_defaults_to_false(iso):
    sig = inspect.signature(get_failure_patterns)
    assert "filter_resolved" in sig.parameters
    assert sig.parameters["filter_resolved"].default is False


def test_r9b_resolution_record_shape(iso):
    fm, rs = iso
    record_resolution("S777", "CADDY", " EC-X ", "caddy", "shape check")
    rec = json.loads(_lines(rs)[0])
    for k in m15.RESOLUTION_REQUIRED_FIELDS:
        assert k in rec and rec[k]
    assert rec["session"] == "777"
    assert rec["component"] == "caddy"
    assert rec["error_code"] == "EC-X"

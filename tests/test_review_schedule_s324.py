#!/usr/bin/env python3
"""
test_review_schedule_s324.py
Always-On Phase 1: review_schedule init/preserve tests (3 tests)
EAG: EAG-S324-REVIEW-SCHEDULE-001
"""
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/close")
from session_close_generator import apply_delta

_DELTA = {
    "session_reentry":         {"resume_point": "test", "eag_carryover": ""},
    "next_steps":              [],
    "agent_focus":             {},
    "pytest_status":           {"total_passed": 0, "total_failed": 0, "total_skipped": 0, "last_run_session": 324},
    "system_changes":          {"deployed_session": 324, "commits": [], "changes": [], "eag_chain": ""},
    "caddy_governance_record": {"session": 324, "eag_gates_this_session": [], "incidents": [], "oi_observations": [], "caddy_self_report": [], "notable": ""},
    "visibility_metrics":      {"session": 324},
    "session_delta":           {"from_session": 323, "to_session": 324, "summary": "test", "incident_count": 0, "eag_count": 0},
    "sync_meta":               {"last_close_session": 324, "close_method": "test", "verified": False},
}

def _base_sc():
    return {"session_count": 323, "chain": {"session": 323, "prev_tip": "abc", "tip": "def"}}


# Test 1: review_schedule 미존재 시 초기화
def test_review_schedule_initialized():
    sc = _base_sc()
    assert "review_schedule" not in sc
    result, _ = apply_delta(sc, 324, "tip1", "ptip1", _DELTA)
    assert "review_schedule" in result
    rs = result["review_schedule"]
    assert "weekly_failure_audit" in rs
    assert "monthly_assumption_review" in rs
    assert "quarterly_constitution_review" in rs


# Test 2: 기존 review_schedule 보존 (덮어쓰기 금지)
def test_review_schedule_preserved():
    sc = _base_sc()
    sc["review_schedule"] = {
        "weekly_failure_audit": {"last_run": "2026-07-04", "next_due": "2026-07-11"},
        "monthly_assumption_review": {"last_run": None, "next_due": "2026-08-01"},
        "quarterly_constitution_review": {"last_run": None, "next_due": "2026-10-01"},
    }
    result, _ = apply_delta(sc, 324, "tip2", "ptip2", _DELTA)
    assert result["review_schedule"]["weekly_failure_audit"]["last_run"] == "2026-07-04"


# Test 3: 초기화된 review_schedule 스키마 검증
def test_review_schedule_schema():
    sc = _base_sc()
    result, _ = apply_delta(sc, 324, "tip3", "ptip3", _DELTA)
    rs = result["review_schedule"]
    for key in ("weekly_failure_audit", "monthly_assumption_review", "quarterly_constitution_review"):
        assert key in rs, f"{key} missing"
        assert "last_run" in rs[key]
        assert "next_due" in rs[key]
        assert rs[key]["last_run"] is None
        assert rs[key]["next_due"] is not None


# Test 4 (EAG-S385): review_completed -> last_run/next_due updated
def test_review_completed_updates():
    from datetime import datetime, timezone, timedelta
    _KST = timezone(timedelta(hours=9))
    sc = _base_sc()
    sc["review_schedule"] = {
        "weekly_failure_audit": {"last_run": None, "next_due": "2026-07-11"},
        "monthly_assumption_review": {"last_run": None, "next_due": "2026-08-01"},
        "quarterly_constitution_review": {"last_run": None, "next_due": "2026-10-01"},
    }
    d = dict(_DELTA)
    d["review_completed"] = ["weekly_failure_audit"]
    result, _ = apply_delta(sc, 385, "tip4", "ptip4", d)
    k = datetime.now(_KST)
    w = result["review_schedule"]["weekly_failure_audit"]
    assert w["last_run"] == k.strftime("%Y-%m-%d")
    assert w["next_due"] == (k + timedelta(days=7)).strftime("%Y-%m-%d")


# Test 5 (EAG-S385): non-completed entries untouched
def test_review_completed_scoped():
    sc = _base_sc()
    sc["review_schedule"] = {
        "weekly_failure_audit": {"last_run": None, "next_due": "2026-07-11"},
        "monthly_assumption_review": {"last_run": None, "next_due": "2026-08-01"},
        "quarterly_constitution_review": {"last_run": None, "next_due": "2026-10-01"},
    }
    d = dict(_DELTA)
    d["review_completed"] = ["weekly_failure_audit"]
    result, _ = apply_delta(sc, 385, "tip5", "ptip5", d)
    m = result["review_schedule"]["monthly_assumption_review"]
    assert m["last_run"] is None
    assert m["next_due"] == "2026-08-01"


# Test 6 (EAG-S385): no review_completed -> preserve (regression)
def test_review_completed_absent_preserves():
    sc = _base_sc()
    sc["review_schedule"] = {
        "weekly_failure_audit": {"last_run": "2026-07-04", "next_due": "2026-07-11"},
    }
    result, _ = apply_delta(sc, 385, "tip6", "ptip6", dict(_DELTA))
    w = result["review_schedule"]["weekly_failure_audit"]
    assert w["last_run"] == "2026-07-04"
    assert w["next_due"] == "2026-07-11"

#!/usr/bin/env python3
"""
test_aif_area7_org_learning.py
AIF Area 7: Organizational Learning Engine test suite (12 tests)
EAG: EAG-S324-AIF-AREA7-001
"""
import pytest
from datetime import date, timedelta
from unittest.mock import patch

import tools.governance.area_7_org_learning as m7
from tools.governance.area_7_org_learning import (
    LearningEngineError,
    OrgLearningEngine,
    VERSION,
    EAG_ID,
)

_NO_ALERT = {
    "has_alert": False,
    "consecutive_repeat": [],
    "frequency_burst": [],
    "cross_component": [],
    "window_minutes": 43200,
    "threshold": 3,
}
_NO_FAIL_SNAP = {"total_failed": 0, "total_passed": 1869}


# 01: record_learning basic
def test_01_record_learning_success(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    entry = engine.record_learning(
        source="failure",
        content="RC-2 PowerShell nested quote issue",
        area_ref="area_15",
        confidence=0.9,
        actor="caddy",
    )
    assert entry["id"].startswith("L-")
    assert entry["schema"] == "learning_log_v1"
    assert entry["version"] == VERSION
    assert entry["source"] == "failure"
    assert entry["confidence"] == 0.9
    assert entry["eag"] == EAG_ID
    assert "recorded_at" in entry


# 02: record_learning invalid source
def test_02_record_learning_invalid_source(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="source"):
        engine.record_learning(
            source="INVALID",
            content="some content",
            area_ref="area_15",
            confidence=0.5,
        )


# 03: record_learning empty content
def test_03_record_learning_empty_content(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="content"):
        engine.record_learning(
            source="outcome",
            content="   ",
            area_ref="area_13",
            confidence=0.5,
        )


# 04: record_learning confidence out of range
def test_04_record_learning_confidence_out_of_range(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="confidence"):
        engine.record_learning(
            source="review",
            content="valid content",
            area_ref="area_7",
            confidence=1.5,
        )


# 05: detect_improvement_opportunities no issues
def test_05_detect_improvement_no_issues(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=_NO_FAIL_SNAP):
            result = engine.detect_improvement_opportunities()
    assert result == []


# 06: detect_improvement failure_repeat
def test_06_detect_improvement_failure_repeat(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    alert_patterns = {
        "has_alert": True,
        "consecutive_repeat": [{"component": "caddy", "error_code": "RC-2", "count": 4}],
        "frequency_burst": [],
        "cross_component": [],
        "window_minutes": 43200,
        "threshold": 3,
    }
    with patch.object(m7, "_get_failure_patterns", return_value=alert_patterns):
        with patch.object(m7, "_get_current_snapshot", return_value=_NO_FAIL_SNAP):
            result = engine.detect_improvement_opportunities()
    assert len(result) >= 1
    assert result[0]["trigger"] == "failure_repeat"
    assert result[0]["priority"] in ("HIGH", "CRITICAL")


# 07: detect_improvement ghs_decline
def test_07_detect_improvement_ghs_decline(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    fail_snap = {"total_failed": 3, "total_passed": 1866}
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=fail_snap):
            result = engine.detect_improvement_opportunities()
    assert any(r["trigger"] == "ghs_decline" for r in result)


# 08: generate_improvement_proposal basic
def test_08_generate_improvement_proposal_basic(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    prop = engine.generate_improvement_proposal(
        trigger="failure_repeat",
        description="Area 15: RC-2 caddy consecutive 4x",
        priority="HIGH",
        actor="area_7_scheduler",
    )
    assert prop["id"].startswith("IP-")
    assert prop["schema"] == "improvement_proposal_v1"
    assert prop["trigger"] == "failure_repeat"
    assert prop["priority"] == "HIGH"
    assert prop["eag"] == EAG_ID


# 09: generate_proposal status always pending_eag
def test_09_generate_proposal_status_pending_eag(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    prop = engine.generate_improvement_proposal(
        trigger="ghs_decline",
        description="GHS decline detected",
        priority="MEDIUM",
    )
    assert prop["status"] == "pending_eag"
    assert prop["constitution_review_proposal"] is None
    assert prop["self_improvement_debt"] is None


# 10: check_review_schedule_overdue
def test_10_check_review_schedule_overdue(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    yesterday  = (date.today() - timedelta(days=2)).isoformat()
    next_week  = (date.today() + timedelta(days=7)).isoformat()
    schedule = {
        "weekly_failure_audit":     {"last_run": None, "next_due": yesterday},
        "monthly_assumption_review": {"last_run": None, "next_due": next_week},
    }
    result = engine.check_review_schedule_overdue(schedule)
    assert result["overdue"] is True
    assert len(result["overdue_items"]) == 1
    assert result["overdue_items"][0]["review_type"] == "weekly_failure_audit"
    assert result["overdue_items"][0]["days_overdue"] >= 1
    assert result["next_upcoming"]["review_type"] == "monthly_assumption_review"


# 11: get_learning_summary
def test_11_get_learning_summary(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    engine.record_learning("failure", "learning 1", "area_15", 0.8)
    engine.record_learning("outcome", "learning 2", "area_11", 0.7)
    engine.record_learning("failure", "learning 3", "area_15", 0.9)
    summary = engine.get_learning_summary()
    assert summary["schema"] == "learning_summary_v1"
    assert summary["total_count"] == 3
    assert summary["source_counts"]["failure"] == 2
    assert summary["source_counts"]["outcome"] == 1
    assert len(summary["recent_5"]) == 3


# 12: get_pending_proposals filter
def test_12_get_pending_proposals_filter(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    engine.generate_improvement_proposal("failure_repeat",   "high priority issue",    "HIGH")
    engine.generate_improvement_proposal("ghs_decline",      "medium priority issue",  "MEDIUM")
    engine.generate_improvement_proposal("schedule_overdue", "critical issue",         "CRITICAL")
    all_pending = engine.get_pending_proposals()
    high_only   = engine.get_pending_proposals(priority_filter="HIGH")
    assert len(all_pending) == 3
    assert len(high_only)   == 1
    assert high_only[0]["priority"] == "HIGH"

# ===== Phase 2 Tests (EAG-S327-AIF-AREA7-P2-001) =====

# 13: propose_constitution_review basic
def test_13_propose_constitution_review_basic(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    result = engine.propose_constitution_review(
        reason="VPS access policy needs revision",
        proposer="caddy",
        priority="HIGH",
    )
    assert result["id"].startswith("CR-")
    assert result["schema"] == "constitution_review_v1"
    assert result["reason"] == "VPS access policy needs revision"
    assert result["proposer"] == "caddy"
    assert result["priority"] == "HIGH"
    assert result["status"] == "pending"
    assert result["eag"] == "EAG-S327-AIF-AREA7-P2-001"
    assert "created_at" in result
    # jsonl file written
    cr_log = tmp_path / "constitution_review_log.jsonl"
    assert cr_log.exists()
    lines = [l for l in cr_log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# 14: propose_constitution_review invalid priority
def test_14_propose_constitution_review_invalid_priority(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="priority"):
        engine.propose_constitution_review(
            reason="some reason",
            proposer="caddy",
            priority="INVALID",
        )


# 15: propose_constitution_review empty reason
def test_15_propose_constitution_review_empty_reason(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="reason"):
        engine.propose_constitution_review(
            reason="   ",
            proposer="caddy",
            priority="MEDIUM",
        )


# 16: record_improvement_debt basic
def test_16_record_improvement_debt_basic(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    result = engine.record_improvement_debt(
        description="Area 6 WF-05 dispatch not yet live",
        area="area_6",
        debt_type="IMPL",
        estimated_sessions=2,
        actor="caddy",
    )
    assert result["id"].startswith("IMP-")
    assert result["schema"] == "improvement_debt_v1"
    assert result["description"] == "Area 6 WF-05 dispatch not yet live"
    assert result["area"] == "area_6"
    assert result["debt_type"] == "IMPL"
    assert result["estimated_sessions"] == 2
    assert result["status"] == "open"
    assert result["eag"] == "EAG-S327-AIF-AREA7-P2-001"
    # jsonl file written
    debt_log = tmp_path / "improvement_debt_log.jsonl"
    assert debt_log.exists()
    lines = [l for l in debt_log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


# 17: record_improvement_debt invalid debt_type
def test_17_record_improvement_debt_invalid_debt_type(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="debt_type"):
        engine.record_improvement_debt(
            description="some debt",
            area="area_7",
            debt_type="INVALID",
            estimated_sessions=1,
        )


# 18: record_improvement_debt invalid estimated_sessions
def test_18_record_improvement_debt_invalid_sessions(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with pytest.raises(LearningEngineError, match="estimated_sessions"):
        engine.record_improvement_debt(
            description="some debt",
            area="area_7",
            debt_type="TEST",
            estimated_sessions=0,
        )

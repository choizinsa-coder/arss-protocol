#!/usr/bin/env python3
"""
test_aif_area15_failure_memory.py
AIF Area 15: Failure Memory System 테스트
EAG: EAG-S322-AIF-AREA15-001
"""
import pytest
from unittest.mock import patch
from pathlib import Path

import tools.governance.area_15_failure_memory as m15
from tools.governance.area_15_failure_memory import (
    FailureCategory,
    FailureMemoryError,
    record_failure,
    _load_all_entries,
    get_failures_by_rc,
    get_recent_failures,
    get_failure_patterns,
    get_m04_contribution,
    get_m05_contribution,
    get_failure_summary,
)


@pytest.fixture(autouse=True)
def patch_log_path(tmp_path):
    stub = tmp_path / "failure_memory.jsonl"
    with patch.object(m15, "LOG_PATH", stub):
        yield stub


def test_failure_category_enum_values():
    assert FailureCategory.RC1.value == "RC-1"
    assert FailureCategory.RC2.value == "RC-2"
    assert FailureCategory.RC3.value == "RC-3"
    assert FailureCategory.RC4.value == "RC-4"


def test_failure_category_requires_escalation():
    assert FailureCategory.RC1.requires_escalation is False
    assert FailureCategory.RC2.requires_escalation is False
    assert FailureCategory.RC3.requires_escalation is True
    assert FailureCategory.RC4.requires_escalation is True


def test_record_failure_rc1_basic():
    entry = record_failure(
        FailureCategory.RC1, "caddy", "CB-001", "circuit breaker triggered"
    )
    assert entry["schema"] == "failure_memory_v1"
    assert entry["rc"] == "RC-1"
    assert entry["component"] == "caddy"
    assert entry["error_code"] == "CB-001"
    assert entry["description"] == "circuit breaker triggered"


def test_record_failure_rc2_basic():
    entry = record_failure(
        FailureCategory.RC2, "domi", "ZPB-002", "zero progress breaker"
    )
    assert entry["rc"] == "RC-2"
    assert entry["component"] == "domi"
    assert "recorded_at" in entry


def test_record_failure_rc3_with_context_succeeds():
    entry = record_failure(
        FailureCategory.RC3,
        "jeni",
        "TRUST-FAIL-001",
        "trust verification failed repeatedly",
        context={"session": "S322", "rounds": 3},
    )
    assert entry["rc"] == "RC-3"
    assert entry["context"]["session"] == "S322"


def test_record_failure_rc4_with_context_succeeds():
    entry = record_failure(
        FailureCategory.RC4,
        "system",
        "CHAIN-CORRUPT-001",
        "chain integrity violation",
        context={"session": "S322", "hash": "abc123"},
    )
    assert entry["rc"] == "RC-4"
    assert entry["context"]["hash"] == "abc123"


def test_record_failure_schema_fields():
    entry = record_failure(
        FailureCategory.RC1, "caddy", "CB-001", "test", actor="caddy"
    )
    required = {"schema", "version", "rc", "component", "error_code",
                "description", "context", "actor", "recorded_at"}
    assert required.issubset(entry.keys())
    assert entry["version"] == "1.0.0"
    assert entry["actor"] == "caddy"


def test_record_failure_appends_to_jsonl():
    record_failure(FailureCategory.RC1, "caddy", "CB-001", "first")
    record_failure(FailureCategory.RC2, "domi", "ZPB-001", "second")
    entries = _load_all_entries()
    assert len(entries) == 2


def test_record_failure_empty_description_raises():
    with pytest.raises(FailureMemoryError, match="description"):
        record_failure(FailureCategory.RC1, "caddy", "CB-001", "")


def test_record_failure_empty_error_code_raises():
    with pytest.raises(FailureMemoryError, match="error_code"):
        record_failure(FailureCategory.RC1, "caddy", "", "some desc")


def test_record_failure_invalid_component_raises():
    with pytest.raises(FailureMemoryError, match="Invalid component"):
        record_failure(FailureCategory.RC1, "invalid_agent", "CB-001", "desc")


def test_record_failure_rc3_no_context_raises():
    with pytest.raises(FailureMemoryError, match="context is required"):
        record_failure(FailureCategory.RC3, "caddy", "INC-001", "critical failure")


def test_record_failure_rc4_no_context_raises():
    with pytest.raises(FailureMemoryError, match="context is required"):
        record_failure(FailureCategory.RC4, "system", "FATAL-001", "catastrophic")


def test_get_failures_by_rc():
    record_failure(FailureCategory.RC1, "caddy", "CB-001", "first")
    record_failure(FailureCategory.RC2, "domi", "ZPB-001", "second")
    record_failure(FailureCategory.RC1, "jeni", "CB-002", "third")
    rc1_entries = get_failures_by_rc(FailureCategory.RC1)
    assert len(rc1_entries) == 2
    assert all(e["rc"] == "RC-1" for e in rc1_entries)


def test_get_failures_by_rc_empty():
    result = get_failures_by_rc(FailureCategory.RC4)
    assert result == []


def test_get_recent_failures():
    for i in range(5):
        record_failure(FailureCategory.RC1, "caddy", "CB-{:03d}".format(i), "failure {}".format(i))
    recent = get_recent_failures(3)
    assert len(recent) == 3


def test_get_recent_failures_empty():
    result = get_recent_failures()
    assert result == []


def test_get_failure_patterns_empty():
    result = get_failure_patterns()
    assert result["has_alert"] is False
    assert result["consecutive_repeat"] == []
    assert result["frequency_burst"] == []
    assert result["cross_component"] == []


def test_get_failure_patterns_consecutive():
    for _ in range(3):
        record_failure(FailureCategory.RC1, "caddy", "CB-001", "repeated error")
    result = get_failure_patterns(threshold=3)
    assert len(result["consecutive_repeat"]) == 1
    assert result["consecutive_repeat"][0]["component"] == "caddy"
    assert result["has_alert"] is True


def test_get_m04_contribution():
    record_failure(FailureCategory.RC1, "caddy", "CB-001", "cb event")
    record_failure(FailureCategory.RC2, "domi", "ZPB-001", "zpb event")
    result = get_m04_contribution(window_minutes=1440)
    assert result["metric"] == "M04"
    assert result["count"] == 2


def test_get_m05_contribution():
    record_failure(
        FailureCategory.RC2, "caddy", "INC-001", "incident",
        context={"session": "S322"}
    )
    record_failure(FailureCategory.RC1, "caddy", "CB-001", "non-incident")
    result = get_m05_contribution("S322")
    assert result["metric"] == "M05"
    assert result["count"] == 1


def test_get_failure_summary_empty():
    result = get_failure_summary()
    assert result["schema"] == "failure_memory_summary_v1"
    assert result["total_count"] == 0
    assert result["recent_5"] == []


def test_get_failure_summary():
    record_failure(FailureCategory.RC1, "caddy", "CB-001", "first")
    record_failure(FailureCategory.RC2, "domi", "ZPB-001", "second")
    result = get_failure_summary()
    assert result["total_count"] == 2
    assert "RC-1" in result["rc_counts"]
    assert "RC-2" in result["rc_counts"]
    assert result["eag"] == "EAG-S322-AIF-AREA15-001"

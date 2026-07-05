import pytest
from tools.governance.area_7_org_learning import OrgLearningEngine

NOW = "2026-07-06T00:00:00+00:00"

def _engine(tmp_path):
    return OrgLearningEngine(log_dir=tmp_path)

def test_ch3_init_state(tmp_path):
    e = _engine(tmp_path)
    assert e._prev_context_hash is None
    assert e._prev_dl_total is None

def test_ch3_source_a_high(tmp_path):
    e = _engine(tmp_path)
    e._prev_dl_total = 10
    e._get_decision_summary = lambda: {"total_count": 12, "class_counts": {"DC-3": 3, "DC-4": 2}}
    e._get_context_hash = lambda: None
    res = e._detect_ch3_external_change(NOW)
    assert len(res) == 1
    assert res[0]["trigger"] == "external"
    assert res[0]["priority"] == "HIGH"
    assert res[0]["source_ref"]["area"] == "area_11"

def test_ch3_source_a_medium(tmp_path):
    e = _engine(tmp_path)
    e._prev_dl_total = 10
    e._get_decision_summary = lambda: {"total_count": 15, "class_counts": {"DC-3": 1, "DC-4": 0}}
    e._get_context_hash = lambda: None
    res = e._detect_ch3_external_change(NOW)
    assert len(res) == 1
    assert res[0]["priority"] == "MEDIUM"
    assert res[0]["source_ref"]["detail"]["current_total"] == 15

def test_ch3_source_b_high(tmp_path):
    e = _engine(tmp_path)
    e._prev_context_hash = "abc12345old"
    e._prev_dl_total = 5
    e._get_decision_summary = lambda: {"total_count": 5, "class_counts": {"DC-3": 0, "DC-4": 0}}
    e._get_context_hash = lambda: "def67890new"
    res = e._detect_ch3_external_change(NOW)
    assert len(res) == 1
    assert res[0]["priority"] == "HIGH"
    assert res[0]["source_ref"]["area"] == "session_pointer"

def test_ch3_no_change(tmp_path):
    e = _engine(tmp_path)
    e._prev_dl_total = 5
    e._prev_context_hash = "same"
    e._get_decision_summary = lambda: {"total_count": 5, "class_counts": {"DC-3": 1, "DC-4": 1}}
    e._get_context_hash = lambda: "same"
    res = e._detect_ch3_external_change(NOW)
    assert res == []

def test_ch3_first_call_baseline(tmp_path):
    e = _engine(tmp_path)
    e._get_decision_summary = lambda: {"total_count": 99, "class_counts": {"DC-3": 9, "DC-4": 9}}
    e._get_context_hash = lambda: "firsthash"
    res = e._detect_ch3_external_change(NOW)
    assert res == []
    assert e._prev_dl_total == 99
    assert e._prev_context_hash == "firsthash"

def test_ch3_none_sources_isolation(tmp_path):
    e = _engine(tmp_path)
    e._prev_dl_total = 5
    e._prev_context_hash = "x"
    e._get_decision_summary = lambda: None
    e._get_context_hash = lambda: None
    res = e._detect_ch3_external_change(NOW)
    assert res == []


#!/usr/bin/env python3
"""
test_aif_area14_shadow_sim.py
AIF Area 14: Shadow Simulation test suite (12 tests)
EAG: EAG-S324-AIF-AREA14-001
"""
import pytest
from tools.governance.area_14_shadow_sim import (
    ShadowSimError, ShadowSimEngine, VERSION, EAG_ID,
)


# 01: record_shadow_run basic
def test_01_record_shadow_run_basic(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    r = e.record_shadow_run(
        scenario_id="S324-AREA6-DEPLOY",
        description="Deploy Area 6 without breaking Area 11",
        target_area="area_6",
        predicted_outcome="success",
        risk_level="LOW",
        confidence=0.9,
    )
    assert r["id"].startswith("SIM-")
    assert r["schema"] == "shadow_run_v1"
    assert r["version"] == VERSION
    assert r["predicted_outcome"] == "success"
    assert r["risk_level"] == "LOW"
    assert r["confidence"] == 0.9
    assert r["eag"] == EAG_ID


# 02: record_shadow_run empty scenario_id
def test_02_record_shadow_run_empty_scenario_id(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="scenario_id"):
        e.record_shadow_run("", "desc", "area_7", "success", "LOW", 0.5)


# 03: record_shadow_run invalid risk_level
def test_03_record_shadow_run_invalid_risk_level(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="risk_level"):
        e.record_shadow_run("S1", "desc", "area_7", "success", "EXTREME", 0.5)


# 04: record_shadow_run invalid confidence
def test_04_record_shadow_run_invalid_confidence(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="confidence"):
        e.record_shadow_run("S1", "desc", "area_7", "success", "HIGH", 1.5)


# 05: record_shadow_run invalid predicted_outcome
def test_05_record_shadow_run_invalid_outcome(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="predicted_outcome"):
        e.record_shadow_run("S1", "desc", "area_7", "INVALID", "HIGH", 0.5)


# 06: record_interlock_rule basic
def test_06_record_interlock_rule_basic(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    r = e.record_interlock_rule(
        rule_id="ILK-RC3-AREA7",
        trigger_area="area_15",
        trigger_condition="rc3_repeat",
        blocked_area="area_7",
        reason="RC-3 repeat blocks Area 7 self-improvement",
    )
    assert r["id"].startswith("ILK-")
    assert r["schema"] == "interlock_rule_v1"
    assert r["trigger_condition"] == "rc3_repeat"
    assert r["blocked_area"] == "area_7"
    assert r["eag"] == EAG_ID


# 07: record_interlock_rule empty blocked_area
def test_07_record_interlock_rule_empty_blocked_area(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="blocked_area"):
        e.record_interlock_rule("R1", "area_15", "rc3_repeat", "", "reason")


# 08: record_interlock_rule invalid trigger_condition
def test_08_record_interlock_rule_invalid_condition(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError, match="trigger_condition"):
        e.record_interlock_rule("R1", "area_15", "INVALID", "area_7", "reason")


# 09: check_interlock matching
def test_09_check_interlock_matching(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule("ILK-1", "area_15", "rc3_repeat",          "area_7", "reason A")
    e.record_interlock_rule("ILK-2", "area_13", "ghs_below_threshold", "area_7", "reason B")
    e.record_interlock_rule("ILK-3", "area_15", "rc3_repeat",          "area_6", "reason C")
    result = e.check_interlock("area_7")
    assert len(result) == 2
    assert all(r["blocked_area"] == "area_7" for r in result)


# 10: check_interlock no match
def test_10_check_interlock_no_match(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule("ILK-1", "area_15", "rc3_repeat", "area_7", "reason")
    result = e.check_interlock("area_99")
    assert result == []


# 11: get_shadow_summary
def test_11_get_shadow_summary(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_shadow_run("SC-ALPHA", "Test A", "area_7", "success",  "LOW",    0.9)
    e.record_shadow_run("SC-ALPHA", "Test B", "area_7", "failure",  "HIGH",   0.6)
    e.record_shadow_run("SC-BETA",  "Test C", "area_6", "uncertain","MEDIUM", 0.5)
    summary = e.get_shadow_summary("SC-ALPHA")
    assert summary["schema"] == "shadow_summary_v1"
    assert summary["scenario_id"] == "SC-ALPHA"
    assert summary["total_runs"] == 2
    assert len(summary["runs"]) == 2


# 12: get_simulation_status
def test_12_get_simulation_status(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_shadow_run("S1", "desc", "area_7", "success", "HIGH",   0.8)
    e.record_shadow_run("S1", "desc", "area_6", "failure", "LOW",    0.6)
    e.record_shadow_run("S2", "desc", "area_4", "success", "MEDIUM", 0.7)
    e.record_interlock_rule("R1", "area_15", "rc3_repeat", "area_7", "reason")
    status = e.get_simulation_status()
    assert status["schema"] == "simulation_status_v1"
    assert status["sim_total"] == 3
    assert status["sim_by_risk"]["HIGH"] == 1
    assert status["sim_by_outcome"]["success"] == 2
    assert status["interlock_rules"] == 1


from unittest.mock import patch, MagicMock
import json as _jmod


# 13: run_simulation_llm mock success
def test_13_run_simulation_llm_success(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_shadow_run(
        scenario_id="SC-s328-01", description="test scenario",
        target_area="area_6", predicted_outcome="uncertain",
        risk_level="MEDIUM", confidence=0.5,
    )
    inner = {"predicted_outcome": "success", "risk_level": "LOW", "confidence": 0.9, "reasoning": "ok"}
    resp_d = {"ok": True, "text": _jmod.dumps(inner)}
    rbytes = _jmod.dumps(resp_d).encode("utf-8")
    mock_h = MagicMock()
    mock_h.read.return_value = rbytes
    with patch("urllib.request.urlopen") as mu:
        mu.return_value.__enter__ = MagicMock(return_value=mock_h)
        mu.return_value.__exit__ = MagicMock(return_value=False)
        result = e.run_simulation_llm("SC-s328-01", session="S328")
    assert result["source"] == "llm_simulation"
    assert result["predicted_outcome"] == "success"
    assert result["risk_level"] == "LOW"
    assert abs(result["confidence"] - 0.9) < 0.01


# 14: run_simulation_llm URLError
def test_14_run_simulation_llm_unreachable(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_shadow_run(
        scenario_id="SC-s328-02", description="unreachable",
        target_area="area_14", predicted_outcome="uncertain",
        risk_level="LOW", confidence=0.5,
    )
    import urllib.error as _ue
    with patch("urllib.request.urlopen", side_effect=_ue.URLError("refused")):
        with pytest.raises(ShadowSimError):
            e.run_simulation_llm("SC-s328-02", session="S328")


# 15: run_simulation_llm no scenario
def test_15_run_simulation_llm_no_scenario(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError):
        e.run_simulation_llm("SC-does-not-exist", session="S328")


# 16: run_simulation_llm parse fallback
def test_16_run_simulation_llm_parse_fallback(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_shadow_run(
        scenario_id="SC-s328-03", description="fallback",
        target_area="area_14", predicted_outcome="failure",
        risk_level="HIGH", confidence=0.3,
    )
    resp_d = {"ok": True, "text": "no valid json here at all"}
    rbytes = _jmod.dumps(resp_d).encode("utf-8")
    mock_h = MagicMock()
    mock_h.read.return_value = rbytes
    with patch("urllib.request.urlopen") as mu:
        mu.return_value.__enter__ = MagicMock(return_value=mock_h)
        mu.return_value.__exit__ = MagicMock(return_value=False)
        result = e.run_simulation_llm("SC-s328-03", session="S328")
    assert result["source"] == "llm_simulation"
    assert result["predicted_outcome"] == "failure"
    assert result["risk_level"] == "HIGH"
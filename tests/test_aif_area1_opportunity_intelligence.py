#!/usr/bin/env python3
"""
test_aif_area1_opportunity_intelligence.py
AIF Area 1: Trust-Bound Opportunity Intelligence Engine test suite (12 tests)
EAG: EAG-S323-AIF-AREA1-001
"""
import hashlib
import json
import pytest
from datetime import datetime, timedelta, timezone

from tools.opportunity.area_1_opportunity_intelligence import (
    OpportunityError,
    OpportunityIntelligenceEngine,
    REVERSIBILITY_PENALTY,
    VERSION,
    EAG_ID,
)


# 01: Evidence basic storage
def test_01_record_evidence_basic(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    ev = engine.record_evidence(
        content="AI governance regulation is increasing",
        evidence_confidence=0.9,
        inference_confidence=0.8,
        source="regulatory_report",
    )
    assert ev["id"].startswith("E-")
    assert ev["schema"] == "evidence_v1"
    assert ev["version"] == VERSION
    assert ev["evidence_confidence"] == 0.9
    assert ev["inference_confidence"] == 0.8
    assert "expires_at" in ev
    assert "recorded_at" in ev
    assert ev["actor"] == "system"


# 02: Evidence SHA-256 hash binding
def test_02_record_evidence_source_hash(tmp_path):
    engine  = OpportunityIntelligenceEngine(log_dir=tmp_path)
    content = "Market size is 10B by 2030"
    ev      = engine.record_evidence(
        content=content,
        evidence_confidence=0.7,
        inference_confidence=0.6,
        source="analyst_report",
    )
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert ev["source_hash"] == expected


# 03: Evidence confidence upper bound
def test_03_record_evidence_invalid_confidence_high(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    with pytest.raises(OpportunityError, match="evidence_confidence"):
        engine.record_evidence(
            content="Test",
            evidence_confidence=1.5,
            inference_confidence=0.5,
            source="test",
        )


# 04: Evidence inference_confidence lower bound
def test_04_record_evidence_invalid_inference_confidence_negative(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    with pytest.raises(OpportunityError, match="inference_confidence"):
        engine.record_evidence(
            content="Test",
            evidence_confidence=0.5,
            inference_confidence=-0.1,
            source="test",
        )


# 05: Assumption basic storage
def test_05_record_assumption_basic(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    a = engine.record_assumption(
        content="Regulators will mandate AI audit trails by 2027",
        confidence=0.75,
    )
    assert a["id"].startswith("A-")
    assert a["schema"] == "assumption_v1"
    assert a["confidence"] == 0.75
    assert a["belief_revision_events"] == []
    assert a["depends_on"] == []
    assert a["vev_declared"] is False


# 06: Assumption TTL expires_at correctness
def test_06_record_assumption_ttl(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    before = datetime.now(timezone.utc)
    a      = engine.record_assumption(
        content="Test assumption", confidence=0.5, ttl_days=7
    )
    after = datetime.now(timezone.utc)
    exp   = datetime.fromisoformat(a["expires_at"])
    assert before + timedelta(days=7) <= exp <= after + timedelta(days=7)


# 07: Opportunity Score - HIGH reversibility (penalty=1.0)
def test_07_score_reversibility_high(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    score  = engine.calculate_opportunity_score(
        expected_value=2.0, evidence_ids=[], assumption_ids=[],
        strategic_alignment=1.0, wrong_cost_factor=1.0, reversibility="HIGH",
    )
    # No evidence: avg_ec=0.5, avg_ic=0.5, fresh=1.0
    # Score = (2.0*0.5*0.5*1.0*1.0*1.0*1.0)/(1.0*1.0*1.0) = 0.5
    assert score == pytest.approx(0.5, abs=1e-4)


# 08: Opportunity Score - MEDIUM reversibility (penalty=1.5)
def test_08_score_reversibility_medium(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    score  = engine.calculate_opportunity_score(
        expected_value=2.0, evidence_ids=[], assumption_ids=[],
        strategic_alignment=1.0, wrong_cost_factor=1.0, reversibility="MEDIUM",
    )
    # Score = 0.5 / 1.5
    assert score == pytest.approx(0.5 / 1.5, abs=1e-4)


# 09: Opportunity Score - LOW reversibility (penalty=2.0) + ordering
def test_09_score_reversibility_low_ordering(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    kwargs = dict(
        expected_value=2.0, evidence_ids=[], assumption_ids=[],
        strategic_alignment=1.0, wrong_cost_factor=1.0,
    )
    s_low  = engine.calculate_opportunity_score(reversibility="LOW",    **kwargs)
    s_med  = engine.calculate_opportunity_score(reversibility="MEDIUM", **kwargs)
    s_high = engine.calculate_opportunity_score(reversibility="HIGH",   **kwargs)
    assert s_low  == pytest.approx(0.25, abs=1e-4)
    assert s_low < s_med < s_high


# 10: Freshness factor decay via expired evidence
def test_10_freshness_factor_decay(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    ev = engine.record_evidence(
        content="Fresh signal data",
        evidence_confidence=0.9,
        inference_confidence=0.9,
        source="live_feed",
        ttl_days=30,
    )
    # Append synthetic expired entry with same confidences
    expired = engine._load_evidence()[0].copy()
    expired["id"]         = "E-expired-synthetic"
    expired["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).isoformat()
    with open(engine._evidence_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(expired, ensure_ascii=False) + "\n")

    score_fresh_only = engine.calculate_opportunity_score(
        expected_value=1.0, evidence_ids=[ev["id"]],
        assumption_ids=[], strategic_alignment=1.0,
        wrong_cost_factor=1.0, reversibility="HIGH",
    )
    score_with_expired = engine.calculate_opportunity_score(
        expected_value=1.0, evidence_ids=[ev["id"], "E-expired-synthetic"],
        assumption_ids=[], strategic_alignment=1.0,
        wrong_cost_factor=1.0, reversibility="HIGH",
    )
    # Expired evidence halves freshness_factor; score must decrease
    assert score_with_expired < score_fresh_only


# 11: Opportunity record + auto score
def test_11_record_opportunity_basic(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    ev = engine.record_evidence(
        content="Enterprise AI compliance market growing",
        evidence_confidence=0.85,
        inference_confidence=0.80,
        source="market_research",
    )
    op = engine.record_opportunity(
        title="AI Compliance SaaS MVP",
        evidence_ids=[ev["id"]],
        assumption_ids=[],
        strategic_alignment=0.9,
        wrong_cost_factor=1.5,
        reversibility="HIGH",
        expected_value=3.0,
        actor="caddy",
    )
    assert op["id"].startswith("OP-")
    assert op["schema"] == "opportunity_v1"
    assert op["status"] == "active"
    assert isinstance(op["score"], float) and op["score"] > 0.0
    assert op["signal_verification_gate"] is None
    assert op["differential_eag"] is None


# 12: get_active_opportunities min_score filter
def test_12_get_active_opportunities_filter(tmp_path):
    engine = OpportunityIntelligenceEngine(log_dir=tmp_path)
    engine.record_opportunity(
        title="High Score",
        evidence_ids=[], assumption_ids=[],
        strategic_alignment=1.0, wrong_cost_factor=1.0,
        reversibility="HIGH", expected_value=10.0,
    )
    engine.record_opportunity(
        title="Low Score",
        evidence_ids=[], assumption_ids=[],
        strategic_alignment=0.1, wrong_cost_factor=5.0,
        reversibility="LOW", expected_value=0.5,
    )
    all_active = engine.get_active_opportunities(min_score=0.0)
    high_only  = engine.get_active_opportunities(min_score=1.0)
    assert len(all_active) == 2
    assert len(high_only)  == 1
    assert high_only[0]["title"] == "High Score"

#!/usr/bin/env python3
"""
test_aif_area4_agent_debate.py
AIF Area 4: Agent Debate Protocol test suite (12 tests)
EAG: EAG-S324-AIF-AREA4-001
"""
import pytest

from tools.governance.area_4_agent_debate import (
    DebateError,
    AgentDebateEngine,
    VERSION,
    EAG_ID,
    EAG_ID_P2,
)


# 01: open_debate basic
def test_01_open_debate_basic(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate(
        topic_id="AREA-6-DESIGN",
        topic_title="Area 6 design review",
        initiator="caddy",
    )
    assert debate["id"].startswith("DEB-")
    assert debate["schema"] == "debate_log_v1"
    assert debate["version"] == VERSION
    assert debate["type"] == "open"
    assert debate["status"] == "open"
    assert debate["initiator"] == "caddy"
    assert debate["eag"] == EAG_ID


# 02: open_debate invalid initiator
def test_02_open_debate_invalid_initiator(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    with pytest.raises(DebateError, match="initiator"):
        engine.open_debate(
            topic_id="T-001",
            topic_title="test",
            initiator="INVALID_AGENT",
        )


# 03: open_debate empty topic_id
def test_03_open_debate_empty_topic_id(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    with pytest.raises(DebateError, match="topic_id"):
        engine.open_debate(
            topic_id="",
            topic_title="test",
            initiator="caddy",
        )


# 04: record_position basic
def test_04_record_position_basic(tmp_path):
    engine  = AgentDebateEngine(log_dir=tmp_path)
    debate  = engine.open_debate("T-001", "Area 7 learning review", "caddy")
    pos     = engine.record_position(
        debate_id     = debate["id"],
        agent         = "domi",
        position_type = "support",
        content       = "Design aligns with Decision OS Section 15",
        confidence    = 0.9,
    )
    assert pos["id"].startswith("POS-")
    assert pos["schema"] == "position_log_v1"
    assert pos["debate_id"] == debate["id"]
    assert pos["agent"] == "domi"
    assert pos["position_type"] == "support"
    assert pos["confidence"] == 0.9


# 05: record_position invalid agent
def test_05_record_position_invalid_agent(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "test", "caddy")
    with pytest.raises(DebateError, match="agent"):
        engine.record_position(
            debate_id="T-001", agent="UNKNOWN",
            position_type="support", content="test", confidence=0.5,
        )


# 06: record_position confidence out of range
def test_06_record_position_confidence_out_of_range(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "test", "jeni")
    with pytest.raises(DebateError, match="confidence"):
        engine.record_position(
            debate_id=debate["id"], agent="jeni",
            position_type="neutral", content="test", confidence=1.5,
        )


# 07: record_round_result basic
def test_07_record_round_result_basic(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "Round test", "caddy")
    result = engine.record_round_result(
        debate_id=debate["id"],
        round_number=1,
        summary="Domi supports, Jeni conditionally supports",
    )
    assert result["type"] == "round_result"
    assert result["id"] == debate["id"]
    assert result["round_number"] == 1


# 08: close_debate basic
def test_08_close_debate_basic(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "Close test", "caddy")
    close  = engine.close_debate(
        debate_id       = debate["id"],
        outcome         = "consensus",
        consensus_level = 0.9,
        decision_ref    = "D-042",
    )
    assert close["type"] == "close"
    assert close["status"] == "closed"
    assert close["outcome"] == "consensus"
    assert close["consensus_level"] == 0.9
    assert close["decision_ref"] == "D-042"
    assert close["wf05_workitem"] is None


# 09: close_debate invalid outcome
def test_09_close_debate_invalid_outcome(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "test", "caddy")
    with pytest.raises(DebateError, match="outcome"):
        engine.close_debate(
            debate_id=debate["id"], outcome="INVALID", consensus_level=0.5
        )


# 10: get_open_debates
def test_10_get_open_debates(tmp_path):
    engine  = AgentDebateEngine(log_dir=tmp_path)
    debate1 = engine.open_debate("T-001", "Debate One", "caddy")
    debate2 = engine.open_debate("T-002", "Debate Two", "domi")
    engine.close_debate(debate1["id"], "consensus", 1.0)
    open_debates = engine.get_open_debates()
    assert len(open_debates) == 1
    assert open_debates[0]["id"] == debate2["id"]


# 11: get_debate_summary full flow
def test_11_get_debate_summary(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "Summary test", "caddy")
    engine.record_position(debate["id"], "domi", "support", "Design is solid", 0.95)
    engine.record_position(debate["id"], "jeni", "conditional", "Needs area_ref check", 0.75)
    engine.record_round_result(debate["id"], 1, "Round 1: mostly aligned")
    engine.close_debate(debate["id"], "consensus", 0.85)
    summary = engine.get_debate_summary(debate["id"])
    assert summary["schema"] == "debate_summary_v1"
    assert summary["status"] == "closed"
    assert summary["position_count"] == 2
    assert summary["round_count"] == 1
    assert summary["outcome"] == "consensus"
    assert summary["consensus_level"] == 0.85
    assert summary["position_summary"]["support"] == 1
    assert summary["position_summary"]["conditional"] == 1


# 12: record_position on closed debate raises
def test_12_record_position_closed_debate_raises(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    debate = engine.open_debate("T-001", "Close test", "caddy")
    engine.close_debate(debate["id"], "no_consensus", 0.3)
    with pytest.raises(DebateError, match="already closed"):
        engine.record_position(
            debate_id=debate["id"], agent="beo",
            position_type="oppose", content="Too late", confidence=0.5,
        )

# ===== Phase 2 Tests (EAG-S327-AIF-AREA4-P2-001) =====

# 13: link_wf05_workitem basic
def test_13_link_wf05_workitem_basic(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    deb = engine.open_debate(topic_id="T1", topic_title="Test topic", initiator="caddy")
    did = deb["id"]
    engine.close_debate(debate_id=did, outcome="consensus", consensus_level=0.9)
    result = engine.link_wf05_workitem(debate_id=did, workitem_id="WI-test-001")
    assert result["wf05_workitem"] == "WI-test-001"
    assert result["type"] == "close"
    assert result["eag"] == EAG_ID_P2
    assert "linked_at" in result
    import json
    lines = [l for l in (tmp_path / "debate_log.jsonl").read_text().splitlines() if l.strip()]
    entries = [json.loads(l) for l in lines]
    last = entries[-1]
    assert last["wf05_workitem"] == "WI-test-001"

# 14: link_wf05_workitem no close entry
def test_14_link_wf05_workitem_no_close(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    deb = engine.open_debate(topic_id="T2", topic_title="Open topic", initiator="domi")
    with pytest.raises(DebateError, match="no close entry"):
        engine.link_wf05_workitem(debate_id=deb["id"], workitem_id="WI-test-002")

# 15: link_wf05_workitem empty debate_id
def test_15_link_wf05_workitem_empty_debate_id(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    with pytest.raises(DebateError, match="debate_id"):
        engine.link_wf05_workitem(debate_id="", workitem_id="WI-003")

# 16: link_wf05_workitem empty workitem_id
def test_16_link_wf05_workitem_empty_workitem_id(tmp_path):
    engine = AgentDebateEngine(log_dir=tmp_path)
    with pytest.raises(DebateError, match="workitem_id"):
        engine.link_wf05_workitem(debate_id="DEB-test", workitem_id="   ")

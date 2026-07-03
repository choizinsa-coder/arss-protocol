#!/usr/bin/env python3
"""
test_aif_area6_decl_to_op.py
AIF Area 6: Declaration-to-Operation Engine test suite (12 tests)
EAG: EAG-S324-AIF-AREA6-001
"""
import pytest

from tools.governance.area_6_decl_to_op import (
    DeclToOpError,
    DeclToOpEngine,
    VERSION,
    EAG_ID,
)


# 01: create_workitem basic
def test_01_create_workitem_basic(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    wi = engine.create_workitem(
        parent_decision="D-001",
        actor="caddy",
        work_type="IMPLEMENT",
        title="Implement Area 6",
    )
    assert wi["id"].startswith("WI-")
    assert wi["schema"] == "workitem_v1"
    assert wi["version"] == VERSION
    assert wi["actor"] == "caddy"
    assert wi["work_type"] == "IMPLEMENT"
    assert wi["status"] == "waiting"
    assert wi["eag"] == EAG_ID
    assert wi["sla_deadline"] is None
    assert wi["wf05_task_id"] is None
    assert wi["depends_on"] == []


# 02: create_workitem invalid actor
def test_02_create_workitem_invalid_actor(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    with pytest.raises(DeclToOpError, match="actor"):
        engine.create_workitem(
            parent_decision="D-001",
            actor="INVALID_AGENT",
            work_type="DESIGN",
            title="test",
        )


# 03: create_workitem invalid work_type
def test_03_create_workitem_invalid_work_type(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    with pytest.raises(DeclToOpError, match="work_type"):
        engine.create_workitem(
            parent_decision="D-001",
            actor="caddy",
            work_type="INVALID_TYPE",
            title="test",
        )


# 04: create_workitem empty parent_decision
def test_04_create_workitem_empty_decision(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    with pytest.raises(DeclToOpError, match="parent_decision"):
        engine.create_workitem(
            parent_decision="",
            actor="domi",
            work_type="DESIGN",
            title="test",
        )


# 05: update_workitem_status basic
def test_05_update_workitem_status_basic(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    wi = engine.create_workitem(
        parent_decision="D-001", actor="domi", work_type="DESIGN", title="Test"
    )
    updated = engine.update_workitem_status(wi["id"], "in_progress", actor="domi")
    assert updated["status"] == "in_progress"
    assert updated["id"] == wi["id"]


# 06: update_status is append-only (get_workitem_by_id returns latest)
def test_06_update_status_append_only(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    wi = engine.create_workitem(
        parent_decision="D-001", actor="caddy", work_type="IMPLEMENT",
        title="Test", status="ready",
    )
    engine.update_workitem_status(wi["id"], "in_progress", actor="caddy")
    engine.update_workitem_status(wi["id"], "done", actor="caddy")
    latest = engine.get_workitem_by_id(wi["id"])
    assert latest["status"] == "done"
    # Raw entries = 3 (1 create + 2 updates)
    all_raw = engine._load_all_workitems()
    assert len(all_raw) == 3


# 07: generate_dep_chain structure
def test_07_generate_dep_chain_structure(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    chain = engine.generate_dep_chain("D-100", "Build Feature X")
    assert len(chain) == 4
    assert chain[0]["work_type"] == "DESIGN"    and chain[0]["actor"] == "domi"
    assert chain[1]["work_type"] == "VERIFY"    and chain[1]["actor"] == "jeni"
    assert chain[2]["work_type"] == "IMPLEMENT" and chain[2]["actor"] == "caddy"
    assert chain[3]["work_type"] == "EAG"       and chain[3]["actor"] == "beo"
    assert chain[0]["status"] == "ready"
    assert all(wi["status"] == "waiting" for wi in chain[1:])


# 08: generate_dep_chain depends_on uses actual UUIDs
def test_08_dep_chain_depends_on_uuid(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    chain = engine.generate_dep_chain("D-100", "Test Chain")
    assert chain[0]["depends_on"] == []
    assert chain[1]["depends_on"] == [chain[0]["id"]]
    assert chain[2]["depends_on"] == [chain[1]["id"]]
    assert chain[3]["depends_on"] == [chain[2]["id"]]
    for wi in chain:
        assert wi["id"].startswith("WI-")


# 09: get_workitems_for_decision
def test_09_get_workitems_for_decision(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    engine.generate_dep_chain("D-001", "Decision One")
    engine.generate_dep_chain("D-002", "Decision Two")
    d1_items = engine.get_workitems_for_decision("D-001")
    d2_items = engine.get_workitems_for_decision("D-002")
    assert len(d1_items) == 4
    assert len(d2_items) == 4
    assert all(wi["parent_decision"] == "D-001" for wi in d1_items)


# 10: get_ready_queue basic
def test_10_get_ready_queue_basic(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    engine.generate_dep_chain("D-001", "Decision One")
    engine.generate_dep_chain("D-002", "Decision Two")
    ready = engine.get_ready_queue()
    assert len(ready) == 2
    assert all(wi["status"] == "ready" for wi in ready)


# 11: get_ready_queue actor_filter
def test_11_get_ready_queue_actor_filter(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    engine.generate_dep_chain("D-001", "Decision One")
    engine.generate_dep_chain("D-002", "Decision Two")
    domi_ready = engine.get_ready_queue(actor_filter="domi")
    jeni_ready = engine.get_ready_queue(actor_filter="jeni")
    assert len(domi_ready) == 2
    assert len(jeni_ready) == 0


# 12: get_workitem_summary
def test_12_get_workitem_summary(tmp_path):
    engine = DeclToOpEngine(log_dir=tmp_path)
    engine.generate_dep_chain("D-001", "Decision One")
    summary = engine.get_workitem_summary()
    assert summary["schema"] == "workitem_summary_v1"
    assert summary["total_count"] == 4
    assert summary["by_status"]["ready"] == 1
    assert summary["by_status"]["waiting"] == 3
    assert summary["by_actor"]["domi"] == 1
    assert summary["by_actor"]["jeni"] == 1
    assert summary["by_actor"]["caddy"] == 1
    assert summary["by_actor"]["beo"] == 1
    assert len(summary["recent_5"]) == 4

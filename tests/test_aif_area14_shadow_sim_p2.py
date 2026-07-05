import json
from pathlib import Path
import pytest
from tools.governance.area_14_shadow_sim import ShadowSimError, ShadowSimEngine, VERSION, EAG_ID


def _write_events(log_dir, events):
    p = Path(log_dir) / "interlock_log.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + chr(10))


def test_p2_01_auto_engage_block(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    bid = e._auto_engage_interlock("area_7")
    assert bid and bid.startswith("BLK-")
    assert "area_7" in e.get_blocked_areas()


def test_p2_02_auto_engage_idempotent(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e._auto_engage_interlock("area_7")
    assert e._auto_engage_interlock("area_7") is None
    assert e.get_blocked_areas() == ["area_7"]


def test_p2_03_auto_engage_empty_area(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    with pytest.raises(ShadowSimError):
        e._auto_engage_interlock("")


def test_p2_04_unblock(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e._auto_engage_interlock("area_7")
    uid = e.unblock_area("area_7", actor="beo", eag_id="EAG-S338-TEST")
    assert uid and uid.startswith("UNB-")
    assert "area_7" not in e.get_blocked_areas()


def test_p2_05_unblock_not_blocked_noop(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.unblock_area("area_7") is None


def test_p2_06_get_blocked_empty(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.get_blocked_areas() == []


def test_p2_07_same_ts_block_then_unblock(tmp_path):
    ts = "2026-07-05T00:00:00+00:00"
    _write_events(tmp_path, [
        {"event_type": "block", "area_name": "A", "recorded_at": ts},
        {"event_type": "unblock", "area_name": "A", "recorded_at": ts},
    ])
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.get_blocked_areas() == []


def test_p2_08_same_ts_unblock_then_block(tmp_path):
    ts = "2026-07-05T00:00:00+00:00"
    _write_events(tmp_path, [
        {"event_type": "unblock", "area_name": "A", "recorded_at": ts},
        {"event_type": "block", "area_name": "A", "recorded_at": ts},
    ])
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.get_blocked_areas() == ["A"]


def test_p2_09_missing_fields_skipped(tmp_path):
    _write_events(tmp_path, [
        {"event_type": "block", "area_name": "X", "recorded_at": "2026-07-05T00:00:00+00:00"},
        {"event_type": "block", "recorded_at": "2026-07-05T00:00:01+00:00"},
        {"event_type": "block", "area_name": "Y"},
    ])
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.get_blocked_areas() == ["X"]


def test_p2_10_corrupt_line_skipped(tmp_path):
    p = Path(tmp_path) / "interlock_log.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps({"event_type": "block", "area_name": "A", "recorded_at": "2026-07-05T00:00:00+00:00"}) + chr(10))
        f.write("{invalid json" + chr(10))
        f.write(json.dumps({"event_type": "unblock", "area_name": "A", "recorded_at": "2026-07-05T00:00:02+00:00"}) + chr(10))
    e = ShadowSimEngine(log_dir=tmp_path)
    assert e.get_blocked_areas() == []


def test_p2_11_phase1_rule_backward_compat(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule(rule_id="R1", trigger_area="area_3", trigger_condition="rc3_repeat", blocked_area="area_9", reason="test")
    assert e.get_blocked_areas() == []
    assert len(e.check_interlock("area_9")) == 1


def test_p2_12_dependency_map_empty(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    dm = e.build_dependency_map()
    assert dm["schema"] == "dependency_map_v1"
    assert dm["nodes"] == []
    assert dm["edges"] == []
    assert dm["cycles"] == []
    assert dm["stats"]["total_nodes"] == 0


def test_p2_13_dependency_map_edges(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule(rule_id="R1", trigger_area="area_3", trigger_condition="rc3_repeat", blocked_area="area_9", reason="t")
    dm = e.build_dependency_map()
    assert dm["stats"]["total_edges"] == 1
    assert set(n["area_name"] for n in dm["nodes"]) == {"area_3", "area_9"}
    assert dm["edges"][0]["source"] == "area_3"
    assert dm["edges"][0]["target"] == "area_9"


def test_p2_14_dependency_map_cycle(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule(rule_id="R1", trigger_area="A", trigger_condition="custom", blocked_area="B", reason="t")
    e.record_interlock_rule(rule_id="R2", trigger_area="B", trigger_condition="custom", blocked_area="A", reason="t")
    dm = e.build_dependency_map()
    assert dm["stats"]["cycle_count"] >= 1


def test_p2_15_dependency_map_blocked_flag(tmp_path):
    e = ShadowSimEngine(log_dir=tmp_path)
    e.record_interlock_rule(rule_id="R1", trigger_area="area_3", trigger_condition="rc3_repeat", blocked_area="area_9", reason="t")
    e._auto_engage_interlock("area_9")
    dm = e.build_dependency_map()
    node9 = [n for n in dm["nodes"] if n["area_name"] == "area_9"][0]
    assert node9["blocked"] is True

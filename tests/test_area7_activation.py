#!/usr/bin/env python3
"""
test_area7_activation.py
WP-2 area_7 activation unit tests (EAG-S374-LEARNING-LOOP-B-ACTIVATE-IMPL-001).
Fully isolated: stub engine injected -> NO production area_7/area_15 access.
"""
import json
import uuid
from datetime import datetime, timezone

from tools.monitor.area7_activation import run_area7_activation, _stable_hash


class StubEngine:
    """Isolated stand-in for OrgLearningEngine (no filesystem, no imports)."""
    def __init__(self, opportunities, raise_on=None):
        self._opps    = opportunities
        self.raise_on = raise_on   # description value that triggers a raise
        self.generated = []

    def detect_improvement_opportunities(self, window_days=30):
        return [dict(o) for o in self._opps]

    def generate_improvement_proposal(self, trigger, description, priority, actor="system"):
        if self.raise_on is not None and description == self.raise_on:
            raise ValueError("stub invalid opp")
        self.generated.append({
            "trigger": trigger, "description": description,
            "priority": priority, "actor": actor,
        })
        return {"id": "IP-stub", "status": "pending_eag"}


def _opp(trigger="failure_repeat", desc="5x: caddy/RC-2", prio="HIGH", oid=None, ts=None):
    return {
        "id":          oid or f"IO-{uuid.uuid4()}",
        "trigger":     trigger,
        "description": desc,
        "priority":    prio,
        "source_ref":  {"area": "area_15"},
        "detected_at": ts or datetime.now(timezone.utc).isoformat(),
    }


def test_cooldown_throttles(tmp_path):
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps({"last_run_ts": 1000.0, "proposal_hashes": []}))
    eng = StubEngine([_opp()])
    r = run_area7_activation(engine=eng, throttle_path=tp, now_ts=1000.0 + 60)  # 60s < 1800
    assert r["throttled"] is True
    assert r["ran"] is False
    assert eng.generated == []


def test_detects_and_generates(tmp_path):
    tp = tmp_path / "t.json"
    eng = StubEngine([_opp(desc="A"), _opp(desc="B")])
    r = run_area7_activation(engine=eng, throttle_path=tp, now_ts=10000.0)
    assert r["ran"] is True
    assert r["new_proposals"] == 2
    assert len(eng.generated) == 2
    state = json.loads(tp.read_text())
    assert len(state["proposal_hashes"]) == 2
    assert state["last_run_ts"] == 10000.0


def test_stable_field_dedup(tmp_path):
    """C1 fix: same stable fields, different volatile id/detected_at -> dedup."""
    tp = tmp_path / "t.json"
    eng1 = StubEngine([_opp(desc="dup", oid="IO-1", ts="2026-01-01T00:00:00+00:00")])
    r1 = run_area7_activation(engine=eng1, throttle_path=tp, now_ts=10000.0)
    assert r1["new_proposals"] == 1
    eng2 = StubEngine([_opp(desc="dup", oid="IO-2", ts="2026-02-02T00:00:00+00:00")])
    r2 = run_area7_activation(engine=eng2, throttle_path=tp, now_ts=10000.0 + 2000)
    assert r2["dedup_skipped"] == 1
    assert r2["new_proposals"] == 0
    assert eng2.generated == []


def test_empty_opportunities(tmp_path):
    tp = tmp_path / "t.json"
    eng = StubEngine([])
    r = run_area7_activation(engine=eng, throttle_path=tp, now_ts=5000.0)
    assert r["ran"] is True
    assert r["new_proposals"] == 0
    state = json.loads(tp.read_text())
    assert state["last_run_ts"] == 5000.0


def test_invalid_opp_skipped(tmp_path):
    tp = tmp_path / "t.json"
    eng = StubEngine([_opp(desc="good"), _opp(desc="bad")], raise_on="bad")
    r = run_area7_activation(engine=eng, throttle_path=tp, now_ts=7000.0)
    assert r["new_proposals"] == 1
    state = json.loads(tp.read_text())
    assert len(state["proposal_hashes"]) == 1  # bad hash NOT recorded


def test_stable_hash_ignores_volatile():
    a = _opp(desc="x", oid="IO-a", ts="2026-01-01T00:00:00+00:00")
    b = _opp(desc="x", oid="IO-b", ts="2026-09-09T00:00:00+00:00")
    assert _stable_hash(a) == _stable_hash(b)
    c = _opp(desc="y", oid="IO-a", ts="2026-01-01T00:00:00+00:00")
    assert _stable_hash(a) != _stable_hash(c)


def test_timestamp_persisted_before_generate(tmp_path):
    """Retry-storm guard: timestamp saved even if all generates fail."""
    tp = tmp_path / "t.json"
    eng = StubEngine([_opp(desc="bad")], raise_on="bad")
    r = run_area7_activation(engine=eng, throttle_path=tp, now_ts=8000.0)
    state = json.loads(tp.read_text())
    assert state["last_run_ts"] == 8000.0
    assert r["new_proposals"] == 0


# --- S431 v3 stable-hash normalisation (EAG-S431-AREA7-STABLE-HASH-V3-001) ---
from tools.monitor.area7_activation import _description_pattern


def test_v3_t1_identifier_discrimination():
    """PC-1 and PC-3 must remain distinct signals."""
    assert _stable_hash(_opp(desc="5x: caddy/PC-1")) != _stable_hash(_opp(desc="5x: caddy/PC-3"))


def test_v3_t2_count_increment_ignored():
    """D4 regression guard: the '{count}x:' prefix must be masked."""
    assert _stable_hash(_opp(desc="3x: caddy/RC-2")) == _stable_hash(_opp(desc="5x: caddy/RC-2"))


def test_v3_t3_hex_masked():
    assert _description_pattern("context_hash changed: deadbeef -> cafebabe") == "context_hash changed: {H} -> {H}"


def test_v3_t4_component_discrimination():
    assert _stable_hash(_opp(desc="3x: caddy/RC-2")) != _stable_hash(_opp(desc="3x: domi/RC-2"))


def test_v3_t5_channel2_pattern_and_dedup():
    assert _description_pattern("Area 13: total_failed=1") == "Area {N}: total_failed={N}"
    assert _stable_hash(_opp(desc="Area 13: total_failed=1")) == _stable_hash(_opp(desc="Area 13: total_failed=9"))


def test_v3_t6_non_string_safe():
    assert _description_pattern(None) == ""


def test_v3_burst_count_ignored():
    a = "3x: caddy/RC-2; burst 4x: domi/RC-1"
    b = "3x: caddy/RC-2; burst 9x: domi/RC-1"
    assert _stable_hash(_opp(desc=a)) == _stable_hash(_opp(desc=b))

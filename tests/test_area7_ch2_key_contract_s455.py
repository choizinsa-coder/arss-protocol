#!/usr/bin/env python3
"""
test_area7_ch2_key_contract_s455.py
S455: area_7 Channel 2 key contract vs area_13 real snapshot (EAG-S455-CH2-FIX-001).

Why this file exists:
  Channel 2 read snapshot.get("total_failed") while the real snapshot exposes M02.
  No exception was raised -- the channel evaluated to 0 forever and never fired.
  These contracts call the REAL producer (no mock fixture) so that a future key
  drift fails loudly instead of dying silently.
"""
import inspect
import re
from unittest.mock import patch

import tools.governance.area_7_org_learning as m7
from tools.governance.area_7_org_learning import OrgLearningEngine
from tools.governance.area_13_evaluation import get_current_snapshot
from tools.monitor.area7_activation import _description_pattern

_NO_ALERT = {
    "has_alert": False,
    "consecutive_repeat": [],
    "frequency_burst": [],
    "cross_component": [],
    "window_minutes": 43200,
    "threshold": 3,
}


def _real_snapshot_shape(m02=0, m01=1869):
    """Snapshot dict mirroring the REAL get_current_snapshot() key set."""
    keys = set(get_current_snapshot().keys())
    snap = {k: None for k in keys}
    snap["M01"] = m01
    snap["M02"] = m02
    snap["pytest_skipped"] = 95
    snap["snapshot_at"] = "2026-07-27T00:00:00+00:00"
    return snap


# C1: real snapshot exposes M02 and does NOT expose total_failed
def test_c1_real_snapshot_key_set():
    keys = set(get_current_snapshot().keys())
    assert "M02" in keys
    assert "total_failed" not in keys


# C2: every key Channel 2 reads from the snapshot must exist in the real key set
def test_c2_channel2_reads_only_existing_keys():
    src = inspect.getsource(OrgLearningEngine.detect_improvement_opportunities)
    read_keys = set(re.findall(r'snapshot\.get\(\s*"([^"]+)"', src))
    assert read_keys, "Channel 2 snapshot read not found -- contract anchor moved"
    real_keys = set(get_current_snapshot().keys())
    missing = read_keys - real_keys
    assert not missing, f"Channel 2 reads non-existent snapshot keys: {sorted(missing)}"


# C3: with a realistic snapshot and M02 == 0, ghs_decline must NOT fire
def test_c3_no_fire_when_m02_zero(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=_real_snapshot_shape(m02=0)):
            result = engine.detect_improvement_opportunities()
    assert not any(r["trigger"] == "ghs_decline" for r in result)


# C4: with a realistic snapshot and M02 > 0, ghs_decline MUST fire
def test_c4_fires_when_m02_positive(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=_real_snapshot_shape(m02=3)):
            result = engine.detect_improvement_opportunities()
    hits = [r for r in result if r["trigger"] == "ghs_decline"]
    assert len(hits) == 1
    assert hits[0]["priority"] == "HIGH"
    assert hits[0]["source_ref"]["area"] == "area_13"


# C5: description wording stays compatible with the S431 dedup pattern
def test_c5_description_pattern_compatible(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=_real_snapshot_shape(m02=7)):
            result = engine.detect_improvement_opportunities()
    desc = [r for r in result if r["trigger"] == "ghs_decline"][0]["description"]
    assert desc == "Area 13: total_failed=7"
    assert _description_pattern(desc) == "Area {N}: total_failed={N}"


# C6: a snapshot missing M02 entirely must not raise and must not fire
def test_c6_missing_m02_is_silent_but_safe(tmp_path):
    engine = OrgLearningEngine(log_dir=tmp_path)
    broken = _real_snapshot_shape(m02=0)
    broken.pop("M02")
    with patch.object(m7, "_get_failure_patterns", return_value=_NO_ALERT):
        with patch.object(m7, "_get_current_snapshot", return_value=broken):
            result = engine.detect_improvement_opportunities()
    assert not any(r["trigger"] == "ghs_decline" for r in result)

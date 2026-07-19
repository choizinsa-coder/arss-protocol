#!/usr/bin/env python3
"""S432 channel5: cross_session_repeat + dual-key + M05 guard.
EAG-S432-CH5-DETECTOR-IMPL-001
"""
from unittest.mock import patch

import tools.governance.area_15_failure_memory as m15

MOD = "tools.governance.area_15_failure_memory._load_all_entries"


def _e(comp, ec, sess=None, sess_ref=None, rc="RC-2", source=None):
    ctx = {}
    if sess is not None:
        ctx["session"] = sess
    if sess_ref is not None:
        ctx["session_ref"] = sess_ref
    if source is not None:
        ctx["source"] = source
    return {"component": comp, "error_code": ec, "rc": rc, "context": ctx}


def test_cross_session_repeat_fires_on_three_distinct_sessions():
    rows = [_e("caddy", "SELF-NEG-ORDER", sess="S430"),
            _e("caddy", "SELF-NEG-ORDER", sess="S431"),
            _e("caddy", "SELF-NEG-ORDER", sess="S432")]
    with patch(MOD, return_value=rows):
        r = m15.get_failure_patterns()
    assert len(r["cross_session_repeat"]) == 1
    assert r["cross_session_repeat"][0]["distinct_sessions"] == 3
    assert r["has_alert"] is True


def test_same_session_duplicates_do_not_fire():
    rows = [_e("caddy", "SELF-NEG-ORDER", sess="S432") for _ in range(6)]
    with patch(MOD, return_value=rows):
        r = m15.get_failure_patterns()
    assert r["cross_session_repeat"] == []


def test_dual_key_session_ref_is_recognized():
    rows = [_e("caddy", "EXEC:FAIL:run_script", sess_ref=379),
            _e("caddy", "EXEC:FAIL:run_script", sess_ref=380),
            _e("caddy", "EXEC:FAIL:run_script", sess_ref=384)]
    with patch(MOD, return_value=rows):
        r = m15.get_failure_patterns()
    assert r["cross_session_repeat"][0]["sessions"] == ["379", "380", "384"]


def test_session_value_normalization_collapses_forms():
    rows = [_e("caddy", "X-1", sess="S431"),
            _e("caddy", "X-1", sess="431"),
            _e("caddy", "X-1", sess_ref=431)]
    with patch(MOD, return_value=rows):
        r = m15.get_failure_patterns()
    assert r["cross_session_repeat"] == []


def test_session_key_wins_over_session_ref():
    assert m15._entry_session({"context": {"session": "S432", "session_ref": 111}}) == "432"
    assert m15._entry_session({"context": {"session_ref": 111}}) == "111"
    assert m15._entry_session({"context": {}}) is None


def test_threshold_is_configurable():
    rows = [_e("caddy", "Y-1", sess="S1"), _e("caddy", "Y-1", sess="S2")]
    with patch(MOD, return_value=rows):
        assert m15.get_failure_patterns()["cross_session_repeat"] == []
        assert m15.get_failure_patterns(cross_session_threshold=2)["cross_session_repeat"]


def test_m05_excludes_bridge_source_by_default():
    rows = [_e("caddy", "PC-3", sess_ref=432, source="promise_failure_bridge"),
            _e("caddy", "SELF-DESIGN-D1", sess="S432")]
    with patch(MOD, return_value=rows):
        assert m15.get_m05_contribution("S432")["count"] == 1
        assert m15.get_m05_contribution("S432", exclude_sources=frozenset())["count"] == 2


def test_m05_dual_key_and_rc1_excluded():
    rows = [_e("caddy", "A", sess_ref=432),
            _e("caddy", "B", sess="432", rc="RC-1")]
    with patch(MOD, return_value=rows):
        r = m15.get_m05_contribution("S432")
    assert r["count"] == 1
    assert r["session"] == "S432"

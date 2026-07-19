#!/usr/bin/env python3
"""S432 channel5 stage2: session self-report -> failure_memory ingest.
EAG-S432-CH5-INGEST-IMPL-001
"""
from unittest.mock import patch

import tools.close.session_close_generator as scg
import tools.governance.area_15_failure_memory as m15


def _sc(n, incidents=None, self_report=None):
    return {"caddy_governance_record_s%d" % n: {
        "incidents": incidents or [],
        "caddy_self_report": self_report or [],
    }}


def test_code_mapping_design_prefix():
    assert scg._self_failure_code("D1: 도미 초안 결함", "incidents") == "SELF-DESIGN-D1"
    assert scg._self_failure_code("D4: 정규식 미심", "incidents") == "SELF-DESIGN-D4"


def test_code_mapping_keyword_and_unknown():
    assert scg._self_failure_code("제니 호출 1회 타임아웃", "incidents") == "SELF-TIMEOUT"
    a = scg._self_failure_code("전혀 새로운 서술", "incidents")
    b = scg._self_failure_code("전혀 새로운 서술", "incidents")
    assert a == b and a.startswith("SELF-UNKNOWN-")


def test_neg_prefix_stripped_and_mapped():
    assert scg._self_failure_code("NEG: 실행 순서를 틀렸다", "neg") == "SELF-NEG-ORDER"
    assert scg._self_failure_code("NEG: 건수를 오산했다", "neg") == "SELF-NEG-COUNT"


def test_pos_items_are_not_ingested():
    sc = _sc(432, self_report=["POS: 잘했다", "NEG: 정보 미제공"])
    with patch.object(m15, "_load_all_entries", return_value=[]), \
         patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures(sc, 432)
    assert rf.call_count == 1
    assert rf.call_args.kwargs["error_code"] == "SELF-NEG-INFO"


def test_same_code_collapsed_with_occurrences_preserved():
    sc = _sc(432, incidents=["D1: 첫번째", "D1: 두번째", "D1: 세번째"])
    with patch.object(m15, "_load_all_entries", return_value=[]), \
         patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures(sc, 432)
    assert rf.call_count == 1
    assert rf.call_args.kwargs["context"]["occurrences"] == 3


def test_rc_assignment_incidents_rc2_neg_rc1():
    sc = _sc(432, incidents=["D1: x"], self_report=["NEG: 순서"])
    with patch.object(m15, "_load_all_entries", return_value=[]), \
         patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures(sc, 432)
    rcs = {c.kwargs["error_code"]: c.kwargs["category"] for c in rf.call_args_list}
    assert rcs["SELF-DESIGN-D1"] is m15.FailureCategory.RC2
    assert rcs["SELF-NEG-ORDER"] is m15.FailureCategory.RC1


def test_rerun_skips_already_ingested():
    prior = [{"component": "caddy", "error_code": "SELF-DESIGN-D1", "rc": "RC-2",
              "context": {"session": "432", "session_report": True}}]
    sc = _sc(432, incidents=["D1: x"])
    with patch.object(m15, "_load_all_entries", return_value=prior), \
         patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures(sc, 432)
    assert rf.call_count == 0


def test_context_has_session_and_flag():
    sc = _sc(432, incidents=["D1: x"])
    with patch.object(m15, "_load_all_entries", return_value=[]), \
         patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures(sc, 432)
    ctx = rf.call_args.kwargs["context"]
    assert ctx["session"] == "432"
    assert ctx["session_report"] is True
    assert ctx["source"] == "session_close"


def test_never_raises_on_record_failure_error():
    sc = _sc(432, incidents=["D1: x"])
    with patch.object(m15, "_load_all_entries", return_value=[]), \
         patch.object(m15, "record_failure", side_effect=RuntimeError("boom")):
        scg.ingest_self_failures(sc, 432)  # must not raise


def test_empty_record_is_noop():
    with patch.object(m15, "record_failure") as rf:
        scg.ingest_self_failures({}, 432)
    assert rf.call_count == 0

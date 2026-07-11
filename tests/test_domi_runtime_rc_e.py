# EAG-S378-RC-E-TC-ADD-001
# RC-E truncation-continuation regression lock:
#   Domi runtime finish_reason=="length" detection + _run_design_loop continuation + cap (MAX_TRUNCATION_CONTINUE)
import pytest
import tools.domi_runtime.aiba_domi_runtime as dr


def _mk(text, truncated=False):
    r = {"ok": True, "text": text, "tool_calls": [],
         "message": {"role": "assistant", "content": text},
         "usage": {}, "error": None}
    if truncated:
        r["truncated"] = True
    return r


@pytest.fixture
def _stub(monkeypatch):
    events = []
    monkeypatch.setattr(dr, "_gcb_check", lambda: False)
    monkeypatch.setattr(dr, "_daily_budget_exceeded", lambda: False)
    monkeypatch.setattr(dr, "_load_session_context", lambda: "ctx")
    monkeypatch.setattr(dr, "_begin_observation", lambda s: "obs")
    monkeypatch.setattr(dr, "_reset_loop_state", lambda: None)
    monkeypatch.setattr(dr, "_load_memory_context", lambda: {})
    monkeypatch.setattr(dr, "_build_memory_preamble", lambda m: "")
    monkeypatch.setattr(dr, "_build_initial_messages",
                        lambda p, c, mp, sc="": [{"role": "system", "content": "x"}])
    monkeypatch.setattr(dr, "_log_call_cost", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_persist_results", lambda *a, **k: None)
    monkeypatch.setattr(dr, "_make_audit_bundle", lambda *a, **k: {})
    monkeypatch.setattr(dr, "_gcb_report_progress", lambda c: None)
    monkeypatch.setattr(dr, "_gcb_report_no_progress", lambda c: None)
    monkeypatch.setattr(dr, "_gcb_report_failure", lambda c: None)
    monkeypatch.setattr(dr, "_emit_event", lambda ev: events.append(ev))
    return events


def test_extract_finish_reason_length():
    assert dr._extract_finish_reason({"choices": [{"finish_reason": "length"}]}) == "length"
    assert dr._extract_finish_reason({"choices": [{}]}) == "UNKNOWN"


def test_truncation_continues_then_completes(_stub, monkeypatch):
    seq = [_mk("part1", truncated=True), _mk("full-final")]
    calls = {"n": 0}

    def _fake(accumulated, escalate=False, loop_start=None):
        i = calls["n"]
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr(dr, "_call_openai", _fake)
    res = dr._run_design_loop("p", "c", session="S-TEST")
    assert res["ok"] is True
    assert res["text"] == "full-final"
    assert res["rounds_used"] == 0
    assert calls["n"] == 2
    assert len([e for e in _stub if e.get("tag") == "TRUNCATION_CONTINUE"]) == 1


def test_truncation_caps_at_max(_stub, monkeypatch):
    calls = {"n": 0}

    def _always(accumulated, escalate=False, loop_start=None):
        calls["n"] += 1
        return _mk("partial", truncated=True)

    monkeypatch.setattr(dr, "_call_openai", _always)
    res = dr._run_design_loop("p", "c", session="S-TEST")
    assert dr.MAX_TRUNCATION_CONTINUE == 2
    assert len([e for e in _stub if e.get("tag") == "TRUNCATION_CONTINUE"]) == 2
    assert calls["n"] == 3
    assert res["ok"] is True
    assert res["text"] == "partial"

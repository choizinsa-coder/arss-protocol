# EAG-S378-RC-E-TC-ADD-001
# EAG-S429-RC-E-CONTRACT-SUPERSEDE-001: `text` expectation superseded (accumulate, not last-wins).
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
    # EAG-S429-RC-E-CONTRACT-SUPERSEDE: S378 last-wins `text` superseded by S429 accumulation.
    # RC-E core (detect/continue/cap) unchanged; only `text` semantics updated.
    assert res["text"] == "part1full-final"
    assert res.get("text_complete") is True
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
    # RC-E core contract (state transition): continue is capped at
    # MAX_TRUNCATION_CONTINUE and the cap is never exceeded. Verified via the
    # TRUNCATION_CONTINUE event sequence, NOT the raw call count, so RC-F's
    # post-cap CHUNK_SWITCH stays decoupled (CHUNK_SWITCH is asserted in
    # test_domi_runtime_rc_f.py, keeping RC-E and RC-F contracts separate).
    continue_events = [e for e in _stub if e.get("tag") == "TRUNCATION_CONTINUE"]
    assert dr.MAX_TRUNCATION_CONTINUE == 2
    assert len(continue_events) == dr.MAX_TRUNCATION_CONTINUE
    attempts = [e.get("attempt") for e in continue_events]
    assert attempts == list(range(1, dr.MAX_TRUNCATION_CONTINUE + 1))
    assert max(attempts) <= dr.MAX_TRUNCATION_CONTINUE
    assert res["ok"] is True

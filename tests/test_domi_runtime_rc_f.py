# EAG-S380-RC-F-PAYLOAD-001 regression lock:
#   RC-F lightweight payload - constants, BTB cross-request handoff
#   (new-task / resume / fail-closed), runtime_state non-collision,
#   R5 tool-response cap, R3 chunk switch. RC-E logic untouched.
import json
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


def test_rc_f_constants():
    assert dr.SOFT_OUTPUT_TOKEN_TARGET == 2000
    assert dr.SUMMARY_BUDGET_TOKENS == 500
    assert dr.TOOL_RESPONSE_TOKEN_LIMIT == 2000
    assert dr.MAX_BTB_HANDOFF == 2
    assert 30 <= dr.BTB_BUDGET_SECONDS <= 115
    assert dr.BTB_BUDGET_SECONDS % 5 == 0


def test_btb_persist_no_collision(tmp_path, monkeypatch):
    f = tmp_path / "runtime_state.json"
    f.write_text(json.dumps({"existing_key": 123}), encoding="utf-8")
    monkeypatch.setattr(dr, "MEM_STATE_FILE", str(f))
    monkeypatch.setattr(dr, "_ensure_memory_dirs", lambda: None)
    dr._rc_f_save_btb_handoff("S-P", 1)
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["existing_key"] == 123
    assert data["btb_handoff"]["S-P"] == 1
    assert dr._rc_f_load_btb_handoff("S-P") == 1


def test_btb_handoff_new_task(_stub, monkeypatch):
    monkeypatch.setattr(dr, "BTB_BUDGET_SECONDS", 0)
    monkeypatch.setattr(dr, "_call_openai", lambda *a, **k: _mk("x"))
    monkeypatch.setattr(dr, "_rc_f_save_btb_handoff", lambda s, c: None)
    res = dr._run_design_loop("plain prompt no marker", "ctx", session="S-BTB1")
    assert res["ok"] is True
    assert res["btb_handoff"] == 1
    assert "[BTB_HANDOFF_RESUME]" in res["text"]
    assert any(e.get("tag") == "BTB_HANDOFF" for e in _stub)


def test_btb_handoff_resume_increments(_stub, monkeypatch):
    monkeypatch.setattr(dr, "BTB_BUDGET_SECONDS", 0)
    monkeypatch.setattr(dr, "_rc_f_load_btb_handoff", lambda s: 1)
    monkeypatch.setattr(dr, "_rc_f_save_btb_handoff", lambda s, c: None)
    monkeypatch.setattr(dr, "_call_openai", lambda *a, **k: _mk("x"))
    res = dr._run_design_loop("x [BTB_HANDOFF_RESUME] y", "ctx", session="S-BTB3")
    assert res["ok"] is True
    assert res["btb_handoff"] == 2


def test_btb_handoff_limit_fail_closed(_stub, monkeypatch):
    monkeypatch.setattr(dr, "BTB_BUDGET_SECONDS", 0)
    monkeypatch.setattr(dr, "MAX_BTB_HANDOFF", 2)
    monkeypatch.setattr(dr, "_rc_f_load_btb_handoff", lambda s: 2)
    monkeypatch.setattr(dr, "_call_openai", lambda *a, **k: _mk("x"))
    res = dr._run_design_loop("resume [BTB_HANDOFF_RESUME] here", "ctx", session="S-BTB2")
    assert res["ok"] is False
    assert "BTB_HANDOFF_LIMIT_EXCEEDED" in str(res)


def test_r5_tool_response_cap():
    big = "y" * (dr.TOOL_RESPONSE_TOKEN_LIMIT * 4 + 100)
    out = dr._truncate_tool_result("grep_scoped", big)
    assert "TOOL RESPONSE TRUNCATED" in out
    assert len(out.encode("utf-8")) < len(big.encode("utf-8"))
    small = "z" * 10
    assert dr._truncate_tool_result("grep_scoped", small) == small


def test_r3_chunk_switch_after_continue_limit(_stub, monkeypatch):
    monkeypatch.setattr(dr, "BTB_BUDGET_SECONDS", 999)
    monkeypatch.setattr(dr, "_call_openai", lambda *a, **k: _mk("part", truncated=True))
    res = dr._run_design_loop("p", "c", session="S-CHUNK")
    assert len([e for e in _stub if e.get("tag") == "TRUNCATION_CONTINUE"]) == 2
    assert len([e for e in _stub if e.get("tag") == "CHUNK_SWITCH"]) == 1
    assert res["ok"] is True

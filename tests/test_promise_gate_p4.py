#!/usr/bin/env python3
"""
test_promise_gate_p4.py — 그림자 P4(promise_gate_bridge) 단위테스트.
EAG-S368-CARRYOVER-ELIM-P4-IMPL-001.
모든 파일쓰기 테스트는 tmp_path monkeypatch -> 실경로 무오염.
"""
import json

from tools.monitor import promise_gate_bridge as bridge
from tools.guard.tool_gate_engine_p3 import PromiseGate
from tools.guard.tool_gate_engine import DECISION_DENY


def _patch_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "MODE_PATH", tmp_path / "mode.json")
    monkeypatch.setattr(bridge, "VIOLATIONS_PATH", tmp_path / "viol.jsonl")
    monkeypatch.setattr(bridge, "STATS_PATH", tmp_path / "stats.json")
    monkeypatch.setattr(bridge, "POINTER_PATH", tmp_path / "pointer.json")
    monkeypatch.setattr(bridge, "DECISION_LEDGER", tmp_path / "ledger.jsonl")


def test_read_mode_default_shadow_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "MODE_PATH", tmp_path / "nope.json")
    assert bridge._read_mode() == "SHADOW"


def test_read_mode_enforce(monkeypatch, tmp_path):
    p = tmp_path / "mode.json"
    p.write_text(json.dumps({"mode": "ENFORCE"}), encoding="utf-8")
    monkeypatch.setattr(bridge, "MODE_PATH", p)
    assert bridge._read_mode() == "ENFORCE"


def test_read_mode_corrupt_falls_back_shadow(monkeypatch, tmp_path):
    p = tmp_path / "mode.json"
    p.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(bridge, "MODE_PATH", p)
    assert bridge._read_mode() == "SHADOW"


def test_read_mode_unknown_value_falls_back_shadow(monkeypatch, tmp_path):
    p = tmp_path / "mode.json"
    p.write_text(json.dumps({"mode": "BOGUS"}), encoding="utf-8")
    monkeypatch.setattr(bridge, "MODE_PATH", p)
    assert bridge._read_mode() == "SHADOW"


def test_parse_rule_id():
    assert bridge._parse_rule_id("promise:PC-1") == "PC-1"
    assert bridge._parse_rule_id("PC-1") == "PC-1"
    assert bridge._parse_rule_id("") == ""


def test_pattern_hash_deterministic():
    h1 = bridge._pattern_hash("PC-1", "")
    h2 = bridge._pattern_hash("PC-1", "")
    assert h1 == h2
    assert len(h1) == 64
    assert h1 != bridge._pattern_hash("PC-3", "")


def test_infer_tool():
    assert bridge._infer_tool("caddy ran git_commit for X") == "git_commit"
    assert bridge._infer_tool("nothing here") == ""


def test_rotate_lines():
    lines = [f"{i}\n" for i in range(10)]
    assert bridge._rotate_lines(lines, 5) == lines[-5:]
    assert bridge._rotate_lines(lines, 20) == lines


def test_construct_state_absent_ledger(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    st = bridge._construct_promise_state()
    assert st["session_trail"] == []
    assert st["agent_output"] == ""
    assert st["session_state"]["eag_present"] is True
    assert st["session_state"]["next_steps_checked"] is True


def test_shadow_never_fires_absent_ledger(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    out = bridge.check_promise_gate_trigger("MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["trigger"] == "Promise_Gate"
    assert out["fired"] is False
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["total_inconclusive"] == 1
    assert stats["total_runs"] == 1


def test_shadow_never_fires_even_with_deny(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({"subject": "caddy attempted python -c inline"}) + "\n",
        encoding="utf-8")
    out = bridge.check_promise_gate_trigger("MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["fired"] is False
    viol = (tmp_path / "viol.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(viol) >= 1
    rec = json.loads(viol[0])
    assert rec["rule_id"] == "PC-1"
    assert rec["decision"] == DECISION_DENY
    assert rec["shadow_mode"] is True
    assert rec["schema"] == "promise_violation_v1"


def test_enforce_deny_fires(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    (tmp_path / "mode.json").write_text(json.dumps({"mode": "ENFORCE"}), encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({"subject": "caddy attempted python -c inline"}) + "\n",
        encoding="utf-8")
    out = bridge.check_promise_gate_trigger("MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["fired"] is True
    detail = json.loads(out["detail"])
    assert detail["mode"] == "ENFORCE"
    assert any(v["rule_id"] == "PC-1" for v in detail["violations"])


def test_enforce_clean_ledger_no_fire(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    (tmp_path / "mode.json").write_text(json.dumps({"mode": "ENFORCE"}), encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text(
        json.dumps({"subject": "caddy ran read_file for observation"}) + "\n",
        encoding="utf-8")
    out = bridge.check_promise_gate_trigger("MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["fired"] is False


def test_promisegate_deny_path_direct():
    pg = PromiseGate()
    results = pg.promise_check(
        session_trail=[], agent_output="tried python -c oneliner", session_state={})
    assert any(r.decision == DECISION_DENY and "PC-1" in r.validator for r in results)


def test_write_paths_under_monitor_dir():
    md = str(bridge.MONITOR_DIR)
    for p in (bridge.MODE_PATH, bridge.VIOLATIONS_PATH, bridge.STATS_PATH):
        assert str(p).startswith(md)

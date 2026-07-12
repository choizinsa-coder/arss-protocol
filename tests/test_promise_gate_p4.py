#!/usr/bin/env python3
"""
test_promise_gate_p4.py — 그림자 P4(promise_gate_bridge) 단위테스트.
EAG-S368-CARRYOVER-ELIM-P4-IMPL-001.
모든 파일쓰기 테스트는 tmp_path monkeypatch -> 실경로 무오염.
"""
import json

from tools.monitor import promise_gate_bridge as bridge
from tools.guard.tool_gate_engine_p3 import PromiseGate
from tools.guard.tool_gate_engine import DECISION_DENY, DECISION_WARN


def _patch_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "MODE_PATH", tmp_path / "mode.json")
    monkeypatch.setattr(bridge, "VIOLATIONS_PATH", tmp_path / "viol.jsonl")
    monkeypatch.setattr(bridge, "STATS_PATH", tmp_path / "stats.json")
    monkeypatch.setattr(bridge, "DEDUP_STATE_PATH", tmp_path / "dedup.jsonl")
    monkeypatch.setattr(bridge, "POINTER_PATH", tmp_path / "pointer.json")
    monkeypatch.setattr(bridge, "DECISION_LEDGER", tmp_path / "ledger.jsonl")
    monkeypatch.setattr(bridge, "EXEC_AUDIT_LOG", tmp_path / "exec_audit.log")


def _write_exec_log(tmp_path, items):
    lines = []
    for cmd, sno in items:
        lines.append(json.dumps({
            "stage": "PRE", "command": cmd, "actor_id": "caddy",
            "approval_id": "EAG-S%d-T-001" % sno}))
    (tmp_path / "exec_audit.log").write_text(
        chr(10).join(lines) + chr(10), encoding="utf-8")


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


def test_shadow_records_pc3_warn(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    _write_exec_log(tmp_path, [("write_script", 390), ("git_commit", 390)])
    out = bridge.check_promise_gate_trigger(
        "MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["fired"] is False
    viol = (tmp_path / "viol.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    rec = json.loads(viol[0])
    assert rec["rule_id"] == "PC-3"
    assert rec["decision"] == DECISION_WARN
    assert rec["shadow_mode"] is True
    assert rec["schema"] == "promise_violation_v1"


def test_enforce_pc3_warn_fires_once(monkeypatch, tmp_path):
    # EAG-S392: WARN promotion. Supersedes test_enforce_pc3_warn_does_not_fire
    # (S368 contract: WARN never fired). A new violation now fires exactly
    # once; repeated batches must NOT re-alert (dedup, EAG-S391).
    _patch_tmp(monkeypatch, tmp_path)
    _write_pointer(tmp_path, 390)
    (tmp_path / "mode.json").write_text(
        json.dumps({"mode": "ENFORCE"}), encoding="utf-8")
    _write_exec_log(tmp_path, [("write_script", 390), ("git_commit", 390)])
    out1 = bridge.check_promise_gate_trigger(
        "MON-1", "2026-07-12T00:00:00+00:00")
    assert out1["fired"] is True
    assert "PC-3" in out1["detail"]
    out2 = bridge.check_promise_gate_trigger(
        "MON-2", "2026-07-12T00:05:00+00:00")
    assert out2["fired"] is False
    assert out2["detail"] == ""


def test_enforce_clean_trail_no_fire(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    (tmp_path / "mode.json").write_text(
        json.dumps({"mode": "ENFORCE"}), encoding="utf-8")
    _write_exec_log(tmp_path, [("git_status", 390), ("git_commit", 390)])
    out = bridge.check_promise_gate_trigger(
        "MON-TEST", "2026-07-10T00:00:00+00:00")
    assert out["fired"] is False
    assert not (tmp_path / "viol.jsonl").exists()


def test_stats_exposes_not_evaluable(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    _write_exec_log(tmp_path, [("git_status", 390), ("git_commit", 390)])
    bridge.check_promise_gate_trigger(
        "MON-TEST", "2026-07-10T00:00:00+00:00")
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["evaluable_rules"] == ["PC-3"]
    assert stats["not_evaluable_count"] == 4
    rules = [x["rule"] for x in stats["not_evaluable"]]
    assert rules == ["PC-1", "PC-6", "LESSON-002", "LESSON-023"]


def test_receipt_and_post_lines_excluded(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    lines = [
        json.dumps({"receipt_type": "EVIDENCE_RECEIPT",
                    "action": "exec_scoped:git_commit"}),
        json.dumps({"stage": "POST_OK", "command": "git_commit",
                    "approval_id": "EAG-S390-T-001"}),
        json.dumps({"stage": "PRE", "command": "git_status",
                    "approval_id": "EAG-S390-T-001"}),
    ]
    (tmp_path / "exec_audit.log").write_text(
        chr(10).join(lines) + chr(10), encoding="utf-8")
    st = bridge._construct_promise_state()
    assert [e["tool"] for e in st["session_trail"]] == ["git_status"]


def test_session_filter_latest_only(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    _write_exec_log(tmp_path, [("git_commit", 389), ("git_status", 390),
                               ("git_commit", 390)])
    st = bridge._construct_promise_state()
    assert [e["tool"] for e in st["session_trail"]] == ["git_status", "git_commit"]


def test_promisegate_deny_path_direct():
    pg = PromiseGate()
    results = pg.promise_check(
        session_trail=[], agent_output="tried python -c oneliner", session_state={})
    assert any(r.decision == DECISION_DENY and "PC-1" in r.validator for r in results)


def test_write_paths_under_monitor_dir():
    md = str(bridge.MONITOR_DIR)
    for p in (bridge.MODE_PATH, bridge.VIOLATIONS_PATH, bridge.STATS_PATH):
        assert str(p).startswith(md)


def _write_pointer(tmp_path, sno):
    (tmp_path / "pointer.json").write_text(
        json.dumps({"current_session": sno}), encoding="utf-8")


def test_dedup_suppresses_repeat_batch(monkeypatch, tmp_path):
    # EAG-S391: same violation re-evaluated every batch must be recorded once.
    _patch_tmp(monkeypatch, tmp_path)
    _write_pointer(tmp_path, 390)
    _write_exec_log(tmp_path, [("write_script", 390), ("git_commit", 390)])
    bridge.check_promise_gate_trigger("MON-1", "2026-07-12T00:00:00+00:00")
    bridge.check_promise_gate_trigger("MON-2", "2026-07-12T00:05:00+00:00")
    bridge.check_promise_gate_trigger("MON-3", "2026-07-12T00:10:00+00:00")
    viol = (tmp_path / "viol.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(viol) == 1
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["total_warn"] == 1
    assert stats["total_runs"] == 3


def test_dedup_distinct_sessions_not_suppressed(monkeypatch, tmp_path):
    _patch_tmp(monkeypatch, tmp_path)
    _write_pointer(tmp_path, 390)
    _write_exec_log(tmp_path, [("write_script", 390), ("git_commit", 390)])
    bridge.check_promise_gate_trigger("MON-1", "2026-07-12T00:00:00+00:00")
    _write_pointer(tmp_path, 391)
    _write_exec_log(tmp_path, [("write_script", 391), ("git_commit", 391)])
    bridge.check_promise_gate_trigger("MON-2", "2026-07-12T00:05:00+00:00")
    viol = (tmp_path / "viol.jsonl").read_text(
        encoding="utf-8").strip().splitlines()
    assert len(viol) == 2
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["total_warn"] == 2


def test_dedup_state_path_under_monitor_dir():
    assert str(bridge.DEDUP_STATE_PATH).startswith(str(bridge.MONITOR_DIR))
    assert str(bridge.DEDUP_STATE_PATH).endswith("promise_dedup_seen.jsonl")

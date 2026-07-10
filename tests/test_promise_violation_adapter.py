"""
test_promise_violation_adapter.py
P5 9 TC
EAG: EAG-S369-CARRYOVER-ELIM-P5-IMPL-001
"""
import json, os, uuid, sys
from pathlib import Path
import pytest

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

@pytest.fixture()
def tmp_dir(tmp_path):
    return tmp_path

def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

def test_p5_1_audit_trail_deny_variants(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_audit_trail, _to_violation
    log_path = tmp_dir / "audit_trail.log"
    entries = [
        {"event_type": "TOOL_DENY", "tool_name": "mystery_tool", "layer": "DENY",
         "result_summary": "DENIED reason=NOT_IN_REGISTRY", "timestamp": "2026-07-10T10:00:00+00:00"},
        {"event_type": "TOOL_DENY", "tool_name": "get_all_context", "layer": "DENY",
         "result_summary": "DENIED reason=FORBIDDEN_TOOLS", "timestamp": "2026-07-10T10:00:01+00:00"},
        {"event_type": "TOOL_DENY", "tool_name": "_hang_tool", "layer": "DENY",
         "result_summary": "DENIED reason=T2_TOOL_EXECUTION_TIMEOUT", "timestamp": "2026-07-10T10:00:02+00:00"},
        {"event_type": "TOOL_CALL", "tool_name": "ping", "result_summary": "ok"},
    ]
    _write_jsonl(log_path, entries)
    records, new_offset = scan_audit_trail(log_path, 0)
    assert len(records) == 3
    rule_ids = [r["rule_id"] for r in records]
    assert "L1:NOT_IN_REGISTRY" in rule_ids
    assert "L1:FORBIDDEN_TOOLS" in rule_ids
    assert "L1:T2_TOOL_EXECUTION_TIMEOUT" in rule_ids
    assert new_offset > 0
    v = _to_violation(records[0], "MON-TEST", 369)
    assert v["schema"] == "promise_violation_v1"
    assert v["shadow_mode"] is False
    assert v["decision"] == "DENY"
    assert v["session_ref"] == 369
    assert v["agent"] == "unknown"

def test_p5_2_exec_post_fail(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_exec_audit_trail
    log_path = tmp_dir / "exec_audit_trail.log"
    entries = [
        {"audit_id": str(uuid.uuid4()), "stage": "PRE", "command": "pytest",
         "actor_id": "caddy", "exit_code": None, "timestamp": "2026-07-10T10:00:00+09:00"},
        {"audit_id": str(uuid.uuid4()), "stage": "POST_FAIL", "command": "pytest",
         "actor_id": "caddy", "exit_code": 1, "timestamp": "2026-07-10T10:00:05+09:00"},
    ]
    _write_jsonl(log_path, entries)
    records, new_offset = scan_exec_audit_trail(log_path, 0)
    assert len(records) == 1
    r = records[0]
    assert r["rule_id"] == "EXEC:FAIL:pytest"
    assert r["agent"] == "caddy"
    assert "exit_code=1" in r["raw_reason"]

def test_p5_3_evidence_receipt_fail(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_exec_audit_trail
    log_path = tmp_dir / "exec_audit_trail.log"
    entries = [
        {"receipt_type": "EVIDENCE_RECEIPT", "action": "exec_scoped:pytest", "result": "FAIL",
         "actor_id": "caddy", "timestamp": "2026-07-10T10:00:10+09:00"},
        {"receipt_type": "EVIDENCE_RECEIPT", "action": "exec_scoped:git_commit", "result": "PASS",
         "actor_id": "caddy", "timestamp": "2026-07-10T10:00:11+09:00"},
    ]
    _write_jsonl(log_path, entries)
    records, _ = scan_exec_audit_trail(log_path, 0)
    assert len(records) == 1
    assert records[0]["rule_id"].startswith("EXEC:RECEIPT_FAIL:")

def test_p5_4_offset_no_duplicate(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_audit_trail
    log_path = tmp_dir / "audit_trail.log"
    entry1 = {"event_type": "TOOL_DENY", "tool_name": "tool_a", "layer": "DENY",
              "result_summary": "DENIED reason=NOT_IN_REGISTRY", "timestamp": "2026-07-10T10:00:00+00:00"}
    _write_jsonl(log_path, [entry1])
    records1, offset1 = scan_audit_trail(log_path, 0)
    assert len(records1) == 1
    records2, offset2 = scan_audit_trail(log_path, offset1)
    assert len(records2) == 0
    assert offset2 == offset1
    entry2 = {"event_type": "TOOL_DENY", "tool_name": "tool_b", "layer": "DENY",
              "result_summary": "DENIED reason=FORBIDDEN_TOOLS", "timestamp": "2026-07-10T10:00:01+00:00"}
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry2) + "\n")
    records3, offset3 = scan_audit_trail(log_path, offset2)
    assert len(records3) == 1
    assert records3[0]["trigger_tool"] == "tool_b"
    assert offset3 > offset2

def test_p5_5_file_rotation_truncate(tmp_dir, monkeypatch):
    import tools.monitor.promise_violation_adapter as pva
    log_path        = tmp_dir / "audit_trail.log"
    violations_path = tmp_dir / "promise_violations.jsonl"
    position_path   = tmp_dir / "promise_adapter_position.json"
    monkeypatch.setattr(pva, "AUDIT_LOG_PATH",      log_path)
    monkeypatch.setattr(pva, "EXEC_AUDIT_LOG_PATH", tmp_dir / "exec_audit_trail.log")
    monkeypatch.setattr(pva, "VIOLATIONS_PATH",     violations_path)
    monkeypatch.setattr(pva, "POSITION_PATH",       position_path)
    monkeypatch.setattr(pva, "MONITOR_DIR",         tmp_dir)
    (tmp_dir / "exec_audit_trail.log").write_text("")
    entry1 = {"event_type": "TOOL_DENY", "tool_name": "old_tool", "layer": "DENY",
              "result_summary": "DENIED reason=NOT_IN_REGISTRY", "timestamp": "2026-07-10T10:00:00+00:00"}
    _write_jsonl(log_path, [entry1])
    result1 = pva.scan_and_record("MON-1", "2026-07-10T10:00:00+00:00")
    assert result1["scanned_a"] == 1
    positions_after = json.loads(position_path.read_text())
    stored_offset = positions_after[str(log_path)]["offset"]
    assert stored_offset > 0
    entry2 = {"event_type": "TOOL_DENY", "tool_name": "new_tool", "layer": "DENY",
              "result_summary": "DENIED reason=FORBIDDEN_TOOLS", "timestamp": "2026-07-10T10:01:00+00:00"}
    log_path.write_text(json.dumps(entry2) + "\n")
    new_size = log_path.stat().st_size
    if new_size >= stored_offset:
        positions_after[str(log_path)]["offset"] = new_size + 100
        position_path.write_text(json.dumps(positions_after))
    result2 = pva.scan_and_record("MON-2", "2026-07-10T10:01:00+00:00")
    assert result2["scanned_a"] == 1
    all_violations = [json.loads(ln) for ln in violations_path.read_text().splitlines() if ln.strip()]
    assert "new_tool" in [v["trigger_tool"] for v in all_violations]

def test_p5_6_empty_log(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_audit_trail, scan_exec_audit_trail
    log_a = tmp_dir / "audit_trail.log"
    log_b = tmp_dir / "exec_audit_trail.log"
    log_a.write_text("")
    log_b.write_text("")
    records_a, off_a = scan_audit_trail(log_a, 0)
    records_b, off_b = scan_exec_audit_trail(log_b, 0)
    assert records_a == [] and records_b == []
    assert off_a == 0 and off_b == 0

def test_p5_7_malformed_json(tmp_dir):
    from tools.monitor.promise_violation_adapter import scan_audit_trail
    log_path = tmp_dir / "audit_trail.log"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("{broken json line\n")
        f.write(json.dumps({"event_type": "TOOL_DENY", "tool_name": "tool_x", "layer": "DENY",
                             "result_summary": "DENIED reason=NOT_IN_REGISTRY",
                             "timestamp": "2026-07-10T10:00:00+00:00"}) + "\n")
        f.write("another broken!!\n")
    records, _ = scan_audit_trail(log_path, 0)
    assert len(records) == 1
    assert records[0]["trigger_tool"] == "tool_x"

def test_p5_8_monitor_isolation(tmp_dir, monkeypatch):
    import tools.monitor.promise_violation_adapter as pva
    def _raise(*args, **kwargs):
        raise RuntimeError("force")
    monkeypatch.setattr(pva, "_append_rotated", _raise)
    result = pva.scan_and_record("MON-TEST", "2026-07-10T10:00:00+00:00")
    assert isinstance(result, dict)
    assert result.get("recorded", 0) == 0

def test_p5_9_rotation(tmp_dir, monkeypatch):
    import tools.monitor.promise_violation_adapter as pva
    monkeypatch.setattr(pva, "VIOLATIONS_PATH",     tmp_dir / "promise_violations.jsonl")
    monkeypatch.setattr(pva, "VIOLATIONS_MAX_LINES", 10)
    monkeypatch.setattr(pva, "MONITOR_DIR",          tmp_dir)
    lines = [json.dumps({"n": i}) for i in range(15)]
    pva._append_rotated(tmp_dir / "promise_violations.jsonl", lines)
    with open(tmp_dir / "promise_violations.jsonl", encoding="utf-8") as f:
        saved = f.readlines()
    assert len(saved) == 10
    assert json.loads(saved[0])["n"] == 5

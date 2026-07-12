"""
test_p5_phase_c_axis_s397.py
P5.1 C axis - PHASE_C governance-violation DENY scan.
EAG: EAG-S397-P5.1-PHASE-C-AXIS-001

7 TCs. 0 existing TC modified. All production paths monkeypatched to tmp.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def _pc(reason, agent="caddy", decision="DENY", ts="2026-07-12T10:00:00+09:00",
        returned_scope="/opt/arss/engine/arss-protocol/some/path.py"):
    """Build one PHASE_C audit record (mcp_audit_broker.write_audit schema)."""
    return {
        "timestamp": ts,
        "agent_id": agent,
        "requested_shard": "read",
        "returned_scope": returned_scope,
        "decision": decision,
        "reason": reason,
        "source_hash": "deadbeef",
        "load_state": "DENIED" if decision == "DENY" else "ACTIVE",
        "retrieval_class": "CLASS-D" if decision == "DENY" else "CLASS-B",
        "nonce_hash": None,
    }


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Every production path -> tmp. Nothing may touch the real monitor dir."""
    import tools.monitor.promise_violation_adapter as pva
    phase_c = tmp_path / "mcp_audit.log"
    audit_a = tmp_path / "audit_trail.log"
    audit_b = tmp_path / "exec_audit_trail.log"
    audit_a.write_text("", encoding="utf-8")
    audit_b.write_text("", encoding="utf-8")
    monkeypatch.setattr(pva, "PHASE_C_LOG_PATH",    phase_c)
    monkeypatch.setattr(pva, "AUDIT_LOG_PATH",      audit_a)
    monkeypatch.setattr(pva, "EXEC_AUDIT_LOG_PATH", audit_b)
    monkeypatch.setattr(pva, "VIOLATIONS_PATH",     tmp_path / "promise_violations.jsonl")
    monkeypatch.setattr(pva, "POSITION_PATH",       tmp_path / "promise_adapter_position.json")
    monkeypatch.setattr(pva, "MONITOR_DIR",         tmp_path)
    return pva, tmp_path, phase_c


# TC-1: governance DENY collected, navigation DENY excluded
def test_p5c_1_governance_only(isolated):
    pva, tmp, phase_c = isolated
    _write_jsonl(phase_c, [
        _pc("read_file:OBSERVATION:DENY:UNKNOWN_PURPOSE"),
        _pc("list_dir:OBSERVATION:DENY:PATH_NOT_IN_WHITELIST"),
        _pc("read_file:OBSERVATION:DENY:NOT_A_FILE"),          # navigation -> excluded
        _pc("grep_scoped:OBSERVATION:DENY:PATH_DEPTH_EXCEEDED"),  # navigation -> excluded
        _pc("list_dir:OBSERVATION:DENY:NOT_A_DIRECTORY"),      # navigation -> excluded
        _pc("read_file:OBSERVATION:ALLOW:ok", decision="ALLOW"),  # not a DENY
    ])
    records, new_offset = pva.scan_phase_c(phase_c, 0)
    assert len(records) == 2
    rule_ids = sorted(r["rule_id"] for r in records)
    assert rule_ids == ["PC:PATH_NOT_IN_WHITELIST", "PC:UNKNOWN_PURPOSE"]
    assert new_offset > 0
    # navigation reasons must never appear
    for r in records:
        assert r["raw_reason"] not in ("NOT_A_FILE", "PATH_DEPTH_EXCEEDED", "NOT_A_DIRECTORY")


# TC-2: trigger_tool comes from the reason prefix, NOT returned_scope (path)
def test_p5c_2_trigger_tool_is_tool_not_path(isolated):
    pva, tmp, phase_c = isolated
    _write_jsonl(phase_c, [
        _pc("grep_scoped:OBSERVATION:DENY:PATH_NOT_IN_WHITELIST",
            returned_scope="/opt/arss/engine/arss-protocol/etc/whatever.py"),
    ])
    records, _ = pva.scan_phase_c(phase_c, 0)
    assert len(records) == 1
    assert records[0]["trigger_tool"] == "grep_scoped"
    assert "/" not in records[0]["trigger_tool"]
    assert records[0]["agent"] == "caddy"


# TC-3: bridge-format DENY (no ":DENY:" separator) + CONTAINMENT_ prefix
def test_p5c_3_bridge_format_and_containment(isolated):
    pva, tmp, phase_c = isolated
    _write_jsonl(phase_c, [
        _pc("AGENT_NOT_IN_ALLOWLIST", agent="unknown"),
        _pc("CONTAINMENT_REQUEST_DENIED:initialize", agent="SYSTEM"),
        _pc("SOME_UNLISTED_REASON"),   # not in allowlist -> excluded
    ])
    records, _ = pva.scan_phase_c(phase_c, 0)
    rule_ids = sorted(r["rule_id"] for r in records)
    assert rule_ids == ["PC:AGENT_NOT_IN_ALLOWLIST",
                        "PC:CONTAINMENT_REQUEST_DENIED:initialize"]
    # bridge format has no tool prefix
    for r in records:
        assert r["trigger_tool"] == ""


# TC-4: offset advances - no duplicate on re-scan
def test_p5c_4_offset_no_duplicate(isolated):
    pva, tmp, phase_c = isolated
    _write_jsonl(phase_c, [_pc("read_file:OBSERVATION:DENY:UNKNOWN_PURPOSE")])
    rec1, off1 = pva.scan_phase_c(phase_c, 0)
    assert len(rec1) == 1
    rec2, off2 = pva.scan_phase_c(phase_c, off1)
    assert rec2 == []
    assert off2 == off1
    with open(phase_c, "a", encoding="utf-8") as f:
        f.write(json.dumps(_pc("list_dir:OBSERVATION:DENY:PATH_NOT_IN_WHITELIST")) + "\n")
    rec3, off3 = pva.scan_phase_c(phase_c, off2)
    assert len(rec3) == 1
    assert rec3[0]["rule_id"] == "PC:PATH_NOT_IN_WHITELIST"
    assert off3 > off2


# TC-5: scan_and_record integration - scanned_c reported, positions persisted,
#       and NO runtime seeding (a fresh position file must NOT skip the backlog)
def test_p5c_5_scan_and_record_integration(isolated):
    pva, tmp, phase_c = isolated
    _write_jsonl(phase_c, [
        _pc("read_file:OBSERVATION:DENY:UNKNOWN_PURPOSE"),
        _pc("read_file:OBSERVATION:DENY:NOT_A_FILE"),   # navigation -> excluded
        _pc("check_service_state:OBSERVATION:DENY:SERVICE_NOT_IN_ALLOWLIST"),
    ])
    result = pva.scan_and_record("MON-S397", "2026-07-12T10:00:00+09:00")
    assert result["scanned_c"] == 2          # navigation excluded
    assert result["scanned_a"] == 0
    assert result["scanned_b"] == 0
    assert result["recorded"] == 2

    # positions persisted for the C key
    positions = json.loads((tmp / "promise_adapter_position.json").read_text())
    assert str(phase_c) in positions
    assert positions[str(phase_c)]["offset"] > 0

    # violations written with the promise_violation_v1 schema
    lines = [json.loads(l) for l in
             (tmp / "promise_violations.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    for v in lines:
        assert v["schema"] == "promise_violation_v1"
        assert v["decision"] == "DENY"
        assert v["rule_id"].startswith("PC:")
        assert v["shadow_mode"] is False

    # second run must not re-record (offset held)
    result2 = pva.scan_and_record("MON-S397-2", "2026-07-12T10:05:00+09:00")
    assert result2["scanned_c"] == 0


# TC-6: empty / missing PHASE_C log is safe
def test_p5c_6_empty_and_missing(isolated):
    pva, tmp, phase_c = isolated
    phase_c.write_text("", encoding="utf-8")
    rec, off = pva.scan_phase_c(phase_c, 0)
    assert rec == [] and off == 0
    missing = tmp / "does_not_exist.log"
    rec2, off2 = pva.scan_phase_c(missing, 0)
    assert rec2 == [] and off2 == 0


# TC-7: malformed JSON lines are skipped, valid ones still collected
def test_p5c_7_malformed_json(isolated):
    pva, tmp, phase_c = isolated
    with open(phase_c, "w", encoding="utf-8") as f:
        f.write("{broken json\n")
        f.write(json.dumps(_pc("read_file:OBSERVATION:DENY:FORBIDDEN_PATH_PATTERN")) + "\n")
        f.write("!!! not json !!!\n")
    records, _ = pva.scan_phase_c(phase_c, 0)
    assert len(records) == 1
    assert records[0]["rule_id"] == "PC:FORBIDDEN_PATH_PATTERN"
    assert records[0]["trigger_tool"] == "read_file"

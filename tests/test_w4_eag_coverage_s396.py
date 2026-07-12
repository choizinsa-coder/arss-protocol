#!/usr/bin/env python3
"""
test_w4_eag_coverage_s396.py
EAG-S396-W4-REDEFINE-IMPL-001
2 new TCs for the w4 EAG coverage metric.
All file paths monkeypatched to tmp_path.
"""
import json
from tools.monitor import aiba_monitor as mod
from tools.monitor.aiba_monitor import GovernanceMonitor


def _write_audit_log(tmp_path, entries):
    """Write PRE-stage exec_audit_trail lines."""
    lines = []
    for approval_id in entries:
        lines.append(json.dumps({
            "stage": "PRE",
            "command": "git_commit",
            "actor_id": "caddy",
            "approval_id": approval_id,
        }))
    (tmp_path / "exec_audit.log").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_ledger(tmp_path, eag_ids):
    lines = [json.dumps({"schema": "decision_ledger_v1", "dc": "DC-3",
                          "eag": eid, "actor": "beo"})
             for eid in eag_ids]
    (tmp_path / "ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_pointer(tmp_path, current_session):
    (tmp_path / "pointer.json").write_text(
        json.dumps({"current_session": current_session}), encoding="utf-8")


# TC-1: partial coverage — 2 of 3 audit EAGs in ledger -> 0.6667
def test_w4_eag_coverage_partial(monkeypatch, tmp_path):
    """EAG-S396: w4 returns coverage ratio when only some EAGs are in ledger."""
    monkeypatch.setattr(mod, "EXEC_AUDIT_LOG_PATH", tmp_path / "exec_audit.log")
    monkeypatch.setattr(mod, "DECISION_LEDGER",     tmp_path / "ledger.jsonl")
    monkeypatch.setattr(mod, "POINTER_PATH_W4",     tmp_path / "pointer.json")
    _write_pointer(tmp_path, 396)
    # 3 distinct EAGs within window (396-3=393..396), 2 in ledger
    _write_audit_log(tmp_path, [
        "EAG-S394-FOO-001",
        "EAG-S395-BAR-001",
        "EAG-S396-BAZ-001",
    ])
    _write_ledger(tmp_path, ["EAG-S394-FOO-001", "EAG-S396-BAZ-001"])
    monitor = GovernanceMonitor(run_id="TEST")
    result = monitor._get_process_compliance_rate()
    assert abs(result - round(2/3, 4)) < 1e-4, f"Expected {round(2/3,4)}, got {result}"


# TC-2: audit log absent -> 1.0 (fail-safe, not a compliance signal)
def test_w4_eag_coverage_audit_absent(monkeypatch, tmp_path):
    """EAG-S396: w4 returns 1.0 when exec_audit_trail does not exist."""
    monkeypatch.setattr(mod, "EXEC_AUDIT_LOG_PATH", tmp_path / "no_such_file.log")
    monkeypatch.setattr(mod, "DECISION_LEDGER",     tmp_path / "ledger.jsonl")
    monkeypatch.setattr(mod, "POINTER_PATH_W4",     tmp_path / "pointer.json")
    monitor = GovernanceMonitor(run_id="TEST")
    result = monitor._get_process_compliance_rate()
    assert result == 1.0, f"Expected 1.0 when audit absent, got {result}"


# TC-3: ledger absent but audit EAGs exist -> 0.0 (true gap, not a safe default)
def test_w4_eag_coverage_ledger_absent(monkeypatch, tmp_path):
    """EAG-S396: w4 returns 0.0 when ledger does not exist but audit EAGs do."""
    monkeypatch.setattr(mod, "EXEC_AUDIT_LOG_PATH", tmp_path / "exec_audit.log")
    monkeypatch.setattr(mod, "DECISION_LEDGER",     tmp_path / "no_ledger.jsonl")
    monkeypatch.setattr(mod, "POINTER_PATH_W4",     tmp_path / "pointer.json")
    _write_pointer(tmp_path, 396)
    _write_audit_log(tmp_path, ["EAG-S395-FOO-001"])
    monitor = GovernanceMonitor(run_id="TEST")
    result = monitor._get_process_compliance_rate()
    assert result == 0.0, f"Expected 0.0 when ledger absent, got {result}"

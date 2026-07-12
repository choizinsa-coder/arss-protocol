#!/usr/bin/env python3
"""
test_p4_dedup_key_fix_s396.py
EAG-S396-P4-DEDUP-KEY-FIX-IMPL-001
2 new TCs for the dedup key stabilization fix.
- All paths monkeypatched to tmp_path (production log zero contamination).
"""
import json
from tools.monitor import promise_gate_bridge as bridge


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
        "\n".join(lines) + "\n", encoding="utf-8")


def _write_pointer(tmp_path, sno):
    (tmp_path / "pointer.json").write_text(
        json.dumps({"current_session": sno}), encoding="utf-8")


# TC-1: session_ref in the constructed state equals trail max sno, NOT POINTER
def test_session_ref_uses_trail_max_sno_not_pointer(monkeypatch, tmp_path):
    """EAG-S396: _construct_promise_state must derive session_ref from exec_audit max sno.
    POINTER is set to a different value to prove they are decoupled."""
    _patch_tmp(monkeypatch, tmp_path)
    # POINTER = 395 (post-close), trail max sno = 394
    _write_pointer(tmp_path, 395)
    _write_exec_log(tmp_path, [("git_status", 394), ("git_commit", 394)])
    st = bridge._construct_promise_state()
    # Must be trail sno (394), not POINTER (395)
    assert st["session_state"]["session_ref"] == 394, (
        f"Expected 394 (trail sno) but got {st['session_state']['session_ref']}")


# TC-2: same violation not re-recorded when only POINTER advances (CLOSE simulation)
def test_dedup_stable_across_close_pointer_advance(monkeypatch, tmp_path):
    """EAG-S396: A violation recorded pre-CLOSE must not be re-recorded post-CLOSE
    when only POINTER increments and the exec_audit trail is unchanged.
    Reproduces the structural defect proven live in S395/S396."""
    _patch_tmp(monkeypatch, tmp_path)
    # Pre-CLOSE: POINTER=394, trail sno=394
    _write_pointer(tmp_path, 394)
    _write_exec_log(tmp_path, [("write_script", 394), ("git_commit", 394)])
    bridge.check_promise_gate_trigger("MON-pre-close", "2026-07-12T07:05:00+00:00")

    # Simulate SESSION CLOSE: POINTER increments to 395, trail unchanged
    _write_pointer(tmp_path, 395)
    # exec_audit log is the same (no new ops in the new session yet)
    # NOTE: bridge reads max sno from exec_audit which still has sno=394
    bridge.check_promise_gate_trigger("MON-post-close", "2026-07-12T07:10:00+00:00")

    # Must have exactly 1 record -- not 2
    viol_text = (tmp_path / "viol.jsonl").read_text(encoding="utf-8").strip()
    records = [l for l in viol_text.splitlines() if l.strip()]
    assert len(records) == 1, (
        f"Expected 1 violation record (dedup stable), got {len(records)}. "
        "Structural duplicate-per-CLOSE defect is present.")
    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["total_warn"] == 1, (
        f"Expected total_warn=1, got {stats['total_warn']}")

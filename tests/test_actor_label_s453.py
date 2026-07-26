# S453 actor/actor_id label contract. EAG-S453-ACTOR-LABEL-FIX-001
# Fixtures deliberately mirror the REAL log shape:
#   POST_FAIL rows carry actor_id, EVIDENCE_RECEIPT rows carry actor.
# The pre-S453 test fixtures used actor_id on BOTH, which is why the label
# defect stayed invisible for 8+ sessions.
import json
import sys
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NL = chr(10)
EXPECTED_KEYS = {"rule_id", "trigger_tool", "agent", "timestamp_iso", "raw_reason"}


def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + NL)


def _receipt(actor_key, actor_val, sa="SA-1", action="exec_scoped:pytest"):
    e = {
        "receipt_type": "EVIDENCE_RECEIPT",
        "action": action,
        "result": "FAIL",
        "evidence_files": [],
        "constraint_registry_hash": "3bf74b2b2f67ea45",
        "decision": "EXECUTED",
        "session_audit_id": sa,
        "timestamp": "2026-07-27T10:00:00+09:00",
    }
    if actor_key:
        e[actor_key] = actor_val
    return e


def _postfail(actor_key, actor_val, sa="SA-2", command="pytest"):
    e = {
        "audit_id": "aid-" + sa,
        "stage": "POST_FAIL",
        "command": command,
        "approval_id": "EAG-S453-TEST-001",
        "detail": "exit_code=1",
        "exit_code": 1,
        "version": "1.5.1",
        "session_audit_id": sa,
        "timestamp": "2026-07-27T10:00:01+09:00",
    }
    if actor_key:
        e[actor_key] = actor_val
    return e


def _scan(tmp_path, entries):
    from tools.monitor.promise_violation_adapter import scan_exec_audit_trail
    log = tmp_path / "exec_audit_trail.log"
    state = tmp_path / "dedup_state.json"
    _write_jsonl(log, entries)
    return scan_exec_audit_trail(log, 0, state_path=state)


def test_s453_l1_orphan_receipt_actor_key(tmp_path):
    records, _off = _scan(tmp_path, [_receipt("actor", "caddy")])
    assert len(records) == 1
    assert records[0]["agent"] == "caddy"
    assert records[0]["rule_id"] == "EXEC:RECEIPT_FAIL:pytest"


def test_s453_l2_postfail_actor_id_key(tmp_path):
    records, _off = _scan(tmp_path, [_postfail("actor_id", "caddy")])
    assert len(records) == 1
    assert records[0]["agent"] == "caddy"
    assert records[0]["rule_id"] == "EXEC:FAIL:pytest"


def test_s453_l3_no_actor_key_falls_back_unknown(tmp_path):
    records, _off = _scan(tmp_path, [_receipt(None, None), _postfail(None, None)])
    assert len(records) == 2
    assert sorted(r["agent"] for r in records) == ["unknown", "unknown"]


def test_s453_l4_actor_id_takes_precedence(tmp_path):
    e = _receipt("actor", "domi")
    e["actor_id"] = "caddy"
    records, _off = _scan(tmp_path, [e])
    assert len(records) == 1
    assert records[0]["agent"] == "caddy"


def test_s453_l5_paired_suppression_unchanged(tmp_path):
    entries = [
        _postfail("actor_id", "caddy", sa="SA-P"),
        _receipt("actor", "caddy", sa="SA-P"),
    ]
    records, _off = _scan(tmp_path, entries)
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:FAIL:pytest"
    assert records[0]["agent"] == "caddy"


def test_s453_l6_record_key_set_fixed(tmp_path):
    records, _off = _scan(tmp_path, [_receipt("actor", "caddy")])
    assert set(records[0].keys()) == EXPECTED_KEYS


def test_s453_l7_phantom_receipt_still_filtered(tmp_path):
    e = _receipt("actor", "caddy")
    e["constraint_registry_hash"] = "no_registry"
    records, _off = _scan(tmp_path, [e])
    assert records == []


def test_s453_l8_mixed_batch_real_shape(tmp_path):
    entries = [
        _postfail("actor_id", "caddy", sa="SA-A", command="run_script"),
        _receipt("actor", "caddy", sa="SA-A", action="exec_scoped:run_script"),
        _receipt("actor", "caddy", sa="SA-B", action="exec_scoped:git_commit"),
    ]
    records, _off = _scan(tmp_path, entries)
    assert sorted(r["rule_id"] for r in records) == [
        "EXEC:FAIL:run_script",
        "EXEC:RECEIPT_FAIL:git_commit",
    ]
    assert all(r["agent"] == "caddy" for r in records)


def test_s453_l9_empty_string_actor_id_falls_through(tmp_path):
    e = _receipt("actor", "caddy")
    e["actor_id"] = ""
    records, _off = _scan(tmp_path, [e])
    assert len(records) == 1
    assert records[0]["agent"] == "caddy"

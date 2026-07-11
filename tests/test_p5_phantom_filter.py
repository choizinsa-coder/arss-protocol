#!/usr/bin/env python3
"""
test_p5_phantom_filter.py
EAG-S374-P5-PHANTOM-FILTER-IMPL-001
Isolated: synthetic tmp exec_audit_trail.log -> scan_exec_audit_trail. No production access.
"""
import json
from tools.monitor.promise_violation_adapter import scan_exec_audit_trail


def _write_log(tmp_path, entries):
    p = tmp_path / "exec_audit_trail.log"
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def test_phantom_receipt_fail_skipped(tmp_path):
    p = _write_log(tmp_path, [{
        "receipt_type": "EVIDENCE_RECEIPT", "result": "FAIL",
        "action": "exec_scoped:pytest", "constraint_registry_hash": "no_registry",
        "session_audit_id": "SA-fb5e796c", "actor_id": "caddy", "timestamp": "t",
    }])
    records, _ = scan_exec_audit_trail(p, 0)
    assert records == []


def test_genuine_receipt_fail_preserved(tmp_path):
    p = _write_log(tmp_path, [{
        "receipt_type": "EVIDENCE_RECEIPT", "result": "FAIL",
        "action": "exec_scoped:pytest", "constraint_registry_hash": "3bf74b2b2f67ea45",
        "session_audit_id": "SA-real", "actor_id": "caddy", "timestamp": "t",
    }])
    records, _ = scan_exec_audit_trail(p, 0)
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:RECEIPT_FAIL:pytest"


def test_pass_receipt_ignored(tmp_path):
    p = _write_log(tmp_path, [{
        "receipt_type": "EVIDENCE_RECEIPT", "result": "PASS",
        "action": "exec_scoped:pytest", "constraint_registry_hash": "no_registry",
        "session_audit_id": "", "actor_id": "caddy", "timestamp": "t",
    }])
    records, _ = scan_exec_audit_trail(p, 0)
    assert records == []


def test_post_fail_preserved(tmp_path):
    p = _write_log(tmp_path, [{
        "stage": "POST_FAIL", "command": "pytest", "actor_id": "caddy",
        "exit_code": 1, "timestamp": "t",
    }])
    records, _ = scan_exec_audit_trail(p, 0)
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:FAIL:pytest"


def test_missing_hash_key_preserved(tmp_path):
    p = _write_log(tmp_path, [{
        "receipt_type": "EVIDENCE_RECEIPT", "result": "FAIL",
        "action": "exec_scoped:pytest", "actor_id": "caddy", "timestamp": "t",
    }])
    records, _ = scan_exec_audit_trail(p, 0)
    assert len(records) == 1

"""
test_exec_dedup_s451.py
EAG-S451-BRIDGE-DEDUP-001

Contract: one exec failure must produce exactly ONE violation, not two.
exec_audit_trail.log records a failure twice - a POST_FAIL stage row and an
EVIDENCE_RECEIPT result=FAIL row - correlated by session_audit_id. The receipt
row is suppressed when its POST_FAIL was already emitted. Orphan receipts and
rows carrying no correlation id are preserved: every ambiguity fails open.

Isolated: synthetic tmp logs + explicit tmp state_path. No production access.
"""
import json
import sys
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.monitor.promise_violation_adapter import scan_exec_audit_trail  # noqa: E402


def _post_fail(sa=None, command="pytest", exit_code=1):
    e = {
        "stage": "POST_FAIL",
        "command": command,
        "actor_id": "caddy",
        "exit_code": exit_code,
        "timestamp": "2026-07-26T10:00:00+09:00",
    }
    if sa:
        e["session_audit_id"] = sa
    return e


def _receipt_fail(sa=None, action="exec_scoped:pytest", chash="3bf74b2b2f67ea45"):
    e = {
        "receipt_type": "EVIDENCE_RECEIPT",
        "result": "FAIL",
        "action": action,
        "constraint_registry_hash": chash,
        "actor_id": "caddy",
        "timestamp": "2026-07-26T10:00:01+09:00",
    }
    if sa:
        e["session_audit_id"] = sa
    return e


def _write(path, entries, mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        for e in entries:
            print(json.dumps(e, ensure_ascii=False), file=f)
    return path


def _log(tmp_path):
    return tmp_path / "exec_audit_trail.log"


def _state(tmp_path):
    return tmp_path / "exec_dedup_state.json"


# TC-D1: paired rows in one batch collapse to a single POST_FAIL violation.
def test_d1_same_batch_pair_collapses(tmp_path):
    log = _write(_log(tmp_path), [_post_fail("SA-1"), _receipt_fail("SA-1")])
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:FAIL:pytest"
    assert "exit_code=1" in records[0]["raw_reason"]


# TC-D2: a pair split across two batches is still collapsed.
def test_d2_cross_batch_pair_collapses(tmp_path):
    log = _log(tmp_path)
    st = _state(tmp_path)
    _write(log, [_post_fail("SA-2")])
    first, offset = scan_exec_audit_trail(log, 0, state_path=st)
    assert len(first) == 1
    _write(log, [_receipt_fail("SA-2")], mode="a")
    second, _ = scan_exec_audit_trail(log, offset, state_path=st)
    assert second == []


# TC-D3: an orphan receipt is a real signal and must survive.
def test_d3_orphan_receipt_preserved(tmp_path):
    log = _write(_log(tmp_path), [_receipt_fail("SA-3")])
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:RECEIPT_FAIL:pytest"


# TC-D4: no correlation id means no provable pair, so both rows survive.
def test_d4_rows_without_sa_preserved(tmp_path):
    log = _write(_log(tmp_path), [_post_fail(), _receipt_fail()])
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 2
    ids = {r["rule_id"] for r in records}
    assert ids == {"EXEC:FAIL:pytest", "EXEC:RECEIPT_FAIL:pytest"}


# TC-D5: distinct incidents are never merged.
def test_d5_distinct_sa_not_suppressed(tmp_path):
    log = _write(_log(tmp_path), [_post_fail("SA-A"), _receipt_fail("SA-B")])
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 2


# TC-D6: two separate failures in one batch stay two.
def test_d6_two_full_pairs_yield_two(tmp_path):
    entries = [
        _post_fail("SA-X"), _receipt_fail("SA-X"),
        _post_fail("SA-Y", command="run_script"),
        _receipt_fail("SA-Y", action="exec_scoped:run_script"),
    ]
    log = _write(_log(tmp_path), entries)
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 2
    ids = {r["rule_id"] for r in records}
    assert ids == {"EXEC:FAIL:pytest", "EXEC:FAIL:run_script"}


# TC-D7: a corrupt state file degrades to pre-S451 behaviour, never to a crash.
def test_d7_corrupt_state_fails_open(tmp_path):
    st = _state(tmp_path)
    log = _log(tmp_path)
    st.write_text("{broken json", encoding="utf-8")
    _write(log, [_post_fail("SA-7")])
    first, offset = scan_exec_audit_trail(log, 0, state_path=st)
    assert len(first) == 1
    st.write_text("{broken json", encoding="utf-8")
    _write(log, [_receipt_fail("SA-7")], mode="a")
    second, _ = scan_exec_audit_trail(log, offset, state_path=st)
    assert len(second) == 1
    assert second[0]["rule_id"] == "EXEC:RECEIPT_FAIL:pytest"


# TC-D8: the S374 phantom filter still wins over dedup bookkeeping.
def test_d8_phantom_receipt_still_skipped(tmp_path):
    entries = [_post_fail("SA-8"), _receipt_fail("SA-8", chash="no_registry")]
    log = _write(_log(tmp_path), entries)
    records, _ = scan_exec_audit_trail(log, 0, state_path=_state(tmp_path))
    assert len(records) == 1
    assert records[0]["rule_id"] == "EXEC:FAIL:pytest"


# TC-D9: the pre-S451 two-argument call signature is unbroken.
def test_d9_legacy_signature(tmp_path):
    log = _write(_log(tmp_path), [_post_fail()])
    records, offset = scan_exec_audit_trail(log, 0)
    assert len(records) == 1
    assert offset > 0


# TC-D10: a scan that reads nothing must not create state on disk.
def test_d10_noop_scan_writes_nothing(tmp_path):
    log = _log(tmp_path)
    log.write_text("", encoding="utf-8")
    st = _state(tmp_path)
    records, offset = scan_exec_audit_trail(log, 0, state_path=st)
    assert records == []
    assert offset == 0
    assert not st.exists()


# TC-D11: pending entries expire, so a very late receipt becomes an orphan
# instead of being swallowed forever.
def test_d11_pending_expires(tmp_path):
    log = _log(tmp_path)
    st = _state(tmp_path)
    _write(log, [_post_fail("SA-OLD")])
    _, off1 = scan_exec_audit_trail(log, 0, state_path=st)
    _write(log, [_post_fail("SA-N1")], mode="a")
    _, off2 = scan_exec_audit_trail(log, off1, state_path=st)
    _write(log, [_post_fail("SA-N2")], mode="a")
    _, off3 = scan_exec_audit_trail(log, off2, state_path=st)
    state = json.loads(st.read_text(encoding="utf-8"))
    assert "SA-OLD" not in state["pending"]
    _write(log, [_receipt_fail("SA-OLD")], mode="a")
    late, _ = scan_exec_audit_trail(log, off3, state_path=st)
    assert len(late) == 1
    assert late[0]["rule_id"] == "EXEC:RECEIPT_FAIL:pytest"


# TC-D12: the state file stays a well-formed v1 document.
def test_d12_state_schema(tmp_path):
    log = _write(_log(tmp_path), [_post_fail("SA-12")])
    st = _state(tmp_path)
    scan_exec_audit_trail(log, 0, state_path=st)
    state = json.loads(st.read_text(encoding="utf-8"))
    assert state["schema"] == "exec_dedup_state_v1"
    assert state["batch_counter"] >= 1
    assert "SA-12" in state["pending"]


# TC-D13: suppression must not disturb the byte-offset contract.
def test_d13_offset_contract_intact(tmp_path):
    log = _write(_log(tmp_path), [_post_fail("SA-13"), _receipt_fail("SA-13")])
    st = _state(tmp_path)
    records, offset = scan_exec_audit_trail(log, 0, state_path=st)
    assert len(records) == 1
    assert offset == log.stat().st_size
    again, offset2 = scan_exec_audit_trail(log, offset, state_path=st)
    assert again == []
    assert offset2 == offset

#!/usr/bin/env python3
# test_bridge_permdeny_filter_s452.py
# EAG-S452-PERMDENY-INTAKE-BLOCK-001
# Contracts for the governance-DENY intake block in promise_failure_bridge.
# A DENY the gate correctly refused is not a failure; it must not reach area_15.
# RC-2 PC:* and unregistered deny reasons must still be recorded (fail-closed).
import json
import sys
import importlib
from pathlib import Path
import pytest

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BRIDGE_MOD = "tools.monitor.promise_failure_bridge"
A15_MOD = "tools.governance.area_15_failure_memory"


@pytest.fixture
def env(tmp_path, monkeypatch):
    a15 = importlib.import_module(A15_MOD)
    bridge = importlib.import_module(BRIDGE_MOD)
    fm_path = tmp_path / "failure_memory.jsonl"
    monkeypatch.setattr(a15, "LOG_PATH", fm_path)
    violations = tmp_path / "promise_violations.jsonl"
    position = tmp_path / ".promise_bridge_position.json"
    seen_path = tmp_path / "promise_failure_seen.jsonl"
    monkeypatch.setattr(bridge, "VIOLATIONS_PATH", violations)
    monkeypatch.setattr(bridge, "POSITION_PATH", position)
    monkeypatch.setattr(bridge, "SEEN_PATH", seen_path)
    monkeypatch.setattr(bridge, "MONITOR_DIR", tmp_path)

    def load_fm():
        if not fm_path.exists():
            return []
        rows = fm_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(r) for r in rows if r.strip()]

    return bridge, violations, position, load_fm, seen_path


def _v(vid, rule_id, agent="caddy"):
    return {
        "violation_id": vid,
        "timestamp_iso": "2026-07-27T00:00:00+00:00",
        "session_ref": 452,
        "run_id": "MON-TEST-S452",
        "agent": agent,
        "rule_id": rule_id,
        "decision": "DENY",
        "reason": rule_id.split(":", 1)[-1],
        "hint": None,
        "trigger_tool": "read_file",
        "pattern_hash": "h",
        "shadow_mode": False,
        "schema": "promise_violation_v1",
    }


def _write(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))


def _append(path, records):
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))


def _seed(bridge, violations):
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()


def _run_one(env, rule_id):
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    _append(violations, [_v("v1", rule_id)])
    res = bridge.bridge_promise_violations()
    return res, load_fm()


# --- TC-F1..F4: RC-1 governance DENY is blocked -----------------------------

def test_f1_path_not_in_whitelist_blocked(env):
    res, fm = _run_one(env, "PC:PATH_NOT_IN_WHITELIST")
    assert res["filtered"] == 1
    assert res["bridged"] == 0
    assert fm == []


def test_f2_service_not_in_allowlist_blocked(env):
    res, fm = _run_one(env, "PC:SERVICE_NOT_IN_ALLOWLIST")
    assert res["filtered"] == 1
    assert fm == []


def test_f3_unknown_purpose_blocked(env):
    res, fm = _run_one(env, "PC:UNKNOWN_PURPOSE")
    assert res["filtered"] == 1
    assert fm == []


def test_f4_containment_blocked(env):
    res, fm = _run_one(env, "PC:CONTAINMENT_REQUEST_DENIED:initialize")
    assert res["filtered"] == 1
    assert fm == []


# --- TC-F5..F7: security-relevant and unregistered reasons keep recording ----

def test_f5_auth_mismatch_still_recorded(env):
    res, fm = _run_one(env, "PC:AUTH_MISMATCH")
    assert res["bridged"] == 1
    assert res["filtered"] == 0
    assert len(fm) == 1
    assert fm[0]["error_code"] == "PC:AUTH_MISMATCH"
    assert fm[0]["rc"] == "RC-2"


def test_f6_nonce_replay_still_recorded(env):
    res, fm = _run_one(env, "PC:NONCE_REPLAY")
    assert res["bridged"] == 1
    assert res["filtered"] == 0
    assert len(fm) == 1


def test_f7_unregistered_reason_fail_closed(env):
    # An unknown future deny reason maps to RC-2 and must NOT be silently dropped.
    res, fm = _run_one(env, "PC:BRAND_NEW_REASON_S452")
    assert res["bridged"] == 1
    assert res["filtered"] == 0
    assert fm[0]["error_code"] == "PC:BRAND_NEW_REASON_S452"


# --- TC-F8..F10: mixed input, return contract, non-PC untouched -------------

def test_f8_mixed_batch_splits_correctly(env):
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    _append(violations, [
        _v("m1", "PC:PATH_NOT_IN_WHITELIST"),
        _v("m2", "PC:AUTH_MISMATCH"),
        _v("m3", "PC:SERVICE_NOT_IN_ALLOWLIST"),
        _v("m4", "EXEC:FAIL:run_script"),
    ])
    res = bridge.bridge_promise_violations()
    assert res["filtered"] == 2
    assert res["bridged"] == 2
    codes = sorted(e["error_code"] for e in load_fm())
    assert codes == ["EXEC:FAIL:run_script", "PC:AUTH_MISMATCH"]


def test_f9_return_contract_exact_keys(env):
    # Replaces the exact-dict assertion dropped from the legacy suite: the key
    # set stays pinned, so an unnoticed contract drift is still caught.
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    res = bridge.bridge_promise_violations()
    assert set(res.keys()) == {"bridged", "skipped", "errors", "filtered"}
    assert all(isinstance(v, int) for v in res.values())


def test_f10_non_pc_records_unaffected(env):
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    _append(violations, [
        _v("n1", "L1:NOT_IN_REGISTRY"),
        _v("n2", "L1:FORBIDDEN_TOOLS"),
        _v("n3", "EXEC:RECEIPT_FAIL:pytest"),
    ])
    res = bridge.bridge_promise_violations()
    assert res["bridged"] == 3
    assert res["filtered"] == 0


# --- TC-F11..F12: side-effect containment -----------------------------------

def test_f11_filtered_id_not_in_seen_file(env):
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    _append(violations, [_v("blocked-id", "PC:PATH_NOT_IN_WHITELIST"),
                         _v("kept-id", "PC:AUTH_MISMATCH")])
    bridge.bridge_promise_violations()
    seen = seen_path.read_text(encoding="utf-8") if seen_path.exists() else ""
    assert "kept-id" in seen
    assert "blocked-id" not in seen


def test_f12_violations_file_untouched(env):
    # The audit trail must survive intact: filtering limits what is SUPPLIED
    # to the learning loop, never what is RECORDED.
    bridge, violations, position, load_fm, seen_path = env
    _seed(bridge, violations)
    _append(violations, [_v("a1", "PC:PATH_NOT_IN_WHITELIST")])
    before = violations.read_bytes()
    bridge.bridge_promise_violations()
    assert violations.read_bytes() == before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

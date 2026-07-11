#!/usr/bin/env python3
"""
test_promise_failure_bridge.py — 브리지 검증.
실제 area_15를 tmp 경로로 monkeypatch해 failure_memory.jsonl 오염 방지.
EAG: EAG-S370-LEARNING-LOOP-BRIDGE-IMPL-001
"""
import json
import sys
import importlib
from pathlib import Path
import pytest

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BRIDGE_MOD = "tools.monitor.promise_failure_bridge"
A15_MOD    = "tools.governance.area_15_failure_memory"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """실제 area_15 + 브리지를 tmp 경로로 격리."""
    import importlib
    a15 = importlib.import_module(A15_MOD)
    bridge = importlib.import_module(BRIDGE_MOD)

    # area_15 LOG_PATH를 tmp로 — 실제 failure_memory.jsonl 보호
    fm_path = tmp_path / "failure_memory.jsonl"
    monkeypatch.setattr(a15, "LOG_PATH", fm_path)

    # 브리지 경로 tmp로
    violations = tmp_path / "promise_violations.jsonl"
    position   = tmp_path / ".promise_bridge_position.json"
    monkeypatch.setattr(bridge, "VIOLATIONS_PATH", violations)
    monkeypatch.setattr(bridge, "POSITION_PATH", position)
    monkeypatch.setattr(bridge, "MONITOR_DIR", tmp_path)

    def load_fm():
        if not fm_path.exists():
            return []
        return [json.loads(l) for l in fm_path.read_text(encoding="utf-8").splitlines() if l.strip()]

    return bridge, violations, position, fm_path, load_fm


def _v(vid, rule_id, agent="unknown", reason=None, hint=None):
    return {
        "violation_id": vid, "timestamp_iso": "2026-07-10T00:00:00+00:00",
        "session_ref": 370, "run_id": "MON-TEST", "agent": agent,
        "rule_id": rule_id, "decision": "DENY",
        "reason": reason if reason is not None else rule_id.split(":", 1)[-1],
        "hint": hint, "trigger_tool": "some_tool",
        "pattern_hash": "h", "shadow_mode": False,
        "schema": "promise_violation_v1",
    }


def _write(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append(path, records):
    with open(path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def test_I2_retroactive_skip(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("a", "L1:NOT_IN_REGISTRY"), _v("b", "EXEC:FAIL:run_script")])
    res = bridge.bridge_promise_violations()
    assert res == {"bridged": 0, "skipped": 0, "errors": 0}
    assert load_fm() == []
    pos = json.loads(position.read_text())
    assert pos[str(violations)]["offset"] == violations.stat().st_size


def test_new_records_bridged_real_a15(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [_v("b", "L1:FORBIDDEN_TOOLS", agent="caddy"),
                         _v("c", "L1:T2_TOOL_EXECUTION_TIMEOUT")])
    res = bridge.bridge_promise_violations()
    assert res["bridged"] == 2
    fm = load_fm()
    assert len(fm) == 2
    # 실제 area_15 failure_memory_v1 스키마 확인
    assert all(e["schema"] == "failure_memory_v1" for e in fm)


def test_rc_mapping_real_a15(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [
        _v("r1", "L1:NOT_IN_REGISTRY"),
        _v("r2", "L1:T2_TOOL_EXECUTION_TIMEOUT"),
        _v("r3", "L1:FORBIDDEN_TOOLS"),
        _v("r4", "EXEC:RECEIPT_FAIL:pytest"),
        _v("r5", "EXEC:FAIL:run_script"),
    ])
    bridge.bridge_promise_violations()
    rc = {e["error_code"]: e["rc"] for e in load_fm()}
    assert rc["L1:NOT_IN_REGISTRY"] == "RC-1"
    assert rc["L1:T2_TOOL_EXECUTION_TIMEOUT"] == "RC-1"
    assert rc["L1:FORBIDDEN_TOOLS"] == "RC-2"
    assert rc["EXEC:RECEIPT_FAIL:pytest"] == "RC-2"
    assert rc["EXEC:FAIL:run_script"] == "RC-2"


def test_I4_no_rc3_rc4(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [_v(f"x{i}", "EXEC:FAIL:pytest") for i in range(20)])
    bridge.bridge_promise_violations()
    assert all(e["rc"] in ("RC-1", "RC-2") for e in load_fm())


def test_error_code_and_component(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [
        _v("a", "L1:NOT_IN_REGISTRY", agent="caddy"),
        _v("b", "EXEC:FAIL:run_script", agent="unknown"),
        _v("c", "L1:FORBIDDEN_TOOLS", agent="weird_actor"),
    ])
    bridge.bridge_promise_violations()
    fm = load_fm()
    assert fm[0]["error_code"] == "L1:NOT_IN_REGISTRY"
    assert fm[0]["component"] == "caddy"
    assert fm[1]["component"] == "unknown"
    assert fm[2]["component"] == "unknown"


def test_description_has_violation_id(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [_v("VID-123", "L1:NOT_IN_REGISTRY",
                           reason="not in registry", hint="use registered tool")])
    bridge.bridge_promise_violations()
    desc = load_fm()[0]["description"]
    assert "VID-123" in desc
    assert "not in registry" in desc
    assert "use registered tool" in desc


def test_idempotent_no_reprocess(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    _append(violations, [_v("a", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    n = len(load_fm())
    bridge.bridge_promise_violations()
    assert len(load_fm()) == n


def test_offset_file_independent(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    assert position.name == ".promise_bridge_position.json"
    assert position.exists()


def test_I1_violations_readonly(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY"), _v("a", "EXEC:FAIL:pytest")])
    before = violations.read_bytes()
    bridge.bridge_promise_violations()
    _append(violations, [_v("b", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    assert violations.read_bytes().startswith(before)


def test_failsafe_corrupt_line(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    bridge.bridge_promise_violations()
    with open(violations, "a", encoding="utf-8") as f:
        f.write("{ broken json ][\n")
        f.write(json.dumps(_v("ok", "L1:NOT_IN_REGISTRY")) + "\n")
    res = bridge.bridge_promise_violations()
    assert res["skipped"] >= 1
    assert res["bridged"] == 1


def test_rotation_detected(env):
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY"),
                        _v("pad", "L1:NOT_IN_REGISTRY", reason="x" * 500)])
    bridge.bridge_promise_violations()
    _write(violations, [_v("new", "EXEC:FAIL:pytest")])
    res = bridge.bridge_promise_violations()
    assert res["bridged"] == 1


def test_truncation_phantom_suppressed(env):
    # vector B mirror of test_rotation_detected: head preserved, tail truncated.
    # RC-G: head_sig unchanged -> offset capped -> no phantom re-bridge.
    bridge, violations, position, fm_path, load_fm = env
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY"),
                        _v("pad", "L1:NOT_IN_REGISTRY", reason="x" * 500)])
    bridge.bridge_promise_violations()
    # truncate tail but keep identical head (first line = seed)
    _write(violations, [_v("seed", "L1:NOT_IN_REGISTRY")])
    res = bridge.bridge_promise_violations()
    assert res["bridged"] == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

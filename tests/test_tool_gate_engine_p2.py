"""test_tool_gate_engine_p2.py — 도구 마찰 사전검사기 P2 테스트.
EAG-S366-CARRYOVER-ELIM-P2-IMPL-001
대상: tools/guard/tool_gate_engine_p2.py
"""
import time

from tools.guard.tool_gate_engine import (
    DECISION_ALLOW, DECISION_WARN, DECISION_DENY, REPO_ROOT,
)
from tools.guard.tool_gate_engine_p2 import (
    validate_purpose, validate_l2gate, validate_pytest_slot, validate_freshness,
    ToolGateEngineP2,
    PURPOSE_ALLOWED, PURPOSE_FORBIDDEN, PYTEST_OPTIONS, FRESHNESS_TTL_SECONDS,
)
# SSOT (drift 가드용)
from tools.mcp.mcp_read_server import ALLOWED_PURPOSES as SSOT_ALLOWED_PURPOSES
from tools.mcp.mcp_read_server import FORBIDDEN_PURPOSES as SSOT_FORBIDDEN_PURPOSES
from tools.exec_runtime.aiba_exec_runtime import ALLOWED_PYTEST_OPTIONS as SSOT_PYTEST_OPTIONS


# ── validate_purpose: 2분기 ──
def test_p2_purpose_allow_all_five():
    for p in ("OBSERVATION", "EVIDENCE_INSPECTION", "AUDIT_INSPECTION",
              "CONSISTENCY_CHECK", "STALE_DETECTION"):
        assert validate_purpose(p).decision == DECISION_ALLOW


def test_p2_purpose_deny_freeform():
    r = validate_purpose("read the file to check it")
    assert r.decision == DECISION_DENY
    assert r.hint


def test_p2_purpose_deny_empty():
    assert validate_purpose("").decision == DECISION_DENY


def test_p2_purpose_deny_forbidden():
    r = validate_purpose("EXECUTION_COORDINATION")
    assert r.decision == DECISION_DENY
    assert "orbidden" in r.reason


def test_p2_purpose_deny_lowercase():
    assert validate_purpose("observation").decision == DECISION_DENY


# ── validate_l2gate ──
def test_p2_l2gate_allow_non_run_script():
    assert validate_l2gate("pytest", {}, set()).decision == DECISION_ALLOW


def test_p2_l2gate_allow_measured():
    measured = {"tools/sandbox/caddy/active/x.py"}
    r = validate_l2gate("run_script",
                        {"script_path": "tools/sandbox/caddy/active/x.py"}, measured)
    assert r.decision == DECISION_ALLOW


def test_p2_l2gate_allow_absolute_matches_measured():
    measured = {"tools/sandbox/caddy/active/x.py"}
    abs_p = REPO_ROOT + "/tools/sandbox/caddy/active/x.py"
    assert validate_l2gate("run_script", {"script_path": abs_p}, measured).decision == DECISION_ALLOW


def test_p2_l2gate_warn_unmeasured():
    r = validate_l2gate("run_script",
                        {"script_path": "tools/sandbox/caddy/active/y.py"}, set())
    assert r.decision == DECISION_WARN


def test_p2_l2gate_warn_no_script_path():
    assert validate_l2gate("run_script", {}, set()).decision == DECISION_WARN


# ── validate_pytest_slot ──
def test_p2_pytest_allow_valid_options():
    assert validate_pytest_slot({"options": ["-v", "--tb=short"]}).decision == DECISION_ALLOW


def test_p2_pytest_allow_empty_options():
    assert validate_pytest_slot({"options": []}).decision == DECISION_ALLOW
    assert validate_pytest_slot({}).decision == DECISION_ALLOW


def test_p2_pytest_deny_not_list():
    assert validate_pytest_slot({"options": "-v"}).decision == DECISION_DENY


def test_p2_pytest_deny_invalid_option():
    assert validate_pytest_slot({"options": ["--evil"]}).decision == DECISION_DENY


def test_p2_pytest_deny_path_in_options():
    r = validate_pytest_slot({"options": ["tests/test_x.py"]})
    assert r.decision == DECISION_DENY
    assert r.hint


# ── validate_freshness ──
def test_p2_freshness_allow_fresh():
    mf = {"tools/guard/x.py": time.time()}
    assert validate_freshness("tools/guard/x.py", mf).decision == DECISION_ALLOW


def test_p2_freshness_warn_stale():
    mf = {"tools/guard/x.py": time.time() - (FRESHNESS_TTL_SECONDS + 100)}
    assert validate_freshness("tools/guard/x.py", mf).decision == DECISION_WARN


def test_p2_freshness_warn_unmeasured():
    assert validate_freshness("tools/guard/x.py", {}).decision == DECISION_WARN


# ── ToolGateEngineP2 통합 ──
def test_p2_engine_record_measurement_stamps_freshness():
    eng = ToolGateEngineP2()
    eng.record_measurement("tools/guard/x.py")
    assert "tools/guard/x.py" in eng.measured_paths
    assert "tools/guard/x.py" in eng.measured_freshness
    assert eng.check_freshness("tools/guard/x.py").decision == DECISION_ALLOW


def test_p2_engine_check_entrypoints():
    eng = ToolGateEngineP2()
    assert eng.check_purpose("OBSERVATION").decision == DECISION_ALLOW
    assert eng.check_pytest_slot({"options": ["-v"]}).decision == DECISION_ALLOW
    assert eng.check_l2gate("run_script", {"script_path": "a.py"}).decision == DECISION_WARN


def test_p2_check_all_includes_all_validators():
    eng = ToolGateEngineP2()
    params = {
        "path": "tools/guard/x.py",
        "pattern": "clean",
        "purpose": "OBSERVATION",
        "options": ["-v"],
        "script_path": "tools/sandbox/caddy/active/x.py",
    }
    results = eng.check_all("run_script", params)
    validators = {r.validator for r in results}
    assert validators == {"path", "freshness", "regex", "purpose", "pytest_slot", "l2gate"}
    assert len(results) == 6


def test_p2_check_all_partial_params():
    eng = ToolGateEngineP2()
    results = eng.check_all("pytest", {"options": ["-v"]})
    assert [r.validator for r in results] == ["pytest_slot"]


# ── drift 가드: 하드카피가 SSOT와 일치 ──
def test_p2_drift_purpose_allowed_matches_ssot():
    assert set(PURPOSE_ALLOWED) == set(SSOT_ALLOWED_PURPOSES)


def test_p2_drift_purpose_forbidden_matches_ssot():
    assert set(PURPOSE_FORBIDDEN) == set(SSOT_FORBIDDEN_PURPOSES)


def test_p2_drift_pytest_options_matches_ssot():
    assert set(PYTEST_OPTIONS) == set(SSOT_PYTEST_OPTIONS)

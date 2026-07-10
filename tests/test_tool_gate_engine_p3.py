#!/usr/bin/env python3
"""
test_tool_gate_engine_p3.py — PromiseGate(P3) 단위테스트 + drift 가드
- 판정기(PC-1/PC-3/PC-6/LESSON-002/LESSON-023) ALLOW/WARN/DENY
- 심각도 클램프(CLASS_B/C DENY 불가)
- check_all 하위호환(2인자) + super() 무변경 + P3 append
- drift 가드: id 존재 + 콘텐츠 해시(루트 env 유연, EXPECTED 미주입 시 skip)
"""
import os

import pytest

from tools.guard.tool_gate_engine import (
    ToolGateEngine, DECISION_ALLOW, DECISION_WARN, DECISION_DENY,
)
from tools.guard.tool_gate_engine_p2 import ToolGateEngineP2
from tools.guard.tool_gate_engine_p3 import PromiseGate
from tools.guard import promise_rules

# 드리프트 검증 루트: 로컬은 ARSS_ROOT, VPS는 REPO_ROOT 기본
ROOT = os.environ.get("ARSS_ROOT", promise_rules.REPO_ROOT)


def test_inheritance_chain():
    g = PromiseGate()
    assert isinstance(g, ToolGateEngineP2)
    assert isinstance(g, ToolGateEngine)


def test_rule_counts():
    assert len(promise_rules.CLASS_A) == 6
    assert len(promise_rules.CLASS_B) == 16
    assert len(promise_rules.CLASS_C) == 17
    assert len(promise_rules.all_rules()) == 39


def test_check_all_two_arg_backward_compat():
    g = PromiseGate()
    res = g.check_all("read_file", {"path": "context/lessons/lessons.json",
                                    "purpose": "OBSERVATION"})
    assert isinstance(res, list)
    validators = {r.validator for r in res}
    assert "purpose" in validators


def test_check_all_appends_promise_results():
    g = PromiseGate()
    res = g.check_all(
        "git_commit", {},
        session_trail=[{"tool": "git_commit"}],
        agent_output="",
        session_state={},
    )
    assert any(r.validator == "promise:PC-3" for r in res)


def test_check_all_clean_no_promise_violation():
    g = PromiseGate()
    res = g.check_all(
        "read_file", {"path": "context/x", "purpose": "OBSERVATION"},
        session_trail=[{"tool": "read_file"}],
        agent_output="정상 관측 보고",
        session_state={"eag_present": True, "next_steps_checked": True},
    )
    assert not any(r.validator.startswith("promise:") for r in res)


def test_pc1_deny_inline_exec_in_output():
    g = PromiseGate()
    res = g.promise_check(agent_output="ssh root@x 'python -c \"import os\"'")
    pc1 = [r for r in res if r.validator == "promise:PC-1"]
    assert len(pc1) == 1
    assert pc1[0].decision == DECISION_DENY


def test_pc1_deny_inline_exec_in_trail():
    g = PromiseGate()
    res = g.promise_check(session_trail=[{"command": "python -c print(1)"}])
    assert any(r.validator == "promise:PC-1" and r.decision == DECISION_DENY
               for r in res)


def test_pc3_warn_commit_without_status():
    g = PromiseGate()
    res = g.promise_check(session_trail=[{"tool": "write_script"}, {"tool": "git_commit"}])
    pc3 = [r for r in res if r.validator == "promise:PC-3"]
    assert len(pc3) == 1
    assert pc3[0].decision == DECISION_WARN


def test_pc3_ok_when_status_precedes_commit():
    g = PromiseGate()
    res = g.promise_check(session_trail=[{"tool": "git_status"}, {"tool": "git_commit"}])
    assert not any(r.validator == "promise:PC-3" for r in res)


def test_pc6_warn_next_steps_unchecked():
    g = PromiseGate()
    res = g.promise_check(session_state={"next_steps_checked": False})
    pc6 = [r for r in res if r.validator == "promise:PC-6"]
    assert len(pc6) == 1
    assert pc6[0].decision == DECISION_WARN


def test_lesson002_warn_exec_without_eag():
    g = PromiseGate()
    res = g.promise_check(session_trail=[{"tool": "run_script"}], session_state={})
    l2 = [r for r in res if r.validator == "promise:LESSON-002"]
    assert len(l2) == 1
    assert l2[0].decision == DECISION_WARN


def test_lesson002_ok_when_eag_present():
    g = PromiseGate()
    res = g.promise_check(session_trail=[{"tool": "run_script"}],
                          session_state={"eag_present": True})
    assert not any(r.validator == "promise:LESSON-002" for r in res)


def test_lesson023_warn_claim_without_proof():
    g = PromiseGate()
    res = g.promise_check(agent_output="배포 완료했습니다. 성공.")
    l23 = [r for r in res if r.validator == "promise:LESSON-023"]
    assert len(l23) == 1
    assert l23[0].decision == DECISION_WARN


def test_lesson023_ok_with_proof():
    g = PromiseGate()
    res = g.promise_check(agent_output="배포 완료. read_file 해시 SHA256 일치 확인.")
    assert not any(r.validator == "promise:LESSON-023" for r in res)


def test_class_c_never_deny():
    g = PromiseGate()
    res = g.promise_check(
        session_trail=[{"tool": "run_script"}],
        agent_output="완료 성공",
        session_state={},
    )
    for r in res:
        if r.validator.startswith("promise:LESSON-"):
            assert r.decision != DECISION_DENY


def test_clamp_helper_blocks_class_bc_deny():
    g = PromiseGate()
    g._severity["LESSON-002"] = DECISION_DENY
    g._cls["LESSON-002"] = "C"
    assert g._clamp("LESSON-002") == DECISION_WARN
    assert g._clamp("PC-1") == DECISION_DENY


def test_clean_promise_check_empty():
    g = PromiseGate()
    assert g.promise_check() == []


def test_no_missing_ids():
    assert promise_rules.missing_ids(ROOT) == []


def test_hash_deterministic():
    h1 = promise_rules.compute_ssot_hash(ROOT)
    h2 = promise_rules.compute_ssot_hash(ROOT)
    assert h1 == h2 and len(h1) == 64


def test_missing_id_detected():
    promise_rules.CLASS_C.append({"rule_id": "LESSON-DOES-NOT-EXIST", "severity": DECISION_WARN})
    try:
        assert "LESSON-DOES-NOT-EXIST" in promise_rules.missing_ids(ROOT)
    finally:
        promise_rules.CLASS_C.pop()


def test_hash_matches_expected():
    if promise_rules.EXPECTED_SSOT_HASH == "__FILL_ON_DEPLOY__":
        pytest.skip("EXPECTED_SSOT_HASH not yet injected (pre-deploy)")
    assert promise_rules.compute_ssot_hash(ROOT) == promise_rules.EXPECTED_SSOT_HASH


def test_gateresult_contract_reused():
    from tools.guard.tool_gate_engine import GateResult as G1
    from tools.guard.tool_gate_engine_p3 import GateResult as G3
    assert G1 is G3

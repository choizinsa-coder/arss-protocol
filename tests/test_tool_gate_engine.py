"""test_tool_gate_engine.py — 도구 마찰 사전검사기 P1 테스트.
EAG-S365-CARRYOVER-ELIM-P1-IMPL-001
대상: tools/guard/tool_gate_engine.py (validate_path / validate_regex / ToolGateEngine).
"""
from tools.guard.tool_gate_engine import (
    validate_path, validate_regex, ToolGateEngine, GateResult,
    DECISION_ALLOW, DECISION_WARN, DECISION_DENY, DECISION_HARD_STOP,
    BLOCKING_DECISIONS, _repo_relative, REPO_ROOT,
)

# ── _repo_relative: 절대/상대 등가 정규화 ──────────────────────────────────

def test_repo_relative_absolute_to_relative():
    assert _repo_relative(REPO_ROOT + "/tools/guard/x.py") == "tools/guard/x.py"


def test_repo_relative_already_relative():
    assert _repo_relative("tools/guard/x.py") == "tools/guard/x.py"


def test_repo_relative_normalizes_dot_slash():
    assert _repo_relative("./tools/./guard/x.py") == "tools/guard/x.py"


def test_repo_relative_empty():
    assert _repo_relative("") == ""
    assert _repo_relative("   ") == ""


# ── validate_regex: 미이스케이프 hazard 확정 DENY ──────────────────────────

def test_regex_unescaped_paren_deny():
    r = validate_regex("foo(bar")
    assert r.decision == DECISION_DENY
    assert "unescaped" in r.reason
    assert r.hint  # 교정 힌트 존재


def test_regex_unescaped_close_paren_deny():
    assert validate_regex("bar)baz").decision == DECISION_DENY


def test_regex_escaped_paren_allow():
    r = validate_regex(r"foo\(bar\)")
    assert r.decision == DECISION_ALLOW


def test_regex_plain_literal_allow():
    assert validate_regex("simple_pattern").decision == DECISION_ALLOW
    assert validate_regex("session_count").decision == DECISION_ALLOW


def test_regex_mixed_quotes_deny():
    r = validate_regex("it's a \"test\"")
    assert r.decision == DECISION_DENY
    assert "quote" in r.reason.lower()


def test_regex_none_deny():
    assert validate_regex(None).decision == DECISION_DENY


def test_regex_dedup_multiple_parens():
    # 괄호가 여러 개여도 안내는 한 번만 (중복 정리 확인)
    r = validate_regex("a(b(c(d")
    assert r.decision == DECISION_DENY
    assert r.reason.count("unescaped '('") == 1


# ── validate_path: 측정 경로 대조, 미측정은 WARN(fail-safe) ────────────────

def test_path_measured_allow():
    measured = {"tools/guard/x.py"}
    assert validate_path("tools/guard/x.py", measured).decision == DECISION_ALLOW


def test_path_absolute_matches_measured_relative():
    # INC-S364-003 계열: 절대경로가 측정된 상대경로와 등가 → ALLOW
    measured = {"tools/guard/x.py"}
    abs_path = REPO_ROOT + "/tools/guard/x.py"
    assert validate_path(abs_path, measured).decision == DECISION_ALLOW


def test_path_relative_matches_measured_absolute():
    measured = {REPO_ROOT + "/tools/guard/x.py"}
    assert validate_path("tools/guard/x.py", measured).decision == DECISION_ALLOW


def test_path_unmeasured_warns_not_deny():
    # 측정 안 된 경로 = 기억 재구성 의심 = WARN (DENY 아님, fail-safe)
    r = validate_path("tools/guard/never_measured.py", set())
    assert r.decision == DECISION_WARN
    assert r.decision != DECISION_DENY
    assert r.hint


def test_path_empty_warns():
    assert validate_path("", set()).decision == DECISION_WARN


# ── ToolGateEngine: measured_paths 단일 진입점, 추론 갱신 불가 ──────────────

def test_engine_record_measurement_is_only_mutation_entry():
    eng = ToolGateEngine()
    assert eng.measured_paths == set()
    eng.record_measurement(REPO_ROOT + "/tools/guard/x.py")
    assert "tools/guard/x.py" in eng.measured_paths
    # 등록 후 check_path ALLOW
    assert eng.check_path("tools/guard/x.py").decision == DECISION_ALLOW


def test_engine_unrecorded_path_warns():
    eng = ToolGateEngine()
    assert eng.check_path("tools/guard/x.py").decision == DECISION_WARN


def test_engine_check_regex_delegates():
    eng = ToolGateEngine()
    assert eng.check_regex("foo(bar").decision == DECISION_DENY
    assert eng.check_regex("clean").decision == DECISION_ALLOW


def test_engine_measured_paths_returns_copy():
    # 외부에서 반환 집합을 변조해도 내부 상태 불변 (캡슐화)
    eng = ToolGateEngine()
    eng.record_measurement("tools/guard/x.py")
    snap = eng.measured_paths
    snap.add("tools/guard/injected.py")
    assert "tools/guard/injected.py" not in eng.measured_paths


# ── violations/warnings 필터: 차단 대상만 격리 ─────────────────────────────

def test_violations_filters_blocking_only():
    results = [
        GateResult(DECISION_ALLOW, "path", "", ""),
        GateResult(DECISION_WARN, "path", "w", "h"),
        GateResult(DECISION_DENY, "regex", "bad", "fix"),
        GateResult(DECISION_HARD_STOP, "path", "c2", ""),
    ]
    v = ToolGateEngine.violations(results)
    assert len(v) == 2
    assert {r.decision for r in v} == set(BLOCKING_DECISIONS)


def test_warnings_filters_warn_only():
    results = [
        GateResult(DECISION_ALLOW, "path", "", ""),
        GateResult(DECISION_WARN, "path", "w", "h"),
        GateResult(DECISION_DENY, "regex", "bad", "fix"),
    ]
    w = ToolGateEngine.warnings(results)
    assert len(w) == 1
    assert w[0].decision == DECISION_WARN


# ── GateResult 편의 속성 ───────────────────────────────────────────────────

def test_gateresult_properties():
    assert GateResult(DECISION_ALLOW, "path", "", "").allowed is True
    assert GateResult(DECISION_DENY, "regex", "x", "y").blocking is True
    assert GateResult(DECISION_WARN, "path", "x", "y").blocking is False


def test_gateresult_to_dict():
    d = GateResult(DECISION_DENY, "regex", "bad", "fix").to_dict()
    assert d == {"decision": "DENY", "validator": "regex",
                 "reason": "bad", "hint": "fix"}

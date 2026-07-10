#!/usr/bin/env python3
"""
tool_gate_engine_p2.py v1.0.0 (P2)
AIBA Tool-Friction Pre-Execution Gate — Phase 2
(purpose / l2gate / pytest_slot / freshness)
EAG-S366-CARRYOVER-ELIM-P2-IMPL-001

설계: Domi DESIGN (S366, 이월제거시스템 축1 P2) + Caddy IMPLEMENTABLE 보정 6건
      + Jeni TRUST_READY (S366, BLOCKING_ISSUES: NONE).

목적: P1(경로·정규식) 위에 4계열 도구 마찰을 사전 판정한다:
      purpose 서술형(5회+ 반복), L2게이트 경로 불일치(OI-S353-001),
      pytest 슬롯 오사용(OI-S365-001), 낡은 스냅샷(freshness).

무결성 선(C2) 비침범: 순수 판정 함수만. 파일 쓰기·상태 변경·chain/hash/SSOT/freeze
      접근 전무. stdlib(time)만 + P1(순수) import.
      화이트리스트 상수는 SSOT 하드카피(drift 가드 테스트가 대조) — server 모듈 직접
      import 기각(aiba_exec_runtime 모듈레벨 logging.basicConfig 부작용 회피, C1 유지).

record_measurement 단일 진입점 유지(자체 추론·측정 금지, P1 SELF-CRITIQUE (c) 계승).
"""
from __future__ import annotations

import time

from tools.guard.tool_gate_engine import (
    GateResult,
    ToolGateEngine,
    DECISION_ALLOW,
    DECISION_WARN,
    DECISION_DENY,
    _repo_relative,
)

# ── SSOT 하드카피 (drift 가드 테스트가 SSOT와 문자열 대조) ──────────────
# SSOT: tools/mcp/mcp_read_server.py (ALLOWED_PURPOSES / FORBIDDEN_PURPOSES)
PURPOSE_ALLOWED = frozenset({
    "OBSERVATION",
    "EVIDENCE_INSPECTION",
    "AUDIT_INSPECTION",
    "CONSISTENCY_CHECK",
    "STALE_DETECTION",
})
PURPOSE_FORBIDDEN = frozenset({
    "EXECUTION_COORDINATION",
    "DEPLOYMENT_STEERING",
    "RUNTIME_CONTROL",
    "MUTATION_PREPARATION",
    "APPROVAL_SUBSTITUTION",
})
# SSOT: tools/exec_runtime/aiba_exec_runtime.py (ALLOWED_PYTEST_OPTIONS)
PYTEST_OPTIONS = frozenset({
    "-v", "--verbose",
    "-s", "--capture=no",
    "-x", "--exitfirst",
    "--tb=short", "--tb=long", "--tb=no",
    "-q", "--quiet",
    "--no-header",
    "-p", "no:warnings",
})

# freshness TTL (초). 측정 후 이 시간 경과 시 WARN.
FRESHNESS_TTL_SECONDS = 3600


def validate_purpose(purpose: str) -> GateResult:
    """read 도구 purpose 파라미터 유효성. mcp_read_server._validate_purpose
    2분기(FORBIDDEN 우선, 그다음 ALLOWED 밖) 미러링. 서술형·임의값은 DENY."""
    if purpose in PURPOSE_FORBIDDEN:
        return GateResult(
            DECISION_DENY, "purpose",
            "Forbidden purpose '" + str(purpose) + "'.",
            "Read purposes must be observational. Use one of: "
            "OBSERVATION / EVIDENCE_INSPECTION / AUDIT_INSPECTION / "
            "CONSISTENCY_CHECK / STALE_DETECTION")
    if purpose not in PURPOSE_ALLOWED:
        return GateResult(
            DECISION_DENY, "purpose",
            "Unknown purpose '" + str(purpose) + "'. Only 5 constants allowed.",
            "Use exactly one of: OBSERVATION / EVIDENCE_INSPECTION / "
            "AUDIT_INSPECTION / CONSISTENCY_CHECK / STALE_DETECTION "
            "(descriptive strings are denied).")
    return GateResult(DECISION_ALLOW, "purpose", "", "")


def validate_l2gate(command: str, params: dict, measured_paths) -> GateResult:
    """run_script script_path가 사전 read_file로 측정됐는가(OI-S353-001 L2 게이트).
    비대상 명령은 ALLOW. fail-safe: 미측정은 WARN(실제 bridge L2가 DENY), DENY 미발행."""
    if command != "run_script":
        return GateResult(DECISION_ALLOW, "l2gate", "", "")
    script_path = (params or {}).get("script_path", "")
    if not script_path:
        return GateResult(
            DECISION_WARN, "l2gate",
            "No script_path in params for run_script.",
            "Provide script_path measured via read_file(OBSERVATION).")
    cand = _repo_relative(script_path)
    measured_rel = {_repo_relative(m) for m in (measured_paths or [])}
    if cand in measured_rel:
        return GateResult(DECISION_ALLOW, "l2gate", "", "")
    return GateResult(
        DECISION_WARN, "l2gate",
        "script_path '" + str(script_path) + "' not previously read (norm '" + cand + "').",
        "Run read_file(OBSERVATION) on the SAME relative path string you will "
        "pass as run_script.script_path, then retry.")


def validate_pytest_slot(params: dict) -> GateResult:
    """pytest 파라미터 슬롯 적합성(OI-S365-001). options는 list이고 원소가
    화이트리스트 이내여야 함. 경로를 options에 넣으면 DENY. 형식 위반 확정 → DENY."""
    options = (params or {}).get("options", [])
    if not isinstance(options, list):
        return GateResult(
            DECISION_DENY, "pytest_slot",
            "params.options must be a list.",
            "Set options to a list of flags, e.g. ['-v', '--tb=short']. "
            "Put the test path in params.path, not params.options.")
    for opt in options:
        if opt not in PYTEST_OPTIONS:
            return GateResult(
                DECISION_DENY, "pytest_slot",
                "Option '" + str(opt) + "' not in ALLOWED_PYTEST_OPTIONS.",
                "Only whitelisted pytest flags are allowed; a test path in "
                "options is the common mistake — move it to params.path.")
    return GateResult(DECISION_ALLOW, "pytest_slot", "", "")


def validate_freshness(path: str, measured_freshness: dict) -> GateResult:
    """경로가 최근 측정(TTL 이내)되었는가. fail-safe: 미측정·TTL초과는 WARN, DENY 미발행.
    measured_freshness: {정규화경로: 측정 timestamp(float)}."""
    cand = _repo_relative(path)
    ts = (measured_freshness or {}).get(cand)
    if ts is not None:
        age = time.time() - ts
        if age <= FRESHNESS_TTL_SECONDS:
            return GateResult(DECISION_ALLOW, "freshness", "", "")
        return GateResult(
            DECISION_WARN, "freshness",
            "Path '" + str(path) + "' last measured " + str(int(age)) + "s ago (> TTL).",
            "Re-measure with read_file/list_dir before use.")
    return GateResult(
        DECISION_WARN, "freshness",
        "Path '" + str(path) + "' not measured this session.",
        "Measure with read_file/list_dir first.")


class ToolGateEngineP2(ToolGateEngine):
    """P1 엔진 확장. P2 검사기 4종 + 측정 타임스탬프 추적. 순수 판정만."""

    def __init__(self):
        super().__init__()
        self._measured_freshness: dict = {}

    def record_measurement(self, path: str) -> None:
        """P1 단일 진입점 확장: 경로 등록 + 측정 시각 기록."""
        super().record_measurement(path)
        rel = _repo_relative(path)
        if rel:
            self._measured_freshness[rel] = time.time()

    @property
    def measured_freshness(self) -> dict:
        return dict(self._measured_freshness)

    def check_purpose(self, purpose: str) -> GateResult:
        return validate_purpose(purpose)

    def check_l2gate(self, command: str, params: dict) -> GateResult:
        return validate_l2gate(command, params, self.measured_paths)

    def check_pytest_slot(self, params: dict) -> GateResult:
        return validate_pytest_slot(params)

    def check_freshness(self, path: str) -> GateResult:
        return validate_freshness(path, self._measured_freshness)

    def check_all(self, tool_name: str, params: dict) -> list:
        """존재하는 파라미터 키에 따라 해당 검사기 실행. P1 실제 시그니처
        (check_path(path)/check_regex(pattern)) 정확 호출."""
        params = params or {}
        results = []
        if "path" in params:
            results.append(self.check_path(params["path"]))
            results.append(self.check_freshness(params["path"]))
        if "pattern" in params:
            results.append(self.check_regex(params["pattern"]))
        if "purpose" in params:
            results.append(self.check_purpose(params["purpose"]))
        if "options" in params:
            results.append(self.check_pytest_slot(params))
        if tool_name == "run_script" and "script_path" in params:
            results.append(self.check_l2gate(tool_name, params))
        return results

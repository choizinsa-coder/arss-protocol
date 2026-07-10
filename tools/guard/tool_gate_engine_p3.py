#!/usr/bin/env python3
"""
tool_gate_engine_p3.py v1.0.0 (P3)
AIBA Tool-Friction Pre-Execution Gate — Phase 3 (PromiseGate: lessons/rules 약속 이행 검증)
이월제거시스템 축2.

설계: Domi DESIGN (S367) + Caddy IMPLEMENTABLE 정합 + Jeni TRUST_READY(S367, BLOCKING: NONE).

목적: 세션 행위(session_trail / agent_output / session_state)가 기록된 약속
      (rules.json PC·simple_change / lessons.json prevention_rule)을 위반했는지
      기계 대조하여 판정만 반환한다. 실제 차단·강제는 P4(aiba_monitor 결선) 이월.

심각도 정책(S367 확정): DENY는 rules HARD_GATE(PC-1/PC-4)에서만. simple_change(CLASS_B)와
      lessons(CLASS_C)는 자연어/부분정합이라 WARN 상한(오탐 방지).

무결성 선(C2) 비침범: 순수 판정 함수만. 파일 쓰기·상태 변경·chain/hash/SSOT/freeze
      접근 전무. stdlib(json/hashlib via promise_rules) + P1/P2(순수) import.

P3 범위: '위반했는가?'만 답한다. 답을 받아 '행동'하는 것은 P4.
"""
from __future__ import annotations

from tools.guard.tool_gate_engine import (
    GateResult,
    DECISION_ALLOW,
    DECISION_WARN,
    DECISION_DENY,
)
from tools.guard.tool_gate_engine_p2 import ToolGateEngineP2
from tools.guard import promise_rules

# 상태 변경(실행) 계열 도구 — LESSON-002/019(EAG 없는 실행) 판정용
_EXECUTION_TOOLS = frozenset({
    "write_script", "run_script", "git_commit", "git_push", "systemctl_restart",
})

# 완료·역량 주장 키워드(LESSON-023 판정용) / 증거 마커
_CLAIM_MARKERS = ("완료", "성공", "배포됨", "deployed", "완성")
_PROOF_MARKERS = ("present_files", "read_file", "실측", "해시", "hash", "sha256", "SHA256")


def _entry_name(entry) -> str:
    """session_trail 항목에서 도구/명령 이름을 안전하게 추출."""
    if isinstance(entry, dict):
        return str(entry.get("tool") or entry.get("tool_name") or entry.get("command") or "")
    return str(entry)


def _trail_text(session_trail) -> str:
    """session_trail 전체를 텍스트로 평탄화(패턴 스캔용)."""
    parts = []
    for e in (session_trail or []):
        if isinstance(e, dict):
            parts.append(" ".join(str(v) for v in e.values()))
        else:
            parts.append(str(e))
    return "\n".join(parts)


class PromiseGate(ToolGateEngineP2):
    """P2 확장(P2→P1 연쇄 상속). 약속 이행 검증 판정기. 순수 판정만."""

    def __init__(self):
        super().__init__()
        self._severity = {}
        self._cls = {}
        for r in promise_rules.all_rules():
            self._severity[r["rule_id"]] = r["severity"]
            self._cls[r["rule_id"]] = r["cls"]

    def _eval_pc1(self, trail_text, agent_output, state):
        if "python -c" in agent_output or "python -c" in trail_text:
            return ("Inline execution 'python -c' detected.",
                    "Deploy a .py file (write_script) then run_script; no inline python -c.")
        return None

    def _eval_pc3(self, session_trail, agent_output, state):
        names = [_entry_name(e) for e in (session_trail or [])]
        for i, n in enumerate(names):
            if n == "git_commit":
                prev = names[i - 1] if i > 0 else ""
                if prev != "git_status":
                    return ("git_commit without an immediately preceding git_status.",
                            "Run git_status right before git_commit.")
        return None

    def _eval_pc6(self, session_trail, agent_output, state):
        if state.get("next_steps_checked") is False:
            return ("SESSION_CONTEXT next_steps not verified before work.",
                    "Check next_steps at session start to avoid carry-forward conflicts.")
        return None

    def _eval_lesson_002(self, session_trail, agent_output, state):
        names = {_entry_name(e) for e in (session_trail or [])}
        if names & _EXECUTION_TOOLS and not state.get("eag_present"):
            return ("Execution tool used without an EAG marker in session_state.",
                    "Confirm EAG approval before state-changing execution.")
        return None

    def _eval_lesson_023(self, session_trail, agent_output, state):
        has_claim = any(m in agent_output for m in _CLAIM_MARKERS)
        has_proof = any(m in agent_output for m in _PROOF_MARKERS)
        if has_claim and not has_proof:
            return ("Completion/capability claim without a proof marker.",
                    "Back claims with measured evidence (read_file/present_files/hash).")
        return None

    def _run_evaluator(self, rule_id, session_trail, trail_text, agent_output, state):
        if rule_id == "PC-1":
            return self._eval_pc1(trail_text, agent_output, state)
        if rule_id == "PC-3":
            return self._eval_pc3(session_trail, agent_output, state)
        if rule_id == "PC-6":
            return self._eval_pc6(session_trail, agent_output, state)
        if rule_id == "LESSON-002":
            return self._eval_lesson_002(session_trail, agent_output, state)
        if rule_id == "LESSON-023":
            return self._eval_lesson_023(session_trail, agent_output, state)
        return None

    def _clamp(self, rule_id: str) -> str:
        sev = self._severity.get(rule_id, DECISION_WARN)
        cls = self._cls.get(rule_id, "C")
        if cls in ("B", "C") and sev == DECISION_DENY:
            return DECISION_WARN
        return sev

    def promise_check(self, session_trail=None, agent_output="", session_state=None) -> list:
        agent_output = agent_output or ""
        session_state = session_state or {}
        trail_text = _trail_text(session_trail)
        results = []
        for r in promise_rules.all_rules():
            rule_id = r["rule_id"]
            verdict = self._run_evaluator(rule_id, session_trail, trail_text, agent_output, session_state)
            if verdict is not None:
                reason, hint = verdict
                results.append(GateResult(
                    self._clamp(rule_id),
                    "promise:" + rule_id,
                    reason,
                    hint,
                ))
        return results

    def check_all(self, tool_name, params, session_trail=None, agent_output="", session_state=None) -> list:
        results = super().check_all(tool_name, params)
        results.extend(self.promise_check(session_trail, agent_output, session_state))
        return results

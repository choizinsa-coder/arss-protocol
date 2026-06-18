"""
test_briefing_gate.py
AIBA Governance 3-6: Briefing Quality Gate 테스트
EAG: EAG-S264-GOV-3-6-001

TC-01: 5항목 모두 존재 → PASS
TC-02: [CONTEXT] 누락 → BLOCK
TC-03: [HISTORY] 누락 → BLOCK
TC-04: [GOAL] 누락 → BLOCK
TC-05: [CONSTRAINT] 누락 → BLOCK
TC-06: [REQUEST] 누락 → BLOCK
TC-07: 전체 누락 → BLOCK
TC-08: call_type='query' + 누락 → WARN
TC-09: call_type='query' + 5항목 완비 → PASS
TC-10: missing_sections 정확성 검증
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "governance"))
from briefing_gate import validate_briefing_structure, BriefingCheckResult


FULL_BRIEFING = """
[CONTEXT] 배경 설명
[HISTORY] 실패 사례
[GOAL] 목표 정의
[CONSTRAINT] 제약 조건
[REQUEST] 구체적 요청
"""


class TestBriefingGatePass:
    """TC-01, TC-09: 5항목 완비 시 PASS"""

    def test_tc01_all_sections_present_design(self):
        result = validate_briefing_structure(FULL_BRIEFING, call_type="design")
        assert result.passed is True
        assert result.policy == "PASS"
        assert result.missing_sections == []

    def test_tc09_all_sections_present_query(self):
        result = validate_briefing_structure(FULL_BRIEFING, call_type="query")
        assert result.passed is True
        assert result.policy == "PASS"
        assert result.missing_sections == []


class TestBriefingGateBlock:
    """TC-02~07: 누락 시 BLOCK (call_type='design')"""

    def test_tc02_missing_context(self):
        prompt = "[HISTORY] x\n[GOAL] x\n[CONSTRAINT] x\n[REQUEST] x"
        result = validate_briefing_structure(prompt)
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert "[CONTEXT]" in result.missing_sections

    def test_tc03_missing_history(self):
        prompt = "[CONTEXT] x\n[GOAL] x\n[CONSTRAINT] x\n[REQUEST] x"
        result = validate_briefing_structure(prompt)
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert "[HISTORY]" in result.missing_sections

    def test_tc04_missing_goal(self):
        prompt = "[CONTEXT] x\n[HISTORY] x\n[CONSTRAINT] x\n[REQUEST] x"
        result = validate_briefing_structure(prompt)
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert "[GOAL]" in result.missing_sections

    def test_tc05_missing_constraint(self):
        prompt = "[CONTEXT] x\n[HISTORY] x\n[GOAL] x\n[REQUEST] x"
        result = validate_briefing_structure(prompt)
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert "[CONSTRAINT]" in result.missing_sections

    def test_tc06_missing_request(self):
        prompt = "[CONTEXT] x\n[HISTORY] x\n[GOAL] x\n[CONSTRAINT] x"
        result = validate_briefing_structure(prompt)
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert "[REQUEST]" in result.missing_sections

    def test_tc07_all_missing(self):
        result = validate_briefing_structure("no sections here")
        assert result.passed is False
        assert result.policy == "BLOCK"
        assert len(result.missing_sections) == 5


class TestBriefingGateWarn:
    """TC-08: call_type='query' + 누락 → WARN"""

    def test_tc08_query_type_missing_sections(self):
        prompt = "[CONTEXT] x\n[GOAL] x"  # HISTORY, CONSTRAINT, REQUEST 누락
        result = validate_briefing_structure(prompt, call_type="query")
        assert result.passed is False
        assert result.policy == "WARN"
        assert "[HISTORY]" in result.missing_sections
        assert "[CONSTRAINT]" in result.missing_sections
        assert "[REQUEST]" in result.missing_sections


class TestBriefingGateMissingSections:
    """TC-10: missing_sections 정확성"""

    def test_tc10_missing_sections_accuracy(self):
        prompt = "[CONTEXT] x\n[REQUEST] x"  # HISTORY, GOAL, CONSTRAINT 누락
        result = validate_briefing_structure(prompt)
        assert set(result.missing_sections) == {"[HISTORY]", "[GOAL]", "[CONSTRAINT]"}

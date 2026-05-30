"""
test_rule_loader.py
P4-C4 Phase-beta Batch-1: RULE-8 placeholder → assertion 보강
source: tools/code_health/rule_loader.py
EAG-3 Approved (비오(Joshua), S175)

Layer A: RULE 상수 존재 및 타입 (4)
Layer B: RULE-6/RULE-8 fail-closed 계약 값 (4)
Layer C: Severity / Gate 상수 (3)
Total: 11
"""

import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import tools.code_health.rule_loader as rl


# ── Layer A: RULE 상수 존재 및 타입 ────────────────────────────────────────

class TestLayerA_RuleConstantsExist:

    def test_A1_rule1_forbidden_patterns_is_list(self):
        """RULE1_FORBIDDEN_PATTERNS 는 비어있지 않은 리스트"""
        assert isinstance(rl.RULE1_FORBIDDEN_PATTERNS, list)
        assert len(rl.RULE1_FORBIDDEN_PATTERNS) > 0

    def test_A2_rule4_active_version_markers_contains_active_version(self):
        """RULE4_ACTIVE_VERSION_MARKERS 에 'ACTIVE_VERSION' 포함"""
        assert "ACTIVE_VERSION" in rl.RULE4_ACTIVE_VERSION_MARKERS

    def test_A3_rule7_mutation_keywords_is_list(self):
        """RULE7_MUTATION_KEYWORDS 는 비어있지 않은 리스트"""
        assert isinstance(rl.RULE7_MUTATION_KEYWORDS, list)
        assert len(rl.RULE7_MUTATION_KEYWORDS) > 0

    def test_A4_rule9_domain_keywords_has_governance(self):
        """RULE9_DOMAIN_KEYWORDS 에 'governance' 도메인 존재"""
        assert "governance" in rl.RULE9_DOMAIN_KEYWORDS
        assert isinstance(rl.RULE9_DOMAIN_KEYWORDS["governance"], list)


# ── Layer B: RULE-6/RULE-8 fail-closed 계약 값 ────────────────────────────

class TestLayerB_FailClosedContract:

    def test_B1_rule6_forbidden_except_contains_pass(self):
        """RULE-6: except 블록 내 'pass' 사용 금지 목록에 포함"""
        assert "pass" in rl.RULE6_FORBIDDEN_EXCEPT_PATTERNS

    def test_B2_rule6_forbidden_return_contains_success_true(self):
        """RULE-6: except 후 'success=True' 반환 금지"""
        assert "success=True" in rl.RULE6_FORBIDDEN_RETURN_AFTER_EXCEPT

    def test_B3_rule8_test_file_prefix_is_test_(self):
        """RULE-8: 테스트 파일 prefix는 'test_' 고정"""
        assert rl.RULE8_TEST_FILE_PREFIX == "test_"

    def test_B4_rule5_line_fail_greater_than_review(self):
        """RULE-5: FAIL 임계값은 REVIEW 임계값보다 큼 (120 > 80)"""
        assert rl.RULE5_FUNCTION_LINE_FAIL > rl.RULE5_FUNCTION_LINE_REVIEW


# ── Layer C: Severity / Gate 상수 ──────────────────────────────────────────

class TestLayerC_SeverityGate:

    def test_C1_severity_fail_is_fail_string(self):
        """SEVERITY_FAIL = 'FAIL'"""
        assert rl.SEVERITY_FAIL == "FAIL"

    def test_C2_severity_pass_is_pass_string(self):
        """SEVERITY_PASS = 'PASS'"""
        assert rl.SEVERITY_PASS == "PASS"

    def test_C3_gate_id_is_code_health(self):
        """GATE_ID = 'CODE_HEALTH'"""
        assert rl.GATE_ID == "CODE_HEALTH"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

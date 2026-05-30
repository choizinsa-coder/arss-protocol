"""
test_patterns.py
P4-C4 Phase-beta Batch-1: RULE-8 placeholder → assertion 보강
source: tools/eps_v1_4/patterns.py
EAG-3 Approved (비오(Joshua), S175)

Layer A: has_uncertainty_marker (3)
Layer B: matches_exploration / matches_proposed_action (4)
Layer C: matches_assertion_state / matches_auto_assertion (4)
Layer D: has_next_action — failure path (4)
Total: 15
"""

import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_4.patterns import (
    has_uncertainty_marker,
    matches_exploration,
    matches_proposed_action,
    matches_assertion_state,
    matches_auto_assertion,
    has_next_action,
)


# ── Layer A: has_uncertainty_marker ────────────────────────────────────────

class TestLayerA_UncertaintyMarker:

    def test_A1_match_uncertainty(self):
        """불확실성 표현 포함 → True"""
        assert has_uncertainty_marker("이것은 추정됩니다.") is True

    def test_A2_match_possible(self):
        """'일 수 있' 표현 → True"""
        assert has_uncertainty_marker("오류일 수 있습니다.") is True

    def test_A3_no_match_empty(self):
        """빈 문자열 → False"""
        assert has_uncertainty_marker("") is False


# ── Layer B: matches_exploration / matches_proposed_action ─────────────────

class TestLayerB_ExplorationProposed:

    def test_B1_matches_exploration_true(self):
        """탐색 표현 패턴 매칭 → True"""
        assert matches_exploration("가능성이 있어 보입니다.") is True

    def test_B2_matches_exploration_false(self):
        """확정 표현 → False"""
        assert matches_exploration("완료되었습니다.") is False

    def test_B3_matches_proposed_action_true(self):
        """제안 표현 포함 → True"""
        assert matches_proposed_action("다음 단계를 진행하겠습니다.") is True

    def test_B4_matches_proposed_action_false(self):
        """제안 표현 없음 → False"""
        assert matches_proposed_action("오류가 발생했습니다.") is False


# ── Layer C: matches_assertion_state / matches_auto_assertion ──────────────

class TestLayerC_AssertionAutoAssertion:

    def test_C1_matches_assertion_state_true(self):
        """완료 확정 표현 → True"""
        assert matches_assertion_state("완료되었습니다.") is True

    def test_C2_matches_assertion_state_all_pass(self):
        """'ALL PASS' 표현 → True"""
        assert matches_assertion_state("pytest ALL PASS 확인.") is True

    def test_C3_matches_auto_assertion_true(self):
        """준 완료 표현 → True"""
        assert matches_auto_assertion("준 완료 상태입니다.") is True

    def test_C4_matches_auto_assertion_false(self):
        """일반 설명 문장 → False"""
        assert matches_auto_assertion("설정 중입니다.") is False


# ── Layer D: has_next_action — failure path ────────────────────────────────

class TestLayerD_HasNextAction_FailurePath:

    def test_D1_valid_next_action(self):
        """'Next Action: ...' 비어있지 않음 → True"""
        assert has_next_action("Next Action: VPS 배포 진행") is True

    def test_D2_placeholder_body_false(self):
        """'Next Action: TBD' → placeholder → False"""
        assert has_next_action("Next Action: TBD") is False

    def test_D3_missing_next_action(self):
        """'Next Action' 없음 → False"""
        assert has_next_action("아무 내용이나 작성합니다.") is False

    def test_D4_empty_body_false(self):
        """'Next Action:' 뒤가 비어있음 → False"""
        assert has_next_action("Next Action: ") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
test_load_result.py
P4-C4 Phase-beta Batch-1: RULE-8 placeholder → assertion 보강
source: tools/auto_loader/load_result.py
EAG-3 Approved (비오(Joshua), S175)

Layer A: make_load_result 정상 경로 (4)
Layer B: make_load_result failure path — failure_reason 존재 (4)
Layer C: LoadResult frozen dataclass 계약 (3)
Total: 11
"""

import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.auto_loader.load_result import LoadResult, make_load_result
from tools.auto_loader.field_contract import Verdict


# ── Layer A: make_load_result 정상 경로 ────────────────────────────────────

class TestLayerA_NormalPath:

    def test_A1_no_failure_reason_returns_pass_verdict(self):
        """failure_reason=None → verdict=PASS"""
        result = make_load_result("T-001", True, True, "abc123", None)
        assert result.verdict == Verdict.PASS

    def test_A2_no_failure_reason_apply_allowed_true(self):
        """failure_reason=None → apply_allowed=True"""
        result = make_load_result("T-001", True, True, "abc123", None)
        assert result.apply_allowed is True

    def test_A3_no_failure_reason_next_allowed_true(self):
        """failure_reason=None → next_allowed=True"""
        result = make_load_result("T-001", True, True, "abc123", None)
        assert result.next_allowed is True

    def test_A4_target_id_preserved(self):
        """target_id 필드 보존"""
        result = make_load_result("TARGET-XYZ", True, True, None, None)
        assert result.target_id == "TARGET-XYZ"


# ── Layer B: failure path — failure_reason 존재 ────────────────────────────

class TestLayerB_FailurePath:

    def test_B1_failure_reason_returns_fail_verdict(self):
        """failure_reason 존재 → verdict=FAIL"""
        result = make_load_result("T-002", False, False, None, "SOURCE_NOT_FOUND")
        assert result.verdict == Verdict.FAIL

    def test_B2_failure_reason_apply_allowed_false(self):
        """failure_reason 존재 → apply_allowed=False"""
        result = make_load_result("T-002", False, False, None, "SOURCE_NOT_FOUND")
        assert result.apply_allowed is False

    def test_B3_failure_reason_next_allowed_false(self):
        """failure_reason 존재 → next_allowed=False"""
        result = make_load_result("T-002", False, False, None, "HASH_MISMATCH")
        assert result.next_allowed is False

    def test_B4_failure_reason_preserved(self):
        """failure_reason 내용 그대로 보존"""
        result = make_load_result("T-003", True, False, None, "LOAD_TIMEOUT")
        assert result.failure_reason == "LOAD_TIMEOUT"


# ── Layer C: LoadResult frozen dataclass 계약 ──────────────────────────────

class TestLayerC_FrozenContract:

    def test_C1_load_result_is_frozen(self):
        """LoadResult는 frozen=True — 필드 수정 불가"""
        result = make_load_result("T-004", True, True, "hash_val", None)
        with pytest.raises((AttributeError, TypeError)):
            result.verdict = Verdict.FAIL  # type: ignore

    def test_C2_hash_field_preserved(self):
        """hash 필드 값 보존"""
        result = make_load_result("T-005", True, True, "sha256_deadbeef", None)
        assert result.hash == "sha256_deadbeef"

    def test_C3_hash_none_on_failure(self):
        """실패 시 hash=None 허용"""
        result = make_load_result("T-006", False, False, None, "FILE_MISSING")
        assert result.hash is None
        assert result.verdict == Verdict.FAIL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

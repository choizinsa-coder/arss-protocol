"""
test_context_schema.py
P4-C4 Phase-beta Batch-1: RULE-8 placeholder → assertion 보강
source: tools/eps_v1_4/context_schema.py
EAG-3 Approved (비오(Joshua), S175)

Layer A: validate_sep_context (3)
Layer B: has_valid_receipt (3)
Layer C: verifier_pass (3)
Layer D: verifier_is_fresh — failure path (4)
Total: 13
"""

import sys
import pytest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_4.context_schema import (
    validate_sep_context,
    has_valid_receipt,
    verifier_pass,
    verifier_is_fresh,
)
from tools.eps_v1_4.exceptions import ContextValidationError


# ── Layer A: validate_sep_context ──────────────────────────────────────────

class TestLayerA_ValidateSepContext:

    def test_A1_valid_dict_no_exception(self):
        """정상 dict 입력 → 예외 없음"""
        validate_sep_context({"key": "value"})  # 예외 없으면 통과

    def test_A2_non_dict_raises_context_validation_error(self):
        """비-dict 입력 → ContextValidationError 발생 (RULE-8 failure path)"""
        with pytest.raises(ContextValidationError):
            validate_sep_context("not a dict")

    def test_A3_none_raises_context_validation_error(self):
        """None 입력 → ContextValidationError 발생"""
        with pytest.raises(ContextValidationError):
            validate_sep_context(None)


# ── Layer B: has_valid_receipt ─────────────────────────────────────────────

class TestLayerB_HasValidReceipt:

    def test_B1_valid_receipt_with_id_returns_true(self):
        """receipt_id 있는 receipt → True"""
        ctx = {"receipt": {"receipt_id": "RCP-001"}}
        assert has_valid_receipt(ctx) is True

    def test_B2_receipt_missing_receipt_id_returns_false(self):
        """receipt_id 없는 receipt → False (failure path)"""
        ctx = {"receipt": {"other_field": "value"}}
        assert has_valid_receipt(ctx) is False

    def test_B3_no_receipt_key_returns_false(self):
        """receipt 키 없음 → False"""
        assert has_valid_receipt({}) is False


# ── Layer C: verifier_pass ─────────────────────────────────────────────────

class TestLayerC_VerifierPass:

    def test_C1_status_pass_returns_true(self):
        """verifier_result.status = 'PASS' → True"""
        ctx = {"verifier_result": {"status": "PASS"}}
        assert verifier_pass(ctx) is True

    def test_C2_status_fail_returns_false(self):
        """verifier_result.status = 'FAIL' → False (failure path)"""
        ctx = {"verifier_result": {"status": "FAIL"}}
        assert verifier_pass(ctx) is False

    def test_C3_missing_verifier_result_returns_false(self):
        """verifier_result 없음 → False"""
        assert verifier_pass({}) is False


# ── Layer D: verifier_is_fresh — failure path ──────────────────────────────

class TestLayerD_VerifierIsFresh_FailurePath:

    def test_D1_fresh_verifier_returns_true(self):
        """TTL 내 verifier_result → True"""
        checked_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        ctx = {"verifier_result": {"status": "PASS", "checked_at": checked_at, "ttl_sec": 3600}}
        assert verifier_is_fresh(ctx) is True

    def test_D2_expired_ttl_returns_false(self):
        """TTL 초과 → False (failure path)"""
        checked_at = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        ctx = {"verifier_result": {"status": "PASS", "checked_at": checked_at, "ttl_sec": 60}}
        assert verifier_is_fresh(ctx) is False

    def test_D3_missing_ttl_sec_returns_false(self):
        """ttl_sec 없음 → False (failure path)"""
        checked_at = datetime.now(timezone.utc).isoformat()
        ctx = {"verifier_result": {"status": "PASS", "checked_at": checked_at}}
        assert verifier_is_fresh(ctx) is False

    def test_D4_status_not_pass_returns_false(self):
        """status != PASS → False (failure path, TTL 무관)"""
        checked_at = datetime.now(timezone.utc).isoformat()
        ctx = {"verifier_result": {"status": "FAIL", "checked_at": checked_at, "ttl_sec": 3600}}
        assert verifier_is_fresh(ctx) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

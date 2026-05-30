"""
test_exceptions.py
P4-C4 Phase-beta Batch-1: RULE-8 placeholder → assertion 보강
source: tools/eps_v1_4/exceptions.py
EAG-3 Approved (비오(Joshua), S175)

Layer A: 예외 클래스 계층 구조 (3)
Layer B: EnforcementBlockedError 속성 (3)
Layer C: failure path — raise/catch (3)
Total: 9
"""

import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_4.exceptions import (
    SEPError,
    ContextValidationError,
    EnforcementBlockedError,
)


# ── Layer A: 예외 클래스 계층 구조 ─────────────────────────────────────────

class TestLayerA_Hierarchy:

    def test_A1_sep_error_is_exception(self):
        """SEPError는 Exception 의 서브클래스"""
        assert issubclass(SEPError, Exception)

    def test_A2_context_validation_error_is_sep_error(self):
        """ContextValidationError는 SEPError 의 서브클래스"""
        assert issubclass(ContextValidationError, SEPError)

    def test_A3_enforcement_blocked_error_is_sep_error(self):
        """EnforcementBlockedError는 SEPError 의 서브클래스"""
        assert issubclass(EnforcementBlockedError, SEPError)


# ── Layer B: EnforcementBlockedError 속성 ──────────────────────────────────

class TestLayerB_EnforcementBlockedError:

    def test_B1_default_reason_code(self):
        """reason_code 기본값은 'BLOCKED'"""
        err = EnforcementBlockedError("차단됨")
        assert err.reason_code == "BLOCKED"

    def test_B2_custom_reason_code(self):
        """reason_code 커스텀 값 저장"""
        err = EnforcementBlockedError("정책 위반", reason_code="POLICY_VIOLATION")
        assert err.reason_code == "POLICY_VIOLATION"

    def test_B3_message_preserved(self):
        """에러 메시지가 args 에 보존됨"""
        err = EnforcementBlockedError("차단 메시지")
        assert "차단 메시지" in str(err)


# ── Layer C: failure path — raise/catch ────────────────────────────────────

class TestLayerC_FailurePath:

    def test_C1_sep_error_raise_catch(self):
        """SEPError raise → except SEPError 로 포착"""
        with pytest.raises(SEPError):
            raise SEPError("기본 에러")

    def test_C2_context_validation_error_caught_as_sep(self):
        """ContextValidationError는 SEPError 로도 포착 가능"""
        with pytest.raises(SEPError):
            raise ContextValidationError("컨텍스트 오류")

    def test_C3_enforcement_blocked_error_caught_as_sep(self):
        """EnforcementBlockedError는 SEPError 로도 포착 가능,
        reason_code는 except 블록 내에서도 접근 가능"""
        try:
            raise EnforcementBlockedError("EAG 미승인", reason_code="EAG_MISSING")
        except SEPError as e:
            assert hasattr(e, "reason_code")
            assert e.reason_code == "EAG_MISSING"
        else:
            pytest.fail("예외가 발생하지 않음")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

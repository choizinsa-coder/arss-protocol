"""
test_mcp_filter_policy.py
READ_ONLY_COGNITION_MODE Filter Policy 테스트
EAG-2 승인: 비오(Joshua) S129
제니 권고: C-2(HARD_CONTAINMENT) 테스트 케이스 우선 작성

변경 이력:
- S133: TC-1/TC-2 테스트 격리 결함 수정
         _trigger_hct04 mock 추가 — state 파일 오염 방지
         (이전: mock 없이 실제 enter_containment 호출 → mcp_containment_state.json 오염)
"""
import sys
import os
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'mcp'))

import pytest
from mcp_filter_policy import (
    CognitionMode,
    DegradationDetector,
    FilterPolicy,
    FilterResult,
    FilterVerdict,
    LoadState,
    MetadataCategory,
    MetadataRequest,
    _WHITELIST_INTEGRITY_HASH,
    _ALLOWED_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _req(
    category: MetadataCategory,
    namespace: str = "test.ns",
    requester_id: str = "test-agent",
) -> MetadataRequest:
    return MetadataRequest(
        namespace=namespace,
        category=category,
        requester_id=requester_id,
        request_id="req-001",
    )


@pytest.fixture
def policy() -> FilterPolicy:
    return FilterPolicy()


# ---------------------------------------------------------------------------
# TC-1~TC-4: C-2 HARD_CONTAINMENT (제니 우선 권고)
# ---------------------------------------------------------------------------

class TestHardContainment:
    """C-2: 반복 경계 위반 시 HARD_CONTAINMENT 전환"""

    def test_tc1_containment_triggered_after_threshold(self, policy):
        """TC-1: 동일 namespace 3회 위반 시 HARD_CONTAINMENT 전환
        격리: _trigger_hct04 mock — policy 내부 상태(HARD_CONTAINMENT) 검증만.
              state 파일 write 차단으로 운영 환경 오염 방지.
        """
        ns = "attack.ns"
        with patch("mcp_filter_policy._trigger_hct04"):
            for _ in range(FilterPolicy.CONTAINMENT_THRESHOLD):
                policy.evaluate(_req(MetadataCategory.AUTHORITY_METADATA, namespace=ns))
        assert policy.get_mode() == CognitionMode.HARD_CONTAINMENT

    def test_tc2_containment_blocks_all_after_trigger(self, policy):
        """TC-2: HARD_CONTAINMENT 이후 허용 범주 요청도 전면 차단
        격리: _trigger_hct04 mock — state 파일 write 차단.
        """
        ns = "attack.ns"
        with patch("mcp_filter_policy._trigger_hct04"):
            for _ in range(FilterPolicy.CONTAINMENT_THRESHOLD):
                policy.evaluate(_req(MetadataCategory.AUTHORITY_METADATA, namespace=ns))

            result = policy.evaluate(_req(MetadataCategory.LOAD_STATE))
        assert result.verdict == FilterVerdict.DENY
        assert result.containment_triggered is True

    def test_tc3_containment_not_triggered_below_threshold(self, policy):
        """TC-3: 임계값 미만 위반은 HARD_CONTAINMENT 미전환"""
        ns = "test.ns"
        for _ in range(FilterPolicy.CONTAINMENT_THRESHOLD - 1):
            policy.evaluate(_req(MetadataCategory.AUTHORITY_METADATA, namespace=ns))
        assert policy.get_mode() == CognitionMode.READ_ONLY_COGNITION_MODE

    def test_tc4_containment_namespace_isolated(self, policy):
        """TC-4: 다른 namespace 위반은 HARD_CONTAINMENT 카운트 분리"""
        for i in range(FilterPolicy.CONTAINMENT_THRESHOLD):
            policy.evaluate(_req(
                MetadataCategory.AUTHORITY_METADATA,
                namespace=f"ns-{i}"  # 각각 다른 namespace
            ))
        # 각 namespace별 1회씩 — HARD_CONTAINMENT 미전환
        assert policy.get_mode() == CognitionMode.READ_ONLY_COGNITION_MODE


# ---------------------------------------------------------------------------
# TC-5~TC-9: 허용 범주 A-1~A-5
# ---------------------------------------------------------------------------

class TestAllowedCategories:
    """A-1~A-5: 허용 범주 ALLOW 판정"""

    @pytest.mark.parametrize("category", [
        MetadataCategory.LOAD_STATE,
        MetadataCategory.STATIC_OPERATIONAL_FLAGS,
        MetadataCategory.NON_SENSITIVE_ROUTING,
        MetadataCategory.AUDIT_REFERENCE,
        MetadataCategory.STATIC_WHITELIST,
    ])
    def test_tc5_allowed_categories_pass(self, policy, category):
        """TC-5: 허용 범주 전항목 ALLOW"""
        result = policy.evaluate(_req(category))
        assert result.verdict == FilterVerdict.ALLOW

    def test_tc6_allowed_does_not_increment_violation(self, policy):
        """TC-6: 허용 범주 요청은 위반 카운트 미증가"""
        policy.evaluate(_req(MetadataCategory.LOAD_STATE))
        assert policy.get_violation_count() == 0


# ---------------------------------------------------------------------------
# TC-7~TC-11: 차단 범주 B-1~B-5
# ---------------------------------------------------------------------------

class TestBlockedCategories:
    """B-1~B-5: 차단 범주 DENY 판정"""

    @pytest.mark.parametrize("category", [
        MetadataCategory.AUTHORITY_METADATA,
        MetadataCategory.CROSS_SHARD_CORRELATION,
        MetadataCategory.OPERATIONAL_PRIORITY,
        MetadataCategory.HISTORICAL_COGNITION,
        MetadataCategory.NON_WHITELISTED_NAMESPACE,
    ])
    def test_tc7_blocked_categories_denied(self, policy, category):
        """TC-7: 차단 범주 전항목 DENY"""
        result = policy.evaluate(_req(category))
        assert result.verdict == FilterVerdict.DENY

    def test_tc8_blocked_increments_violation(self, policy):
        """TC-8: 차단 범주 요청은 위반 카운트 증가"""
        policy.evaluate(_req(MetadataCategory.AUTHORITY_METADATA))
        assert policy.get_violation_count() == 1

    def test_tc9_audit_required_on_deny(self, policy):
        """TC-9: DENY 시 audit_required=True"""
        result = policy.evaluate(_req(MetadataCategory.AUTHORITY_METADATA))
        assert result.audit_required is True


# ---------------------------------------------------------------------------
# TC-10~TC-12: C-3 모호성 차단
# ---------------------------------------------------------------------------

class TestAmbiguityBlocking:
    """C-3: 모호성 → blocked (추정 금지)"""

    def test_tc10_unknown_category_denied(self, policy):
        """TC-10: UNKNOWN 카테고리 DENY"""
        result = policy.evaluate(_req(MetadataCategory.UNKNOWN))
        assert result.verdict == FilterVerdict.DENY

    def test_tc11_unknown_triggers_violation_count(self, policy):
        """TC-11: UNKNOWN 요청은 위반 카운트 증가"""
        policy.evaluate(_req(MetadataCategory.UNKNOWN))
        assert policy.get_violation_count() == 1


# ---------------------------------------------------------------------------
# TC-13: C-4 / Lock-7 — LOAD_STATE 가시성 계약
# ---------------------------------------------------------------------------

class TestLoadStateVisibility:
    """C-4: 상태 가시성 허용, 권한 구조 노출 금지"""

    def test_tc13_load_state_metadata_no_authority(self, policy):
        """TC-13: get_load_state_metadata에 authority 정보 미포함"""
        meta = policy.get_load_state_metadata()
        forbidden_keys = {"authority", "privilege", "escalation", "approval_scope"}
        assert not forbidden_keys.intersection(set(meta.keys()))
        assert "mode" in meta
        assert "write_enabled" in meta
        assert meta["write_enabled"] is False


# ---------------------------------------------------------------------------
# TC-14~TC-16: D-1~D-5 강등 판정
# ---------------------------------------------------------------------------

class TestDegradationDetector:
    """D-1~D-5: 강등 판정 기준"""

    def test_tc14_normal_state_no_degradation(self):
        """TC-14: 정상 상태 — 강등 없음"""
        state = LoadState()
        should_degrade, reason = DegradationDetector.evaluate(state)
        assert should_degrade is False

    def test_tc15_shard_incomplete_triggers_degradation(self):
        """TC-15: D-1 shard incomplete → 강등"""
        state = LoadState(shard_complete=False)
        should_degrade, reason = DegradationDetector.evaluate(state)
        assert should_degrade is True
        assert "D-1" in reason

    def test_tc16_authority_integrity_fail_triggers_degradation(self):
        """TC-16: D-2 authority integrity 실패 → 강등"""
        state = LoadState(authority_integrity_ok=False)
        should_degrade, reason = DegradationDetector.evaluate(state)
        assert should_degrade is True
        assert "D-2" in reason


# ---------------------------------------------------------------------------
# TC-17: TA-4 화이트리스트 무결성
# ---------------------------------------------------------------------------

class TestWhitelistIntegrity:
    """TA-4: 화이트리스트 하드코딩 무결성"""

    def test_tc17_whitelist_integrity_hash_stable(self):
        """TC-17: 화이트리스트 해시 불변"""
        import hashlib
        import json
        computed = hashlib.sha256(
            json.dumps(
                sorted(c.value for c in _ALLOWED_CATEGORIES),
                sort_keys=True
            ).encode()
        ).hexdigest()
        assert computed == _WHITELIST_INTEGRITY_HASH

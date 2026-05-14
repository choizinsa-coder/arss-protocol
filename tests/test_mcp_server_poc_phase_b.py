"""
PHASE-B 테스트 — PT-S125-BOOT-ONDEMAND-001
EAG: EAG-2 비오(Joshua) 승인 (S127)
"""

import sys
import os
import time
import threading
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Broker / Server 임포트
# ---------------------------------------------------------------------------

from mcp_audit_broker import AuditBroker, AuditPersistenceError, _AppendOnlyLedger
from mcp_server_poc import (
    ThrottleGuard, IntegrityChecker, _build_allowed_tools,
    FORBIDDEN_TOOLS, PHASE_A_ALLOWED_LAYERS,
    ThrottleError, FreshnessError, RoutingIntegrityError,
    STATE_RATE_LIMIT_EXCEEDED, STATE_AUDIT_UNVERIFIED,
    STATE_SEMANTIC_DOMAIN_MISMATCH, STATE_READ_ONLY_COGNITION_MODE,
    THROTTLE_CALL_LIMIT, THROTTLE_CALL_WINDOW_S,
    THROTTLE_SESSION_LIMIT, THROTTLE_COOLDOWN_S,
    T2_TOOL_EXECUTION_TIMEOUT_S,
    SHARD_DOMAIN_REGISTRY,
)


# ===========================================================================
# B-1 Throttling 테스트
# ===========================================================================

class TestThrottleGuard:

    def _fresh(self) -> ThrottleGuard:
        return ThrottleGuard()

    def test_b1_call_limit_exceeded(self):
        """B-1-A: CALL 단위 상한(3/10s) 초과 시 ThrottleError."""
        g = self._fresh()
        for _ in range(THROTTLE_CALL_LIMIT):
            g.check()
        with pytest.raises(ThrottleError) as exc_info:
            g.check()
        assert STATE_RATE_LIMIT_EXCEEDED in str(exc_info.value)

    def test_b1_session_limit_exceeded(self):
        """B-1-A: SESSION 단위 상한(30) 초과 시 ThrottleError."""
        g = self._fresh()
        # window를 속이기 위해 _call_window를 직접 조작
        g._session_count = THROTTLE_SESSION_LIMIT
        with pytest.raises(ThrottleError) as exc_info:
            g.check()
        assert STATE_RATE_LIMIT_EXCEEDED in str(exc_info.value)

    def test_b1_cooldown_blocks_recovery(self):
        """B-1-B: cooldown 중 호출은 ThrottleError."""
        g = self._fresh()
        # cooldown 수동 진입
        g._cooldown_until = time.monotonic() + 999.0
        with pytest.raises(ThrottleError) as exc_info:
            g.check()
        assert "cooldown" in str(exc_info.value)

    def test_b1_recovery_requires_prevalidation(self):
        """B-1-B: cooldown 만료 후 prevalidation PASS 시 복구 성공."""
        g = self._fresh()
        g._cooldown_until = time.monotonic() - 1.0  # 이미 만료
        result = g.try_recover()
        assert result is True

    def test_b1_recovery_fails_during_cooldown(self):
        """B-1-B: cooldown 미만료 시 복구 실패."""
        g = self._fresh()
        g._cooldown_until = time.monotonic() + 999.0
        result = g.try_recover()
        assert result is False

    def test_b1_prevalidation_timeout_guard(self):
        """B-1-B TA-1: prevalidation hang 방지 — timeout 내 완료."""
        g = self._fresh()
        # prevalidation_pass는 즉시 반환 → hang 없음 확인
        start = time.monotonic()
        result = g.prevalidation_pass()
        elapsed = time.monotonic() - start
        assert result is True
        assert elapsed < 1.0  # 1초 이내


# ===========================================================================
# B-2 Audit Broker 테스트
# ===========================================================================

class TestAuditBroker:

    def _make_broker(self, tmp_path) -> AuditBroker:
        ledger = _AppendOnlyLedger(str(tmp_path / "audit.log"))
        return AuditBroker(ledger=ledger)

    def test_b2_submit_event_success(self, tmp_path):
        """B-2-A: audit event 정상 기록."""
        broker = self._make_broker(tmp_path)
        # AuditPersistenceError 없이 완료되어야 함
        broker.submit_event("ping", "L0", "ok", "PHASE-B")

    def test_b2_submit_deny_success(self, tmp_path):
        """B-2-A: DENY 이벤트 정상 기록."""
        broker = self._make_broker(tmp_path)
        broker.submit_deny("forbidden_tool", "FORBIDDEN_TOOLS", "PHASE-B")

    def test_b2_authority_separation(self, tmp_path):
        """B-2-B: execution layer가 직접 write하지 않음 — broker 경유 확인."""
        log_path = tmp_path / "audit.log"
        ledger = _AppendOnlyLedger(str(log_path))
        broker = AuditBroker(ledger=ledger)
        broker.submit_event("get_server_status", "L1", "ok", "PHASE-B")
        time.sleep(0.1)
        assert log_path.exists()
        content = log_path.read_text()
        assert "get_server_status" in content

    def test_b2_t3_timeout_raises(self, tmp_path):
        """B-3 T-3: audit persistence timeout 시 AuditPersistenceError."""
        import queue as _queue

        class HangLedger:
            def write(self, entry):
                time.sleep(999)  # hang 시뮬레이션

        broker = AuditBroker(ledger=HangLedger())
        with pytest.raises(AuditPersistenceError) as exc_info:
            broker.submit_event("ping", "L0", "ok", "PHASE-B")
        assert "T-3" in str(exc_info.value) or "TIMEOUT" in str(exc_info.value)


# ===========================================================================
# B-3 Timeout 테스트
# ===========================================================================

class TestTimeoutContract:

    def test_b3_t2_execution_timeout(self):
        """B-3 T-2: tool execution timeout(5s) — hang 도구 FAIL_CLOSED."""
        from mcp_server_poc import ToolExecutionTimeoutError, ThrottleGuard
        import mcp_server_poc as srv

        # hang 도구 등록 (테스트 전용)
        original = srv.ALLOWED_TOOLS.copy()
        srv.ALLOWED_TOOLS["_hang_tool"] = {
            "name": "_hang_tool", "layer": "L0",
            "fn": lambda: time.sleep(999),
            "description": "test", "inputSchema": {},
        }
        srv._throttle_guard = ThrottleGuard()

        # hang 도구를 짧은 timeout으로 실행
        original_t2 = srv.T2_TOOL_EXECUTION_TIMEOUT_S
        srv.T2_TOOL_EXECUTION_TIMEOUT_S = 0.1

        try:
            with pytest.raises((ToolExecutionTimeoutError, RuntimeError)):
                srv._dispatch("_hang_tool")
        finally:
            srv.ALLOWED_TOOLS = original
            srv.T2_TOOL_EXECUTION_TIMEOUT_S = original_t2
            srv._throttle_guard = None

    def test_b3_audit_unverified_result(self, tmp_path):
        """B-3: audit 실패 시 AUDIT_UNVERIFIED_RESULT — 반환값 폐기."""
        import mcp_server_poc as srv

        class HangLedger:
            def write(self, entry):
                time.sleep(999)

        broker = AuditBroker(ledger=HangLedger())
        srv._audit_broker = broker
        srv._throttle_guard = ThrottleGuard()

        try:
            with pytest.raises(RuntimeError) as exc_info:
                srv._dispatch("ping")
            assert STATE_AUDIT_UNVERIFIED in str(exc_info.value)
        finally:
            srv._audit_broker = None
            srv._throttle_guard = None


# ===========================================================================
# B-4-A Freshness Mismatch 테스트
# ===========================================================================

class TestFreshnessContract:

    def test_b4a_epoch_match_allow(self):
        """B-4-A: epoch + hash 일치 시 ALLOW."""
        result = IntegrityChecker.check_freshness(
            canonical_epoch=1000, source_hash="abc",
            current_epoch=1000, current_hash="abc",
        )
        assert result == "ALLOW"

    def test_b4a_source_hash_mismatch_deny(self):
        """B-4-A: source_hash 불일치 시 무조건 DENY."""
        with pytest.raises(FreshnessError) as exc_info:
            IntegrityChecker.check_freshness(
                canonical_epoch=1000, source_hash="WRONG",
                current_epoch=1000, current_hash="abc",
            )
        assert "source_hash" in str(exc_info.value)

    def test_b4a_epoch_mismatch_deny_default(self):
        """B-4-A: canonical_epoch 불일치 기본 DENY."""
        with pytest.raises(FreshnessError) as exc_info:
            IntegrityChecker.check_freshness(
                canonical_epoch=999, source_hash="abc",
                current_epoch=1000, current_hash="abc",
            )
        assert "canonical_epoch" in str(exc_info.value)

    def test_b4a_epoch_mismatch_read_only_eligible(self):
        """B-4-A: canonical_epoch 불일치 + read_only_eligible=True → READ_ONLY_COGNITION_MODE."""
        result = IntegrityChecker.check_freshness(
            canonical_epoch=999, source_hash="abc",
            current_epoch=1000, current_hash="abc",
            read_only_eligible=True,
        )
        assert result == STATE_READ_ONLY_COGNITION_MODE

    def test_b4a_stale_but_readable_disallowed(self):
        """B-4-A: stale-but-readable 불허 — read_only_eligible=False 기본."""
        with pytest.raises(FreshnessError):
            IntegrityChecker.check_freshness(
                canonical_epoch=1, source_hash="abc",
                current_epoch=2, current_hash="abc",
                read_only_eligible=False,
            )


# ===========================================================================
# B-4-B Retrieval Routing Integrity 테스트
# ===========================================================================

class TestRoutingIntegrity:

    def test_b4b_matching_shard_pass(self):
        """B-4-B: requested == returned shard → 통과."""
        IntegrityChecker.check_routing_integrity("task", "task")  # 예외 없음

    def test_b4b_domain_mismatch_fail_closed(self):
        """B-4-B: shard 불일치 시 SEMANTIC_DOMAIN_MISMATCH + FAIL_CLOSED."""
        with pytest.raises(RoutingIntegrityError) as exc_info:
            IntegrityChecker.check_routing_integrity("task", "archive")
        assert STATE_SEMANTIC_DOMAIN_MISMATCH in str(exc_info.value)

    def test_b4b_unknown_shard_fail_closed(self):
        """B-4-B: 미등재 shard 요청 시 FAIL_CLOSED."""
        with pytest.raises(RoutingIntegrityError) as exc_info:
            IntegrityChecker.check_routing_integrity("unknown_shard", "unknown_shard")
        assert STATE_SEMANTIC_DOMAIN_MISMATCH in str(exc_info.value)

    def test_b4b_lock2_all_registered_shards(self):
        """B-4-B: Lock-2 — 등재된 모든 shard는 자기 자신과 일치."""
        for shard in SHARD_DOMAIN_REGISTRY:
            IntegrityChecker.check_routing_integrity(shard, shard)  # 예외 없음


# ===========================================================================
# PHASE-A 구조 불변성 회귀 테스트
# ===========================================================================

class TestPhaseAInvariant:

    def test_forbidden_tools_not_in_allowed(self):
        """PHASE-A invariant: FORBIDDEN_TOOLS는 ALLOWED_TOOLS에 등재 불가."""
        allowed = _build_allowed_tools()
        for name in FORBIDDEN_TOOLS:
            assert name not in allowed

    def test_allowed_tools_layer_within_phase_a(self):
        """PHASE-A invariant: ALLOWED_TOOLS 전체 계층이 L0/L1 이내."""
        allowed = _build_allowed_tools()
        for name, entry in allowed.items():
            assert entry["layer"] in PHASE_A_ALLOWED_LAYERS, \
                f"{name} layer={entry['layer']} not in PHASE-A allowed"

    def test_deny_by_default_unregistered(self):
        """PHASE-A invariant: 미등재 도구 DENY."""
        from mcp_server_poc import _dispatch, ThrottleGuard
        import mcp_server_poc as srv
        srv._throttle_guard = ThrottleGuard()
        try:
            with pytest.raises(PermissionError) as exc_info:
                _dispatch("nonexistent_tool_xyz")
            assert "FAIL_CLOSED" in str(exc_info.value)
        finally:
            srv._throttle_guard = None

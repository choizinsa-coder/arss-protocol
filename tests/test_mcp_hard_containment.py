"""
tests/test_mcp_hard_containment.py
HARD_CONTAINMENT Recovery Protocol v1.2 테스트
Task:  PT-S125-BOOT-ONDEMAND-001 Recovery Governance Layer
EAG:   EAG-3 비오(Joshua) 승인 (S130)

테스트 범위:
- mcp_containment_state.py: CS-1~CS-10
- mcp_recovery_validator.py: RV-1~RV-8
- HC-T-xx trigger integration: HT-1~HT-7
"""

import logging as _logging
import json
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

# sys.path 주입 (importlib 모드 대응)
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_TESTS_DIR)
_MCP_DIR = os.path.join(_PROJECT_ROOT, "tools", "mcp")
for _p in [_MCP_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from mcp_containment_state import (
    RECOVERY_STATUS_LOCKED,
    RECOVERY_STATUS_OBSERVATION,
    _fail_closed_state,
    _generate_incident_id,
    enter_containment,
    enter_observation_mode,
    get_state,
    is_active,
    load_state,
    read_containment_state,
    release_containment,
    save_state,
    update_recovery_status,
)
from mcp_recovery_validator import build_incident_context, validate_trigger


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _tmp_path():
    """임시 파일 경로 반환."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return path


# ══════════════════════════════════════════════════════════════════════════════
# CS: ContainmentState 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestContainmentState(unittest.TestCase):

    # CS-1: 파일 없을 시 FAIL_CLOSED
    def test_cs1_missing_file_fail_closed(self):
        path = _tmp_path()
        state = load_state(path)
        self.assertTrue(state["containment_active"])
        self.assertEqual(state["recovery_status"], RECOVERY_STATUS_LOCKED)
        self.assertIn("fail_closed_reason", state)

    # CS-2: parse 실패 시 FAIL_CLOSED
    def test_cs2_parse_error_fail_closed(self):
        path = _tmp_path()
        with open(path, "w") as f:
            f.write("NOT_JSON{{{{")
        state = load_state(path)
        self.assertTrue(state["containment_active"])
        self.assertEqual(state["fail_closed_reason"], "STATE_FILE_PARSE_ERROR")
        os.unlink(path)

    # CS-3: 필수 필드 누락 시 FAIL_CLOSED
    def test_cs3_schema_error_fail_closed(self):
        path = _tmp_path()
        with open(path, "w") as f:
            json.dump({"containment_active": True}, f)
        state = load_state(path)
        self.assertTrue(state["containment_active"])
        self.assertEqual(state["fail_closed_reason"], "STATE_FILE_SCHEMA_ERROR")
        os.unlink(path)

    # CS-4: 정상 파일 로드
    def test_cs4_normal_load(self):
        path = _tmp_path()
        normal = {
            "containment_active": False,
            "trigger_id": "HC-T-01",
            "entered_at": "2026-05-15T00:00:00+09:00",
            "incident_id": "HC-INC-ABCD1234",
            "recovery_status": "RELEASED",
        }
        with open(path, "w") as f:
            json.dump(normal, f)
        state = load_state(path)
        self.assertFalse(state["containment_active"])
        self.assertEqual(state["trigger_id"], "HC-T-01")
        os.unlink(path)

    # CS-5: enter_containment 정상 동작
    def test_cs5_enter_containment(self):
        path = _tmp_path()
        state = enter_containment("HC-T-01", path=path)
        self.assertTrue(state["containment_active"])
        self.assertEqual(state["trigger_id"], "HC-T-01")
        self.assertEqual(state["recovery_status"], RECOVERY_STATUS_LOCKED)
        self.assertTrue(state["incident_id"].startswith("HC-INC-"))
        os.unlink(path)

    # CS-6: 유효하지 않은 trigger_id -> UNKNOWN으로 대체
    def test_cs6_invalid_trigger_id(self):
        path = _tmp_path()
        state = enter_containment("INVALID-TRIGGER", path=path)
        self.assertEqual(state["trigger_id"], "UNKNOWN")
        os.unlink(path)

    # CS-7: enter_observation_mode
    def test_cs7_enter_observation_mode(self):
        path = _tmp_path()
        enter_containment("HC-T-02", path=path)
        state = enter_observation_mode(path=path)
        self.assertTrue(state["containment_active"])  # 여전히 active
        self.assertEqual(state["recovery_status"], RECOVERY_STATUS_OBSERVATION)
        self.assertIn("observation_entered_at", state)
        os.unlink(path)

    # CS-8: release_containment (비오 수동 경로 시뮬레이션)
    def test_cs8_release_containment(self):
        path = _tmp_path()
        enter_containment("HC-T-03", path=path)
        state = release_containment(path=path)
        self.assertFalse(state["containment_active"])
        self.assertEqual(state["recovery_status"], "RELEASED")
        self.assertIn("released_at", state)
        os.unlink(path)

    # CS-9: is_active FAIL_CLOSED 기본값
    def test_cs9_is_active_fail_closed(self):
        path = _tmp_path()
        self.assertTrue(is_active(path=path))  # 파일 없음 -> FAIL_CLOSED -> True

    # CS-10: 재진입 = NEW INCIDENT (incident_id 갱신)
    def test_cs10_reentry_new_incident(self):
        path = _tmp_path()
        s1 = enter_containment("HC-T-01", path=path)
        s2 = enter_containment("HC-T-02", path=path)
        self.assertNotEqual(s1["incident_id"], s2["incident_id"])
        self.assertEqual(s2["trigger_id"], "HC-T-02")
        os.unlink(path)


# ══════════════════════════════════════════════════════════════════════════════
# RV: RecoveryValidator 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestRecoveryValidator(unittest.TestCase):

    def _make_active_state(self, trigger_id="HC-T-01", incident_id="HC-INC-TEST0001"):
        return {
            "containment_active": True,
            "trigger_id": trigger_id,
            "entered_at": "2026-05-15T00:00:00+09:00",
            "incident_id": incident_id,
            "recovery_status": RECOVERY_STATUS_LOCKED,
        }

    def _make_ctx(self, trigger_id="HC-T-01", incident_id="HC-INC-TEST0001"):
        return build_incident_context(
            trigger_id=trigger_id,
            incident_id=incident_id,
            entered_at="2026-05-15T00:00:00+09:00",
        )

    # RV-1: PASS 기본 케이스
    def test_rv1_pass_basic(self):
        ctx = self._make_ctx()
        state = self._make_active_state()
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["resolved_trigger"], "HC-T-01")
        self.assertFalse(result["ambiguity_detected"])
        self.assertFalse(result["multi_trigger_detected"])

    # RV-2: containment_active=False -> FAIL
    def test_rv2_containment_not_active(self):
        ctx = self._make_ctx()
        state = self._make_active_state()
        state["containment_active"] = False
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("CONTAINMENT_NOT_ACTIVE", result["fail_reason"])

    # RV-3: trigger_id mismatch -> FAIL + ambiguity
    def test_rv3_trigger_mismatch(self):
        ctx = self._make_ctx(trigger_id="HC-T-01")
        state = self._make_active_state(trigger_id="HC-T-02")
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["ambiguity_detected"])
        self.assertIn("TRIGGER_MISMATCH", result["fail_reason"])

    # RV-4: UNKNOWN trigger -> FAIL + ambiguity
    def test_rv4_unknown_trigger(self):
        ctx = self._make_ctx(trigger_id="UNKNOWN")
        state = self._make_active_state(trigger_id="UNKNOWN")
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["ambiguity_detected"])
        self.assertIn("UNKNOWN_TRIGGER", result["fail_reason"])

    # RV-5: incident_id mismatch -> FAIL
    def test_rv5_incident_id_mismatch(self):
        ctx = self._make_ctx(incident_id="HC-INC-AAAA")
        state = self._make_active_state(incident_id="HC-INC-BBBB")
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("INCIDENT_ID_MISMATCH", result["fail_reason"])

    # RV-6: audit_reference 빈 리스트 -> FAIL
    def test_rv6_empty_audit(self):
        ctx = self._make_ctx()
        state = self._make_active_state()
        result = validate_trigger(ctx, state, audit_reference=[])
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("AUDIT_EMPTY", result["fail_reason"])

    # RV-7: audit_reference DENY 기록 있음 -> PASS
    def test_rv7_audit_with_deny(self):
        ctx = self._make_ctx()
        state = self._make_active_state()
        audit = [{"decision": "DENY", "reason": "NONCE_REUSED"}]
        result = validate_trigger(ctx, state, audit_reference=audit)
        self.assertEqual(result["status"], "PASS")

    # RV-8: multi_trigger -> FAIL
    def test_rv8_multi_trigger(self):
        ctx = build_incident_context(
            trigger_id="HC-T-01",
            incident_id="HC-INC-TEST0001",
            entered_at="2026-05-15T00:00:00+09:00",
            additional_triggers=["HC-T-02"],
        )
        state = self._make_active_state()
        result = validate_trigger(ctx, state)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(result["multi_trigger_detected"])
        self.assertIn("MULTI_TRIGGER", result["fail_reason"])


# ══════════════════════════════════════════════════════════════════════════════
# HT: Trigger Integration 테스트
# ══════════════════════════════════════════════════════════════════════════════

class TestTriggerIntegration(unittest.TestCase):

    # HT-1: HC-T-01 threshold 동작 확인
    def test_ht1_hct01_threshold(self):
        from mcp_server_poc_phase_c import (
            _record_hmac_failure,
            reset_all_hmac_counters,
        )
        reset_all_hmac_counters()
        with patch("mcp_server_poc_phase_c.enter_containment") as mock_enter:
            _record_hmac_failure("domi")
            _record_hmac_failure("domi")
            mock_enter.assert_not_called()
            # 3회째 -> containment
            _record_hmac_failure("domi")
            mock_enter.assert_called_once_with("HC-T-01")
        reset_all_hmac_counters()

    # HT-2: HC-T-01 single success reset
    def test_ht2_hct01_reset_on_success(self):
        from mcp_server_poc_phase_c import (
            _record_hmac_failure,
            _reset_hmac_failure,
            get_hmac_failure_count,
            reset_all_hmac_counters,
        )
        reset_all_hmac_counters()
        _record_hmac_failure("jeni")
        _record_hmac_failure("jeni")
        self.assertEqual(get_hmac_failure_count("jeni"), 2)
        _reset_hmac_failure("jeni")
        self.assertEqual(get_hmac_failure_count("jeni"), 0)
        reset_all_hmac_counters()

    # HT-3: HC-T-02 nonce replay -> containment 진입
    def test_ht3_hct02_nonce_replay(self):
        from mcp_nonce_store import clear_nonce_store, consume_nonce
        clear_nonce_store()
        consume_nonce("test-nonce-001")
        with patch("mcp_nonce_store.enter_containment") as mock_enter:
            result = consume_nonce("test-nonce-001")
            self.assertFalse(result)
            mock_enter.assert_called_once_with("HC-T-02")
        clear_nonce_store()

    # HT-4: HC-T-03 forbidden shard -> containment 진입
    def test_ht4_hct03_forbidden_shard(self):
        from mcp_shard_router import route_shard
        with patch("mcp_shard_router.enter_containment") as mock_enter:
            result = route_shard("caddy", "full_session_context")
            self.assertFalse(result.allowed)
            mock_enter.assert_called_once_with("HC-T-03")

    # HT-5: HC-T-04 filter violation threshold -> containment 진입
    def test_ht5_hct04_filter_violation(self):
        from mcp_filter_policy import FilterPolicy, MetadataCategory, MetadataRequest
        policy = FilterPolicy()
        req = MetadataRequest(
            namespace="test-ns",
            category=MetadataCategory.AUTHORITY_METADATA,
            requester_id="caddy",
        )
        with patch("mcp_filter_policy._trigger_hct04") as mock_hct04:
            for _ in range(3):
                policy.evaluate(req)
            mock_hct04.assert_called_once()

    # HT-6: HC-T-05 audit append failure -> containment 진입
    def test_ht6_hct05_audit_failure(self):
        from mcp_audit_broker import write_audit
        with patch("mcp_audit_broker.open", side_effect=OSError("disk full")):
            with patch("mcp_audit_broker.os.makedirs"):
                with patch("mcp_audit_broker._trigger_hct05") as mock_hct05:
                    try:
                        write_audit(
                            agent_id="caddy",
                            requested_shard="active_tasks",
                            returned_scope="active_tasks",
                            decision="ALLOW",
                            reason="ALLOWED",
                        )
                    except OSError as _rule6_e:
                        _logging.debug("RULE6 test_mcp_hard_containment: %s", _rule6_e)
                    mock_hct05.assert_called_once()

    # HT-7: HARD_CONTAINMENT 활성 시 handle_retrieval 차단
    def test_ht7_containment_blocks_retrieval(self):
        path = _tmp_path()
        enter_containment("HC-T-07", path=path)
        with patch("mcp_server_poc_phase_c.is_active", return_value=True):
            from mcp_server_poc_phase_c import handle_retrieval
            result = handle_retrieval({
                "agent_id": "caddy",
                "shard": "active_tasks",
                "timestamp": str(time.time()),
                "nonce": "test-nonce",
                "signature": "fake",
            })
            self.assertFalse(result["ok"])
            self.assertIn("HARD_CONTAINMENT", result["reason"])
        if os.path.exists(path):
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()

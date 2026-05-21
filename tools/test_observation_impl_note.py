"""
test_observation_impl_note.py
IMPL-NOTE-03/04 검증 테스트 — PT-S142-SANDBOX-LAYER1-LAYER2-001 EAG-2
TC-01~TC-10
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# ── 경로 설정 ───────────────────────────────────────────────────────────────
VPS_TOOLS = Path("/opt/arss/engine/arss-protocol/tools")
if str(VPS_TOOLS) not in sys.path:
    sys.path.insert(0, str(VPS_TOOLS))

import projection_builder as pb
import observation_server as obs


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _make_fake_sandbox(tmp_root: Path, agent: str, file_count: int):
    """테스트용 sandbox/{agent}/active/ 구조 생성"""
    active_dir = tmp_root / agent / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    for i in range(file_count):
        (active_dir / f"task-S143-T{i:03d}-{agent}-draft.md").write_text(f"content {i}")
    return active_dir


def _reset_observation_state():
    """observation_server _system_state 초기화"""
    with obs._fail_closed_lock:
        obs._system_state["observation_locked"] = False
        obs._system_state["lock_reason"] = None
        obs._system_state["lock_time"] = None
        obs._system_state["incident_id"] = None


def _reset_projection_cache():
    pb._cache["projection"] = None
    pb._cache["built_at_epoch"] = 0.0
    pb._cache["stale"] = True
    pb._cache["refresh_failed"] = False


# ════════════════════════════════════════════════════════════════════════════
# IMPL-NOTE-03: active 파일 수 stale 판정 (TC-01 ~ TC-04)
# ════════════════════════════════════════════════════════════════════════════

class TestImplNote03ActiveFileCount(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_projection_cache()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tc01_zero_files_not_stale(self):
        """TC-01: active 파일 0개 → state_anchor_stale=false"""
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["total"], 0)
        self.assertFalse(result["state_anchor_stale"])
        self.assertFalse(result["active_file_count_warning"])
        self.assertFalse(result["eag_ready_blocked"])

    def test_tc02_exactly_threshold_not_stale(self):
        """TC-02: active 파일 10개 → state_anchor_stale=false (경계값)"""
        _make_fake_sandbox(self.tmp, "domi", 10)
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["domi"], 10)
        self.assertFalse(result["state_anchor_stale"],
                         "exactly 10 must NOT trigger stale (> not >=)")

    def test_tc03_over_threshold_stale(self):
        """TC-03: active 파일 11개 → STATE_ANCHOR_STALE=true + WARNING=true"""
        _make_fake_sandbox(self.tmp, "jeni", 11)
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["jeni"], 11)
        self.assertTrue(result["state_anchor_stale"])
        self.assertTrue(result["active_file_count_warning"])
        self.assertTrue(result["eag_ready_blocked"])

    def test_tc04_stale_projection_still_returned(self):
        """TC-04: stale 상태에서도 projection 자체는 반환 (Fail-Closed 발동 없음)"""
        _make_fake_sandbox(self.tmp, "caddy", 15)
        fake_ctx = {
            "system_name": "AIBA",
            "system_version": "v3.2",
            "session_count": 143,
        }
        with patch.object(pb, "SANDBOX_ROOT", self.tmp), \
             patch.object(pb, "_load_session_context", return_value=fake_ctx):
            _reset_projection_cache()
            projection, is_stale_flag = pb.get_projection()

        # projection 반환 확인 (None 아님)
        self.assertIsNotNone(projection)
        self.assertFalse(is_stale_flag)  # TTL 기준으로는 fresh
        # IMPL-NOTE-03 stale 필드 확인
        self.assertTrue(projection.get("state_anchor_stale"))
        self.assertTrue(projection.get("active_file_count_warning"))
        self.assertTrue(projection.get("eag_ready_blocked"))
        # AUTHORITY 유지 확인
        self.assertEqual(projection.get("AUTHORITY_LEVEL"), "OBSERVATION_ONLY_NO_EXECUTION")
        self.assertFalse(projection.get("execution_allowed"))


# ════════════════════════════════════════════════════════════════════════════
# IMPL-NOTE-04: Fail-Closed state file persist (TC-05 ~ TC-06)
# ════════════════════════════════════════════════════════════════════════════

class TestImplNote04StateFilePersist(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_observation_state()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_observation_state()

    def test_tc05_load_unlocked_state(self):
        """TC-05: state file locked=false → 서버 기동 시 unlocked 복구"""
        state_file = self.tmp / "observation_fail_closed_state.json"
        state_file.write_text(json.dumps({
            "observation_locked": False,
            "locked_at": None,
            "reason": None,
            "incident_id": None,
            "locked_by": None,
            "unlock_required_by": "beo",
        }))
        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file):
            obs._load_fail_closed_state()
        self.assertFalse(obs._system_state["observation_locked"])

    def test_tc06_load_locked_state_persists(self):
        """TC-06: state file locked=true → 서버 기동 시 locked 상태 복구"""
        state_file = self.tmp / "observation_fail_closed_state.json"
        state_file.write_text(json.dumps({
            "observation_locked": True,
            "locked_at": "2026-05-21T10:00:00+09:00",
            "reason": "test_lock",
            "incident_id": "INC-TEST-001",
            "locked_by": "system",
            "unlock_required_by": "beo",
        }))
        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file):
            obs._load_fail_closed_state()
        self.assertTrue(obs._system_state["observation_locked"])
        self.assertEqual(obs._system_state["lock_reason"], "test_lock")
        self.assertEqual(obs._system_state["incident_id"], "INC-TEST-001")


# ════════════════════════════════════════════════════════════════════════════
# IMPL-NOTE-04: Unlock 엔드포인트 (TC-07 ~ TC-10)
# ════════════════════════════════════════════════════════════════════════════

class TestImplNote04UnlockEndpoint(unittest.TestCase):

    VALID_UNLOCK_BODY = {
        "actor": "beo",
        "approval_phrase": "BEO_APPROVE_OBSERVATION_UNLOCK",
        "incident_id": "INC-S143-001",
        "jeni_trust_revalidation": "PASS",
        "caddy_incident_report": "PRESENT",
        "new_token_rotation": "DONE",
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_observation_state()
        _reset_projection_cache()
        # Fail-Closed 상태로 설정
        with obs._fail_closed_lock:
            obs._system_state["observation_locked"] = True
            obs._system_state["lock_reason"] = "test"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_observation_state()

    def _make_handler(self, body: dict, client_ip: str = "127.0.0.1"):
        """ObservationHandler mock 생성"""
        handler = MagicMock(spec=obs.ObservationHandler)
        handler.client_address = (client_ip, 12345)
        raw = json.dumps(body).encode("utf-8")
        handler.headers = {
            "Content-Length": str(len(raw)),
            "Content-Type": "application/json",
        }
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = raw

        # _send_json / _send_error 실제 응답 캡처
        responses = []

        def fake_send_json(status, body_dict):
            responses.append((status, body_dict))
            return len(json.dumps(body_dict))

        def fake_send_error(status, reason):
            return fake_send_json(status, {"error": reason, "execution_allowed": False})

        handler._send_json.side_effect = fake_send_json
        handler._send_error.side_effect = fake_send_error
        handler._is_loopback.return_value = (client_ip in ("127.0.0.1", "::1"))
        # observation_server_v2: _handle_unlock이 _read_body() 사용
        handler._read_body.return_value = body
        handler.responses = responses
        return handler

    def test_tc07_valid_unlock_succeeds(self):
        """TC-07: 6종 조건 전부 충족 → 200 + state file 갱신 + locked=false"""
        state_file = self.tmp / "observation_fail_closed_state.json"
        audit_dir = self.tmp / "audit"
        audit_dir.mkdir()

        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file), \
             patch.object(obs, "AUDIT_DIR", audit_dir), \
             patch.object(obs, "invalidate_cache") as mock_invalidate, \
             patch.object(obs, "_write_audit"):
            handler = self._make_handler(self.VALID_UNLOCK_BODY)
            obs.ObservationHandler._handle_unlock(handler)

        # locked 해제 확인
        self.assertFalse(obs._system_state["observation_locked"])
        # state file 갱신 확인
        self.assertTrue(state_file.exists())
        with open(state_file) as f:
            saved = json.load(f)
        self.assertFalse(saved["observation_locked"])
        # cache 무효화 호출 확인
        mock_invalidate.assert_called_once()
        # 응답 확인
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["result"], "OBSERVATION_UNLOCKED")

    def test_tc08_missing_condition_denied(self):
        """TC-08: 조건 1종 누락 → 403 DENY + locked 유지"""
        bad_body = dict(self.VALID_UNLOCK_BODY)
        bad_body["jeni_trust_revalidation"] = "FAIL"  # 의도적 실패

        with patch.object(obs, "_write_audit"):
            handler = self._make_handler(bad_body)
            obs.ObservationHandler._handle_unlock(handler)

        # locked 유지 확인
        self.assertTrue(obs._system_state["observation_locked"])
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("OBSERVATION_UNLOCK_DENIED", body["error"])
        self.assertIn("JENI_TRUST_REVALIDATION_NOT_PASS", body["error"])

    def test_tc09_unlock_invalidates_projection_cache(self):
        """TC-09: unlock 후 fresh projection 강제 확인 (캐시 무효화)"""
        # 캐시에 stale 데이터 주입
        pb._cache["projection"] = {"stale_data": True}
        pb._cache["built_at_epoch"] = time.time()

        state_file = self.tmp / "observation_fail_closed_state.json"
        audit_dir = self.tmp / "audit"
        audit_dir.mkdir()

        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file), \
             patch.object(obs, "AUDIT_DIR", audit_dir), \
             patch.object(obs, "_write_audit"):
            handler = self._make_handler(self.VALID_UNLOCK_BODY)
            obs.ObservationHandler._handle_unlock(handler)

        # 캐시 무효화 확인 (built_at_epoch=0)
        self.assertEqual(pb._cache["built_at_epoch"], 0.0)
        self.assertIsNone(pb._cache["projection"])

    def test_tc10_non_loopback_denied(self):
        """TC-10: loopback 외부 IP unlock 시도 → 403 DENY"""
        with patch.object(obs, "_write_audit"):
            handler = self._make_handler(self.VALID_UNLOCK_BODY, client_ip="192.168.1.100")
            obs.ObservationHandler._handle_unlock(handler)

        # locked 유지 확인
        self.assertTrue(obs._system_state["observation_locked"])
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("LOOPBACK_ONLY", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

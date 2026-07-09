"""
test_observation_impl_note.py
IMPL-NOTE-03/04 검증 테스트 — PT-S142-SANDBOX-LAYER1-LAYER2-001 EAG-2
TC-01~TC-10
RULE-3 이동: tools/ → tests/ (S153)

S180 수정: Incident-L14 Group D 수습
  - TC-04 (test_tc04_stale_projection_still_returned):
    Phase A(S151) 이후 projection_builder.py에서 _load_session_context가
    load_canonical_context()로 교체됨.
    patch 대상: pb._load_session_context → load_canonical_context
    반환값: fake_ctx → (fake_ctx, "MOCK") 튜플로 변경
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

sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools")
import projection_builder as pb
import observation_server as obs


def _make_fake_sandbox(tmp_root: Path, agent: str, file_count: int):
    active_dir = tmp_root / agent / "active"
    active_dir.mkdir(parents=True, exist_ok=True)
    for i in range(file_count):
        (active_dir / f"task-S143-T{i:03d}-{agent}-draft.md").write_text(f"content {i}")
    return active_dir


def _reset_observation_state():
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


class TestImplNote03ActiveFileCount(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_projection_cache()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tc01_zero_files_not_stale(self):
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["total"], 0)
        self.assertFalse(result["state_anchor_stale"])
        self.assertFalse(result["active_file_count_warning"])
        self.assertFalse(result["eag_ready_blocked"])

    def test_tc02_exactly_threshold_not_stale(self):
        _make_fake_sandbox(self.tmp, "domi", 10)
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["domi"], 10)
        self.assertFalse(result["state_anchor_stale"])

    def test_tc03_over_threshold_stale(self):
        _make_fake_sandbox(self.tmp, "jeni", 11)
        with patch.object(pb, "SANDBOX_ROOT", self.tmp):
            result = pb._build_sandbox_active_file_count()
        self.assertEqual(result["jeni"], 11)
        self.assertTrue(result["state_anchor_stale"])
        self.assertTrue(result["active_file_count_warning"])
        self.assertTrue(result["eag_ready_blocked"])

    def test_tc04_stale_projection_still_returned(self):
        """
        S180 Incident-L14 Group D 수습:
        Phase A(S151) 이후 _load_session_context → load_canonical_context 교체.
        patch 대상 변경:
          이전: patch.object(pb, "_load_session_context", return_value=fake_ctx)
          현재: patch("tools.context_gateway.pointer_manager.load_canonical_context",
                      return_value=(fake_ctx, "MOCK"))
        """
        _make_fake_sandbox(self.tmp, "caddy", 15)
        fake_ctx = {"system_name": "AIBA", "system_version": "v3.2", "session_count": 143}
        with patch.object(pb, "SANDBOX_ROOT", self.tmp), \
             patch(
                 "tools.context_gateway.pointer_manager.load_canonical_context",
                 return_value=(fake_ctx, "MOCK")
             ), \
             patch.object(pb, "_load_stale_manifest", return_value=None):  # C11·15: MANIFEST 없는 경우 검증 스킵
            _reset_projection_cache()
            projection, is_stale_flag = pb.get_projection()
        self.assertIsNotNone(projection)
        self.assertFalse(is_stale_flag)
        self.assertTrue(projection.get("state_anchor_stale"))
        self.assertTrue(projection.get("active_file_count_warning"))
        self.assertTrue(projection.get("eag_ready_blocked"))
        self.assertEqual(projection.get("AUTHORITY_LEVEL"), "OBSERVATION_ONLY_NO_EXECUTION")
        self.assertFalse(projection.get("execution_allowed"))


class TestImplNote04StateFilePersist(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_observation_state()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_observation_state()

    def test_tc05_load_unlocked_state(self):
        state_file = self.tmp / "observation_fail_closed_state.json"
        state_file.write_text(json.dumps({
            "observation_locked": False, "locked_at": None,
            "reason": None, "incident_id": None,
            "locked_by": None, "unlock_required_by": "beo",
        }))
        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file):
            obs._load_fail_closed_state()
        self.assertFalse(obs._system_state["observation_locked"])

    def test_tc06_load_locked_state_persists(self):
        state_file = self.tmp / "observation_fail_closed_state.json"
        state_file.write_text(json.dumps({
            "observation_locked": True,
            "locked_at": "2026-05-21T10:00:00+09:00",
            "reason": "test_lock", "incident_id": "INC-TEST-001",
            "locked_by": "system", "unlock_required_by": "beo",
        }))
        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file):
            obs._load_fail_closed_state()
        self.assertTrue(obs._system_state["observation_locked"])
        self.assertEqual(obs._system_state["lock_reason"], "test_lock")
        self.assertEqual(obs._system_state["incident_id"], "INC-TEST-001")


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
        with obs._fail_closed_lock:
            obs._system_state["observation_locked"] = True
            obs._system_state["lock_reason"] = "test"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_observation_state()

    def _make_handler(self, body: dict, client_ip: str = "127.0.0.1"):
        handler = MagicMock(spec=obs.ObservationHandler)
        handler.client_address = (client_ip, 12345)
        raw = json.dumps(body).encode("utf-8")
        handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        handler.rfile = MagicMock()
        handler.rfile.read.return_value = raw
        responses = []

        def fake_send_json(status, body_dict):
            responses.append((status, body_dict))
            return len(json.dumps(body_dict))

        def fake_send_error(status, reason):
            return fake_send_json(status, {"error": reason, "execution_allowed": False})

        handler._send_json.side_effect = fake_send_json
        handler._send_error.side_effect = fake_send_error
        handler._is_loopback.return_value = (client_ip in ("127.0.0.1", "::1"))
        handler._read_body.return_value = body
        handler.responses = responses
        return handler

    def test_tc07_valid_unlock_succeeds(self):
        state_file = self.tmp / "observation_fail_closed_state.json"
        audit_dir = self.tmp / "audit"
        audit_dir.mkdir()
        with patch.object(obs, "FAIL_CLOSED_STATE_FILE", state_file), \
             patch.object(obs, "AUDIT_DIR", audit_dir), \
             patch.object(obs, "invalidate_cache") as mock_invalidate, \
             patch.object(obs, "_write_audit"):
            handler = self._make_handler(self.VALID_UNLOCK_BODY)
            obs.ObservationHandler._handle_unlock(handler)
        self.assertFalse(obs._system_state["observation_locked"])
        self.assertTrue(state_file.exists())
        with open(state_file) as f:
            saved = json.load(f)
        self.assertFalse(saved["observation_locked"])
        mock_invalidate.assert_called_once()
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["result"], "OBSERVATION_UNLOCKED")

    def test_tc08_missing_condition_denied(self):
        bad_body = dict(self.VALID_UNLOCK_BODY)
        bad_body["jeni_trust_revalidation"] = "FAIL"
        with patch.object(obs, "_write_audit"):
            handler = self._make_handler(bad_body)
            obs.ObservationHandler._handle_unlock(handler)
        self.assertTrue(obs._system_state["observation_locked"])
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("OBSERVATION_UNLOCK_DENIED", body["error"])

    def test_tc09_unlock_invalidates_projection_cache(self):
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
        self.assertEqual(pb._cache["built_at_epoch"], 0.0)
        self.assertIsNone(pb._cache["projection"])

    def test_tc10_non_loopback_denied(self):
        with patch.object(obs, "_write_audit"):
            handler = self._make_handler(self.VALID_UNLOCK_BODY, client_ip="192.168.1.100")
            obs.ObservationHandler._handle_unlock(handler)
        self.assertTrue(obs._system_state["observation_locked"])
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("LOOPBACK_ONLY", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

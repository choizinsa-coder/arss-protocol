"""
test_token_register.py
Token Issuance 검증 테스트 — BRIEFING-DOMI-S143-TOKEN-001
TC-01~TC-08
RULE-3 이동: tools/ → tests/ (S153)
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
import observation_server as obs


# ── 헬퍼 ────────────────────────────────────────────────────────────────────

def _reset_token_store():
    with obs._token_lock:
        obs._token_store.clear()


def _reset_observation_state():
    with obs._fail_closed_lock:
        obs._system_state["observation_locked"] = False
        obs._system_state["lock_reason"] = None


VALID_REGISTER_BODY = {
    "actor": "beo",
    "approval_phrase": "BEO_APPROVE_TOKEN_REGISTER",
    "agent": "domi",
    "ttl_seconds": 43200,
}


def _make_handler(body: dict, client_ip: str = "127.0.0.1"):
    handler = MagicMock(spec=obs.ObservationHandler)
    handler.client_address = (client_ip, 12345)
    raw = json.dumps(body).encode("utf-8")
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = MagicMock()
    handler.rfile.read.return_value = raw
    responses = []
    def fake_send_json(status, body_dict):
        responses.append((status, body_dict))
        return len(json.dumps(body_dict))
    def fake_send_error(status, reason):
        return fake_send_json(status, {"error": reason, "execution_allowed": False})
    def fake_read_body(max_bytes=65536):
        return body
    handler._send_json.side_effect = fake_send_json
    handler._send_error.side_effect = fake_send_error
    handler._read_body.side_effect = fake_read_body
    handler._is_loopback.return_value = (client_ip in ("127.0.0.1", "::1"))
    handler.responses = responses
    return handler

class TestTokenRegister(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        _reset_token_store()
        _reset_observation_state()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        _reset_token_store()

    def test_tc01_valid_register_returns_token(self):
        token_file = self.tmp / ".tokens"
        with patch.object(obs, "TOKEN_FILE", token_file), \
             patch.object(obs, "_write_audit"), \
             patch("secrets.token_urlsafe", return_value="test_raw_token_abc123"):
            handler = _make_handler(VALID_REGISTER_BODY)
            obs.ObservationHandler._handle_token_register(handler)
        status, body = handler.responses[0]
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["agent"], "domi")
        self.assertIn("token", body)
        self.assertEqual(body["token"], "test_raw_token_abc123")
        self.assertIn("expires_at", body)
        self.assertIn("token_hash_prefix", body)
        self.assertFalse(body["execution_allowed"])

    def test_tc02_wrong_approval_phrase_denied(self):
        bad_body = dict(VALID_REGISTER_BODY)
        bad_body["approval_phrase"] = "WRONG_PHRASE"
        with patch.object(obs, "_write_audit"):
            handler = _make_handler(bad_body)
            obs.ObservationHandler._handle_token_register(handler)
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("APPROVAL_PHRASE_MISMATCH", body["error"])

    def test_tc03_non_beo_actor_denied(self):
        bad_body = dict(VALID_REGISTER_BODY)
        bad_body["actor"] = "caddy"
        with patch.object(obs, "_write_audit"):
            handler = _make_handler(bad_body)
            obs.ObservationHandler._handle_token_register(handler)
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("ACTOR_NOT_BEO", body["error"])

    def test_tc04_non_loopback_denied(self):
        with patch.object(obs, "_write_audit"):
            handler = _make_handler(VALID_REGISTER_BODY, client_ip="10.0.0.1")
            obs.ObservationHandler._handle_token_register(handler)
        status, body = handler.responses[0]
        self.assertEqual(status, 403)
        self.assertIn("LOOPBACK_ONLY", body["error"])

    def test_tc05_rotation_revokes_old_token(self):
        token_file = self.tmp / ".tokens"
        with patch.object(obs, "TOKEN_FILE", token_file), \
             patch.object(obs, "_write_audit"), \
             patch("secrets.token_urlsafe", return_value="first_token"):
            handler = _make_handler(VALID_REGISTER_BODY)
            obs.ObservationHandler._handle_token_register(handler)
        with obs._token_lock:
            self.assertFalse(obs._token_store["domi"]["revoked"])
        with patch.object(obs, "TOKEN_FILE", token_file), \
             patch.object(obs, "_write_audit"), \
             patch("secrets.token_urlsafe", return_value="second_token"):
            handler2 = _make_handler(VALID_REGISTER_BODY)
            obs.ObservationHandler._handle_token_register(handler2)
        status, body = handler2.responses[0]
        self.assertEqual(status, 200)
        self.assertEqual(body["token"], "second_token")
        new_hash = obs._sha256_hex("second_token")
        with obs._token_lock:
            self.assertEqual(obs._token_store["domi"]["hash"], new_hash)
            self.assertFalse(obs._token_store["domi"]["revoked"])

    def test_tc06_token_file_load_activates_valid_entries(self):
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        future = (datetime.now(KST).timestamp() + 3600)
        future_iso = datetime.fromtimestamp(future, tz=KST).isoformat()
        token_file = self.tmp / ".tokens"
        token_file.write_text(json.dumps({
            "domi": {"token_hash": obs._sha256_hex("valid_token"),
                     "issued_at": datetime.now(KST).isoformat(),
                     "expires_at": future_iso, "ttl_seconds": 43200, "revoked": False},
            "jeni": {"token_hash": obs._sha256_hex("revoked_token"),
                     "issued_at": datetime.now(KST).isoformat(),
                     "expires_at": future_iso, "ttl_seconds": 43200, "revoked": True},
        }))
        _reset_token_store()
        with patch.object(obs, "TOKEN_FILE", token_file):
            obs._load_token_file()
        with obs._token_lock:
            self.assertIn("domi", obs._token_store)
            self.assertNotIn("jeni", obs._token_store)
        valid, reason = obs.validate_token("domi", "valid_token")
        self.assertTrue(valid)
        self.assertEqual(reason, "OK")

    def test_tc07_expired_token_filtered_on_load(self):
        from datetime import datetime, timezone, timedelta
        KST = timezone(timedelta(hours=9))
        past_iso = datetime.fromtimestamp(
            datetime.now(KST).timestamp() - 3600, tz=KST
        ).isoformat()
        token_file = self.tmp / ".tokens"
        token_file.write_text(json.dumps({
            "domi": {"token_hash": obs._sha256_hex("expired_token"),
                     "issued_at": past_iso, "expires_at": past_iso,
                     "ttl_seconds": 43200, "revoked": False},
        }))
        _reset_token_store()
        with patch.object(obs, "TOKEN_FILE", token_file):
            obs._load_token_file()
        with obs._token_lock:
            self.assertNotIn("domi", obs._token_store)

    def test_tc08_raw_token_not_in_audit(self):
        token_file = self.tmp / ".tokens"
        audit_records = []
        def fake_write_audit(**kwargs):
            audit_records.append(kwargs)
        with patch.object(obs, "TOKEN_FILE", token_file), \
             patch.object(obs, "_write_audit", side_effect=fake_write_audit), \
             patch("secrets.token_urlsafe", return_value="super_secret_raw_token"):
            handler = _make_handler(VALID_REGISTER_BODY)
            obs.ObservationHandler._handle_token_register(handler)
        for record in audit_records:
            record_str = json.dumps(record)
            self.assertNotIn("super_secret_raw_token", record_str)
        token_hash_entries = [r.get("token_hash") for r in audit_records if r.get("token_hash")]
        self.assertTrue(any(e != "N/A" for e in token_hash_entries))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
test_mcp_write_server_finalize.py — PT-S141-MCP-WRITE-FINALIZE-001
sys.modules 전역 mock 제거 — unittest.mock.patch 격리 방식으로 재작성
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# sys.path만 추가 (sys.modules 변조 금지)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools", "mcp"))

import mcp_write_server as srv
from mcp_write_gatekeeper import WritePlaneState


# ── 헬퍼 ─────────────────────────────────────────────────────────────

def make_receipt(tmpdir, receipt_id, status="PENDING_BEO_REVIEW", age_seconds=0):
    created_at = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    receipt = {
        "schema": "MCP_WRITE_RESULT_RECEIPT_v1",
        "receipt_id": receipt_id,
        "created_at": created_at,
        "status": status,
        "actor": "caddy",
    }
    path = os.path.join(tmpdir, f"{receipt_id}.json")
    with open(path, "w") as f:
        json.dump(receipt, f)
    return path


def make_mock_gk(state: WritePlaneState):
    gk = MagicMock()
    gk.get_state.return_value = state
    return gk


# ── 테스트 클래스 ─────────────────────────────────────────────────────

class TestReceiptFinalize(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_receipts_dir = srv.RECEIPTS_DIR
        srv.RECEIPTS_DIR = self.tmpdir

    def tearDown(self):
        srv.RECEIPTS_DIR = self._orig_receipts_dir

    def _run(self, state, receipt_id, target_state):
        gk = make_mock_gk(state)
        with patch("mcp_write_server.get_gatekeeper", return_value=gk):
            return srv.handle_receipt_finalize(receipt_id, target_state)

    # T-1: RECOVERY_MODE 아닐 때 거부 (LOCKED)
    def test_T1_not_recovery_mode_deny(self):
        status, body = self._run(WritePlaneState.LOCKED, "R-001", "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("RECOVERY_MODE", body["error"])

    # T-2: NORMAL 상태 거부
    def test_T2_normal_state_deny(self):
        status, body = self._run(WritePlaneState.NORMAL, "R-001", "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    # T-3: 잘못된 target_state 거부
    def test_T3_invalid_target_state(self):
        make_receipt(self.tmpdir, "R-003")
        status, body = self._run(WritePlaneState.RECOVERY_MODE, "R-003", "APPROVED")
        self.assertEqual(status, 400)
        self.assertIn("target_state", body["error"])

    # T-4: 존재하지 않는 receipt 거부
    def test_T4_receipt_not_found(self):
        status, body = self._run(WritePlaneState.RECOVERY_MODE, "NONEXISTENT", "CONFIRMED")
        self.assertEqual(status, 404)

    # T-5: PENDING → CONFIRMED 정상 전이
    def test_T5_pending_to_confirmed(self):
        rid = "MCP-WRITE-RECEIPT-AAAA"
        make_receipt(self.tmpdir, rid)
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "CONFIRMED")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["current_status"], "CONFIRMED")
        self.assertFalse(body["ttl_expired"])
        with open(os.path.join(self.tmpdir, f"{rid}.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], "CONFIRMED")
        self.assertEqual(saved["finalized_by"], "Beo")

    # T-6: PENDING → REJECTED 정상 전이
    def test_T6_pending_to_rejected(self):
        rid = "MCP-WRITE-RECEIPT-BBBB"
        make_receipt(self.tmpdir, rid)
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "REJECTED")
        self.assertEqual(status, 200)
        self.assertEqual(body["current_status"], "REJECTED")

    # T-7: terminal immutability — CONFIRMED 재전이 거부
    def test_T7_terminal_immutability_confirmed(self):
        rid = "MCP-WRITE-RECEIPT-CCCC"
        make_receipt(self.tmpdir, rid, status="CONFIRMED")
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "REJECTED")
        self.assertEqual(status, 400)
        self.assertIn("terminal", body["error"])

    # T-8: terminal immutability — REJECTED 재전이 거부
    def test_T8_terminal_immutability_rejected(self):
        rid = "MCP-WRITE-RECEIPT-DDDD"
        make_receipt(self.tmpdir, rid, status="REJECTED")
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "CONFIRMED")
        self.assertEqual(status, 400)

    # T-9: terminal immutability — EXPIRED 재전이 거부
    def test_T9_terminal_immutability_expired(self):
        rid = "MCP-WRITE-RECEIPT-EEEE"
        make_receipt(self.tmpdir, rid, status="EXPIRED")
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "CONFIRMED")
        self.assertEqual(status, 400)

    # T-10: TTL 초과 → EXPIRED 강제
    def test_T10_ttl_expired_override(self):
        rid = "MCP-WRITE-RECEIPT-FFFF"
        make_receipt(self.tmpdir, rid, age_seconds=700)
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "CONFIRMED")
        self.assertEqual(status, 200)
        self.assertEqual(body["current_status"], "EXPIRED")
        self.assertTrue(body["ttl_expired"])

    # T-11: TTL 미초과 → 요청 target_state 유지
    def test_T11_ttl_not_expired(self):
        rid = "MCP-WRITE-RECEIPT-GGGG"
        make_receipt(self.tmpdir, rid, age_seconds=100)
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "REJECTED")
        self.assertEqual(status, 200)
        self.assertEqual(body["current_status"], "REJECTED")
        self.assertFalse(body["ttl_expired"])

    # T-12: UNKNOWN status receipt 거부
    def test_T12_unknown_status_deny(self):
        rid = "MCP-WRITE-RECEIPT-HHHH"
        make_receipt(self.tmpdir, rid, status="PROCESSING")
        status, body = self._run(WritePlaneState.RECOVERY_MODE, rid, "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertIn("PENDING_BEO_REVIEW", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

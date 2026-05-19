"""
test_mcp_recovery_enter_normal.py — PT-S141-MCP-WRITE-FINALIZE-001
sys.modules 전역 mock 제거 — unittest.mock.patch 격리 방식으로 재작성
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# sys.path만 추가 (sys.modules 변조 금지)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "tools", "mcp"))

import mcp_write_server as srv
from mcp_write_gatekeeper import WritePlaneState, MCP_WriteGatekeeper


# ── 헬퍼 ─────────────────────────────────────────────────────────────

def make_receipt(tmpdir, receipt_id, status="PENDING_BEO_REVIEW"):
    receipt = {
        "receipt_id": receipt_id,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(tmpdir, f"{receipt_id}.json"), "w") as f:
        json.dump(receipt, f)


def make_mock_gk(state: WritePlaneState, enter_side_effect=None):
    gk = MagicMock()
    gk.get_state.return_value = state
    if enter_side_effect:
        gk.beo_enter_recovery_mode.side_effect = enter_side_effect
    else:
        gk.beo_enter_recovery_mode.return_value = (
            "STALE_PENDING_RECEIPT_RECOVERY"
            if state == WritePlaneState.NORMAL else "FAULT_RECOVERY"
        )
    return gk


# ── Server 레이어 테스트 ──────────────────────────────────────────────

class TestRecoveryEnterNormal(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._orig_receipts_dir = srv.RECEIPTS_DIR
        srv.RECEIPTS_DIR = self.tmpdir

    def tearDown(self):
        srv.RECEIPTS_DIR = self._orig_receipts_dir

    def _run_enter(self, state, enter_side_effect=None):
        gk = make_mock_gk(state, enter_side_effect)
        with patch("mcp_write_server.get_gatekeeper", return_value=gk):
            return srv.handle_recovery_enter(), gk

    # N-1: NORMAL + PENDING 존재 → RECOVERY_MODE 진입
    def test_N1_normal_with_pending_allows_entry(self):
        make_receipt(self.tmpdir, "MCP-WRITE-RECEIPT-AAAA")
        (status, body), gk = self._run_enter(WritePlaneState.NORMAL)
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["entry_reason"], "STALE_PENDING_RECEIPT_RECOVERY")
        self.assertEqual(body["pending_receipt_count"], 1)
        gk.beo_enter_recovery_mode.assert_called_once_with(pending_count=1)

    # N-2: NORMAL + PENDING 없음 → DENY
    def test_N2_normal_no_pending_denied(self):
        (status, body), _ = self._run_enter(WritePlaneState.NORMAL)
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("PENDING", body["error"])

    # N-3: NORMAL + PENDING 복수 → count 전달
    def test_N3_normal_multiple_pending(self):
        make_receipt(self.tmpdir, "MCP-WRITE-RECEIPT-BBBB")
        make_receipt(self.tmpdir, "MCP-WRITE-RECEIPT-CCCC")
        (status, body), gk = self._run_enter(WritePlaneState.NORMAL)
        self.assertEqual(status, 200)
        self.assertEqual(body["pending_receipt_count"], 2)
        gk.beo_enter_recovery_mode.assert_called_once_with(pending_count=2)

    # N-4: NORMAL + scan 실패 → FAIL_CLOSED
    def test_N4_normal_scan_failure_failclosed(self):
        gk = make_mock_gk(WritePlaneState.NORMAL)
        with patch("mcp_write_server.get_gatekeeper", return_value=gk), \
             patch("mcp_write_server._find_pending_receipts",
                   return_value=(None, "scan error")):
            status, body = srv.handle_recovery_enter()
        self.assertEqual(status, 500)
        self.assertIn("FAIL-CLOSED", body["error"])

    # N-5: LOCKED → RECOVERY_MODE (기존 경로 무변경)
    def test_N5_locked_entry_unchanged(self):
        (status, body), gk = self._run_enter(WritePlaneState.LOCKED)
        self.assertEqual(status, 200)
        self.assertEqual(body["entry_reason"], "FAULT_RECOVERY")
        self.assertNotIn("pending_receipt_count", body)
        gk.beo_enter_recovery_mode.assert_called_once_with(pending_count=0)

    # N-6: HOLD → RECOVERY_MODE (기존 경로 무변경)
    def test_N6_hold_entry_unchanged(self):
        (status, body), gk = self._run_enter(WritePlaneState.HOLD)
        self.assertEqual(status, 200)
        self.assertEqual(body["entry_reason"], "FAULT_RECOVERY")

    # N-7: gatekeeper ValueError 전파
    def test_N7_gatekeeper_deny_propagated(self):
        make_receipt(self.tmpdir, "MCP-WRITE-RECEIPT-DDDD")
        (status, body), _ = self._run_enter(
            WritePlaneState.NORMAL,
            enter_side_effect=ValueError("NORMAL → RECOVERY_MODE 불가")
        )
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    # N-8: entry_reason 항상 포함
    def test_N8_entry_reason_in_response(self):
        make_receipt(self.tmpdir, "MCP-WRITE-RECEIPT-EEEE")
        (status, body), _ = self._run_enter(WritePlaneState.NORMAL)
        self.assertEqual(status, 200)
        self.assertIn("entry_reason", body)


# ── Gatekeeper 직접 테스트 ────────────────────────────────────────────

class TestGatekeeperEnterRecovery(unittest.TestCase):

    def _make_gk(self):
        return MCP_WriteGatekeeper(
            allowed_paths=["/tmp/sandbox/"],
            forbidden_prefixes=[],
            approvals_dir="/tmp/approvals",
            audit_dir="/tmp/audit",
            snapshots_dir="/tmp/snapshots",
            receipts_dir="/tmp/receipts",
            baselines_dir="/tmp/baselines",
        )

    # G-1: NORMAL + pending > 0 → RECOVERY_MODE
    def test_G1_normal_pending_allows(self):
        gk = self._make_gk()
        reason = gk.beo_enter_recovery_mode(pending_count=2)
        self.assertEqual(reason, "STALE_PENDING_RECEIPT_RECOVERY")
        self.assertEqual(gk.get_state(), WritePlaneState.RECOVERY_MODE)

    # G-2: NORMAL + pending == 0 → ValueError
    def test_G2_normal_no_pending_raises(self):
        gk = self._make_gk()
        with self.assertRaises(ValueError):
            gk.beo_enter_recovery_mode(pending_count=0)

    # G-3: LOCKED → RECOVERY_MODE + FAULT_RECOVERY
    def test_G3_locked_entry(self):
        gk = self._make_gk()
        gk._state = WritePlaneState.LOCKED
        reason = gk.beo_enter_recovery_mode(pending_count=0)
        self.assertEqual(reason, "FAULT_RECOVERY")
        self.assertEqual(gk.get_state(), WritePlaneState.RECOVERY_MODE)

    # G-4: HOLD → RECOVERY_MODE + FAULT_RECOVERY
    def test_G4_hold_entry(self):
        gk = self._make_gk()
        gk._state = WritePlaneState.HOLD
        reason = gk.beo_enter_recovery_mode(pending_count=0)
        self.assertEqual(reason, "FAULT_RECOVERY")

    # G-5: RECOVERY_MODE 재진입 → ValueError
    def test_G5_recovery_mode_raises(self):
        gk = self._make_gk()
        gk._state = WritePlaneState.RECOVERY_MODE
        with self.assertRaises(ValueError):
            gk.beo_enter_recovery_mode(pending_count=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)

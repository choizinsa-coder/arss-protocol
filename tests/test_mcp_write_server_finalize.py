"""
test_mcp_write_server_finalize.py — PT-S141-MCP-WRITE-FINALIZE-001 테스트
mcp_write_server.py v2.2.0 /internal/receipt/finalize 검증
"""

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# mcp_write_config, mcp_write_gatekeeper mock 선행 등록
import types

# ── 최소 mock 모듈 ────────────────────────────────────────────────────
mock_config = types.ModuleType("mcp_write_config")
mock_config.RECEIPTS_DIR = None  # 테스트별 tmpdir로 교체
mock_config.TOKEN_TTL = 600
mock_config.SOFT_TOKEN_TTL = 480
mock_config.APPROVALS_DIR = "/tmp/approvals"
mock_config.AUDIT_DIR = "/tmp/audit"
mock_config.SNAPSHOTS_DIR = "/tmp/snapshots"
mock_config.BASELINES_DIR = "/tmp/baselines"
mock_config.INTAKE_DIR = "/tmp/intake"
mock_config.ALLOWED_SANDBOX_PATHS = ["/tmp/sandbox/"]
mock_config.FORBIDDEN_PATH_PREFIXES = []
mock_config.ALLOWED_EXTENSIONS = {".md", ".json", ".txt"}
mock_config.FORBIDDEN_EXTENSIONS = {".py", ".sh"}
mock_config.HASH_ALGORITHM = "sha256"
sys.modules["mcp_write_config"] = mock_config

from enum import Enum

class WritePlaneState(Enum):
    NORMAL = "NORMAL"
    HOLD = "HOLD"
    LOCKED = "LOCKED"
    RECOVERY_MODE = "RECOVERY_MODE"

class FailClosedError(Exception):
    def __init__(self, tier, reason):
        self.tier = tier
        self.reason = reason
        super().__init__(f"FC-{tier}: {reason}")

mock_gatekeeper_mod = types.ModuleType("mcp_write_gatekeeper")
mock_gatekeeper_mod.WritePlaneState = WritePlaneState
mock_gatekeeper_mod.FailClosedError = FailClosedError
mock_gatekeeper_mod.get_gatekeeper = MagicMock()
sys.modules["mcp_write_gatekeeper"] = mock_gatekeeper_mod

import importlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..","tools","mcp"))
import mcp_write_server as srv

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


def make_gk_mock(state: WritePlaneState):
    gk = MagicMock()
    gk.get_state.return_value = state
    mock_gatekeeper_mod.get_gatekeeper.return_value = gk
    return gk


# ── 테스트 클래스 ─────────────────────────────────────────────────────

class TestReceiptFinalize(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        mock_config.RECEIPTS_DIR = self.tmpdir
        srv.RECEIPTS_DIR = self.tmpdir

    # T-1: RECOVERY_MODE 아닐 때 거부
    def test_T1_not_recovery_mode_deny(self):
        make_gk_mock(WritePlaneState.LOCKED)
        status, body = srv.handle_receipt_finalize("RECEIPT-001", "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("RECOVERY_MODE", body["error"])

    # T-2: NORMAL 상태에서도 거부
    def test_T2_normal_state_deny(self):
        make_gk_mock(WritePlaneState.NORMAL)
        status, body = srv.handle_receipt_finalize("RECEIPT-001", "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    # T-3: 잘못된 target_state 거부
    def test_T3_invalid_target_state(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        status, body = srv.handle_receipt_finalize("RECEIPT-001", "APPROVED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("target_state", body["error"])

    # T-4: 존재하지 않는 receipt_id 거부
    def test_T4_receipt_not_found(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        status, body = srv.handle_receipt_finalize("NONEXISTENT-RECEIPT", "CONFIRMED")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    # T-5: PENDING → CONFIRMED 정상 전이
    def test_T5_pending_to_confirmed(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-AAAA"
        make_receipt(self.tmpdir, rid)
        status, body = srv.handle_receipt_finalize(rid, "CONFIRMED")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["previous_status"], "PENDING_BEO_REVIEW")
        self.assertEqual(body["current_status"], "CONFIRMED")
        self.assertFalse(body["ttl_expired"])
        # 파일 확인
        with open(os.path.join(self.tmpdir, f"{rid}.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], "CONFIRMED")
        self.assertEqual(saved["finalized_by"], "Beo")
        self.assertEqual(saved["finalize_requested_target"], "CONFIRMED")

    # T-6: PENDING → REJECTED 정상 전이
    def test_T6_pending_to_rejected(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-BBBB"
        make_receipt(self.tmpdir, rid)
        status, body = srv.handle_receipt_finalize(rid, "REJECTED")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["current_status"], "REJECTED")

    # T-7: terminal immutability — CONFIRMED 재전이 거부
    def test_T7_terminal_immutability_confirmed(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-CCCC"
        make_receipt(self.tmpdir, rid, status="CONFIRMED")
        status, body = srv.handle_receipt_finalize(rid, "REJECTED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("terminal", body["error"])

    # T-8: terminal immutability — REJECTED 재전이 거부
    def test_T8_terminal_immutability_rejected(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-DDDD"
        make_receipt(self.tmpdir, rid, status="REJECTED")
        status, body = srv.handle_receipt_finalize(rid, "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    # T-9: terminal immutability — EXPIRED 재전이 거부
    def test_T9_terminal_immutability_expired(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-EEEE"
        make_receipt(self.tmpdir, rid, status="EXPIRED")
        status, body = srv.handle_receipt_finalize(rid, "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    # T-10: GAP-1 — TTL 초과 시 EXPIRED 강제 (CONFIRMED 요청해도)
    def test_T10_ttl_expired_override(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-FFFF"
        make_receipt(self.tmpdir, rid, age_seconds=700)  # TOKEN_TTL=600 초과
        status, body = srv.handle_receipt_finalize(rid, "CONFIRMED")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["current_status"], "EXPIRED")
        self.assertTrue(body["ttl_expired"])
        # 파일: finalize_requested_target 보존
        with open(os.path.join(self.tmpdir, f"{rid}.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved["status"], "EXPIRED")
        self.assertEqual(saved["finalize_requested_target"], "CONFIRMED")

    # T-11: GAP-1 — TTL 미초과 시 요청 target_state 유지
    def test_T11_ttl_not_expired(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-GGGG"
        make_receipt(self.tmpdir, rid, age_seconds=100)  # 100초 — TTL 미초과
        status, body = srv.handle_receipt_finalize(rid, "REJECTED")
        self.assertEqual(status, 200)
        self.assertEqual(body["current_status"], "REJECTED")
        self.assertFalse(body["ttl_expired"])

    # T-12: UNKNOWN status receipt 거부
    def test_T12_unknown_status_deny(self):
        make_gk_mock(WritePlaneState.RECOVERY_MODE)
        rid = "MCP-WRITE-RECEIPT-HHHH"
        make_receipt(self.tmpdir, rid, status="PROCESSING")
        status, body = srv.handle_receipt_finalize(rid, "CONFIRMED")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("PENDING_BEO_REVIEW", body["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
test_p4t2.py
P4-T2: binding_guard + receiver_receipt 단위 테스트
EAG-2 Approved (비오(Joshua), S172)
P4-C1 패치 (S174): Layer E failure path 보강 (E4, E5) + Layer A RULE-8_NOT_APPLICABLE 처리

테스트 구조:
  Layer A: binding_guard 상태 조회 (3) — RULE-8_NOT_APPLICABLE (순수 상태 조회 R0급)
  Layer B: binding_guard probe 로직 (3)
  Layer C: binding_guard 전체 검증 (3)
  Layer D: receiver_receipt 생성 (3)
  Layer E: receiver_receipt 저장 (5) ← P4-C1: E4/E5 failure path 추가
  Layer F: 통합 — 차단 흐름 (3)
  Total: 20
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import urllib.error

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.transport.binding_guard import (
    EndpointBindingResult,
    BindingGuardResult,
    BINDING_STATUS_MATCH,
    BINDING_STATUS_MISMATCH,
    BINDING_STATUS_UNKNOWN,
    check_single_binding,
    validate_all_bindings,
    is_endpoint_sendable,
    get_binding_guard_status,
    _probe_endpoint,
    _now_kst,
)
from tools.sync_layer.transport.receiver_receipt import (
    RECEIPT_TYPE,
    RECEIPT_VERSION,
    RESULT_ACCEPTED,
    RESULT_REJECTED,
    BINDING_MATCH,
    BINDING_MISMATCH,
    SCHEMA_PASS,
    SCHEMA_FAIL,
    create_receiver_receipt,
    save_receiver_receipt,
    create_and_save_receipt,
    get_receipt_store_status,
)

# ── 공통 픽스처 ─────────────────────────────────────────────────────────────

MOCK_ENDPOINTS = {
    "version": "TRANSPORT_REGISTRY_v1",
    "endpoints": {
        "aiba-deployment": {
            "url": "http://localhost:5678/webhook/aiba-deployment",
            "active": True,
            "workflow": "WF-T1",
        },
        "aiba-sync": {
            "url": "http://localhost:5678/webhook/aiba-sync",
            "active": True,
            "workflow": "WF-T2",
        },
    },
}

MOCK_INACTIVE_ENDPOINTS = {
    "version": "TRANSPORT_REGISTRY_v1",
    "endpoints": {
        "aiba-deployment": {
            "url": "http://localhost:5678/webhook/aiba-deployment",
            "active": False,
            "workflow": "WF-T1",
        },
    },
}


# ── Layer A: binding_guard 상태 조회 ────────────────────────────────────────
# RULE-8_NOT_APPLICABLE: 순수 상태 딕셔너리 반환 함수 (R0급).
# 부작용 없음 / 외부 I/O 없음 / 상태 변경 없음.
# failure path assertion 대상 아님 (P4-C1 S174 확정).

class TestLayerA_BindingGuardStatus(unittest.TestCase):

    def test_A1_get_status_returns_dict(self):
        """get_binding_guard_status 반환 타입 확인"""
        status = get_binding_guard_status()
        self.assertIsInstance(status, dict)

    def test_A2_status_has_required_keys(self):
        """상태 딕셔너리 필수 키 확인"""
        status = get_binding_guard_status()
        for key in ["component", "layer", "p4_task", "fail_closed", "jeni_advisory"]:
            self.assertIn(key, status)

    def test_A3_fail_closed_true(self):
        """fail_closed 반드시 True"""
        status = get_binding_guard_status()
        self.assertTrue(status["fail_closed"])


# ── Layer B: binding_guard probe 로직 ───────────────────────────────────────

class TestLayerB_ProbeLogic(unittest.TestCase):

    def test_B1_probe_404_returns_mismatch(self):
        """404 응답 → MISMATCH"""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://test", code=404, msg="Not Found",
                hdrs=None, fp=None,
            )
            status, code, reason = _probe_endpoint("http://localhost:5678/webhook/test")
        self.assertEqual(status, BINDING_STATUS_MISMATCH)
        self.assertEqual(code, 404)

    def test_B2_probe_non404_httperror_returns_match(self):
        """404 외 HTTPError(500 등) → webhook 등록됨(처리 오류) → MATCH"""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="http://test", code=500, msg="Internal Server Error",
                hdrs=None, fp=None,
            )
            status, code, reason = _probe_endpoint("http://localhost:5678/webhook/test")
        self.assertEqual(status, BINDING_STATUS_MATCH)

    def test_B3_probe_connection_error_returns_unknown(self):
        """연결 오류 → UNKNOWN"""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("connection refused")
            status, code, reason = _probe_endpoint("http://localhost:5678/webhook/test")
        self.assertEqual(status, BINDING_STATUS_UNKNOWN)
        self.assertIsNone(code)


# ── Layer C: binding_guard 전체 검증 ────────────────────────────────────────

class TestLayerC_ValidateAll(unittest.TestCase):

    def test_C1_inactive_endpoint_returns_unknown(self):
        """inactive endpoint → UNKNOWN (전송 불가)"""
        with patch(
            "tools.sync_layer.transport.binding_guard._load_endpoints",
            return_value=MOCK_INACTIVE_ENDPOINTS,
        ):
            result = check_single_binding("aiba-deployment")
        self.assertFalse(result.active)
        self.assertEqual(result.binding_status, BINDING_STATUS_UNKNOWN)

    def test_C2_unknown_endpoint_id_returns_unknown(self):
        """존재하지 않는 endpoint_id → UNKNOWN"""
        with patch(
            "tools.sync_layer.transport.binding_guard._load_endpoints",
            return_value=MOCK_ENDPOINTS,
        ):
            result = check_single_binding("non-existent-endpoint")
        self.assertEqual(result.binding_status, BINDING_STATUS_UNKNOWN)
        self.assertEqual(result.failure_reason, "ENDPOINT_ID_NOT_FOUND")

    def test_C3_is_endpoint_sendable_mismatch_returns_false(self):
        """MISMATCH endpoint → is_endpoint_sendable = False (fail-closed)"""
        with patch(
            "tools.sync_layer.transport.binding_guard.check_single_binding",
            return_value=EndpointBindingResult(
                endpoint_id="aiba-deployment",
                url="http://localhost:5678/webhook/aiba-deployment",
                active=True,
                binding_status=BINDING_STATUS_MISMATCH,
                probe_http_status=404,
                failure_reason="WEBHOOK_NOT_REGISTERED",
                checked_at=_now_kst(),
            ),
        ):
            self.assertFalse(is_endpoint_sendable("aiba-deployment"))


# ── Layer D: receiver_receipt 생성 ──────────────────────────────────────────

class TestLayerD_ReceiptCreate(unittest.TestCase):

    def test_D1_create_receipt_returns_dict(self):
        """receipt 생성 반환 타입 확인"""
        receipt = create_receiver_receipt(
            receiver="WF-T1",
            event_type="DEPLOYMENT_EVENT",
            endpoint_id="aiba-deployment",
            binding_status=BINDING_MATCH,
            schema_status=SCHEMA_PASS,
            result=RESULT_ACCEPTED,
        )
        self.assertIsInstance(receipt, dict)

    def test_D2_receipt_required_fields(self):
        """9개 필수 필드 모두 존재"""
        receipt = create_receiver_receipt(
            receiver="WF-T2",
            event_type="SYNC_EVENT",
            endpoint_id="aiba-sync",
            binding_status=BINDING_MATCH,
            schema_status=SCHEMA_PASS,
            result=RESULT_ACCEPTED,
        )
        for field in [
            "receipt_id", "receipt_type", "receiver", "event_type",
            "endpoint_id", "binding_status", "schema_status",
            "received_at", "result",
        ]:
            self.assertIn(field, receipt)

    def test_D3_receipt_type_correct(self):
        """receipt_type = TRANSPORT_RECEIVER_RECEIPT"""
        receipt = create_receiver_receipt(
            receiver="WF-T1",
            event_type="DEPLOYMENT_EVENT",
            endpoint_id="aiba-deployment",
            binding_status=BINDING_MISMATCH,
            schema_status=SCHEMA_FAIL,
            result=RESULT_REJECTED,
            reason="BINDING_MISMATCH",
        )
        self.assertEqual(receipt["receipt_type"], RECEIPT_TYPE)
        self.assertEqual(receipt["result"], RESULT_REJECTED)


# ── Layer E: receiver_receipt 저장 ──────────────────────────────────────────

class TestLayerE_ReceiptSave(unittest.TestCase):

    def test_E1_save_receipt_success(self):
        """receipt 저장 성공 확인"""
        receipt = create_receiver_receipt(
            receiver="WF-T1",
            event_type="DEPLOYMENT_EVENT",
            endpoint_id="aiba-deployment",
            binding_status=BINDING_MATCH,
            schema_status=SCHEMA_PASS,
            result=RESULT_ACCEPTED,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "tools.sync_layer.transport.receiver_receipt.RECEIPT_DIR",
                Path(tmpdir),
            ):
                saved = save_receiver_receipt(receipt)
        self.assertTrue(saved)

    def test_E2_create_and_save_returns_tuple(self):
        """create_and_save_receipt 반환 타입 확인"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch(
                "tools.sync_layer.transport.receiver_receipt.RECEIPT_DIR",
                Path(tmpdir),
            ):
                receipt, saved = create_and_save_receipt(
                    receiver="WF-T2",
                    event_type="SYNC_EVENT",
                    endpoint_id="aiba-sync",
                    binding_status=BINDING_MATCH,
                    schema_status=SCHEMA_PASS,
                    result=RESULT_ACCEPTED,
                )
        self.assertIsInstance(receipt, dict)
        self.assertTrue(saved)

    def test_E3_get_receipt_store_status(self):
        """저장소 상태 조회 필수 키 확인"""
        status = get_receipt_store_status()
        for key in ["component", "p4_task", "receipt_type", "receipt_dir", "deploy_executor_coupling"]:
            self.assertIn(key, status)
        self.assertEqual(status["deploy_executor_coupling"], "NONE — 독립 타입")

    def test_E4_save_receipt_fsync_failure_returns_false(self):
        """_fsync_write 실패 → save_receiver_receipt False 반환 (RULE-8 failure path)"""
        receipt = create_receiver_receipt(
            receiver="WF-T1",
            event_type="DEPLOYMENT_EVENT",
            endpoint_id="aiba-deployment",
            binding_status=BINDING_MATCH,
            schema_status=SCHEMA_PASS,
            result=RESULT_ACCEPTED,
        )
        with patch(
            "tools.sync_layer.transport.receiver_receipt._fsync_write",
            return_value=False,
        ):
            saved = save_receiver_receipt(receipt)
        self.assertFalse(saved)

    def test_E5_create_and_save_fsync_failure_returns_false_tuple(self):
        """_fsync_write 실패 → create_and_save_receipt (receipt, False) 반환 (RULE-8 failure path)"""
        with patch(
            "tools.sync_layer.transport.receiver_receipt._fsync_write",
            return_value=False,
        ):
            receipt, saved = create_and_save_receipt(
                receiver="WF-T1",
                event_type="DEPLOYMENT_EVENT",
                endpoint_id="aiba-deployment",
                binding_status=BINDING_MATCH,
                schema_status=SCHEMA_PASS,
                result=RESULT_ACCEPTED,
            )
        self.assertIsInstance(receipt, dict)
        self.assertFalse(saved)


# ── Layer F: 통합 — 차단 흐름 ───────────────────────────────────────────────

class TestLayerF_BlockedFlow(unittest.TestCase):

    def test_F1_mismatch_binding_creates_rejected_receipt(self):
        """MISMATCH 바인딩 → REJECTED receipt 생성"""
        receipt = create_receiver_receipt(
            receiver="WF-T1",
            event_type="DEPLOYMENT_EVENT",
            endpoint_id="aiba-deployment",
            binding_status=BINDING_MISMATCH,
            schema_status=SCHEMA_FAIL,
            result=RESULT_REJECTED,
            reason="BINDING_MISMATCH",
        )
        self.assertEqual(receipt["binding_status"], BINDING_MISMATCH)
        self.assertEqual(receipt["result"], RESULT_REJECTED)

    def test_F2_validate_all_empty_endpoints_returns_not_all_match(self):
        """endpoints 비어있으면 all_match=False"""
        with patch(
            "tools.sync_layer.transport.binding_guard._load_endpoints",
            return_value={},
        ):
            result = validate_all_bindings()
        self.assertFalse(result.all_match)

    def test_F3_is_endpoint_sendable_unknown_returns_false(self):
        """UNKNOWN endpoint → is_endpoint_sendable = False (fail-closed)"""
        with patch(
            "tools.sync_layer.transport.binding_guard.check_single_binding",
            return_value=EndpointBindingResult(
                endpoint_id="aiba-deployment",
                url="",
                active=True,
                binding_status=BINDING_STATUS_UNKNOWN,
                probe_http_status=None,
                failure_reason="PROBE_ERROR: ConnectionError",
                checked_at=_now_kst(),
            ),
        ):
            self.assertFalse(is_endpoint_sendable("aiba-deployment"))


if __name__ == "__main__":
    unittest.main()

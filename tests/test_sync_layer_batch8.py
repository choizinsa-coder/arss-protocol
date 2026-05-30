"""
test_sync_layer_batch8.py
P4-C4 Phase-beta Batch-8: sync_layer transport/validator failure-path assertion 보강
EAG-1 승인: 비오(Joshua) S178
도미 Batch-8 설계: transport 7건 + validator 3건 = 10건
Rule-T2-1: failure-path assertion ≥ 1건 per assertion
"""

import sys
import json
import pytest
from pathlib import Path
from unittest import mock
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.transport import transport_contract, transport_client
from tools.sync_layer.transport.transport_types import RESULT_ABORTED, RESULT_SUCCESS
from tools.sync_layer.validator import receipt_validator, consistency_validator, validation_runner


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def bypass_caller(monkeypatch):
    monkeypatch.setattr(
        "tools.sync_layer.transport.transport_client._enforce_allowed_caller",
        lambda: None,
    )

@pytest.fixture
def mock_endpoint(monkeypatch):
    monkeypatch.setattr(
        "tools.sync_layer.transport.transport_client.get_active_endpoint",
        lambda event_type: "http://localhost:5678/webhook/test",
    )

@pytest.fixture
def dep_payload():
    return {
        "event_type": "DEPLOYMENT_EVENT",
        "deployment_id": "DEPLOY-178-20260530T000000Z-BATCH8",
        "approval_id": "EAG-1-S178",
        "artifact_hash": "a" * 64,
        "target": "SESSION_CONTEXT",
        "result": "SUCCESS",
        "timestamp": "2026-05-30T00:00:00+09:00",
        "session": 178,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Transport 계열 7건 (priority: fail-closed → propagation → receipt/state)
# ══════════════════════════════════════════════════════════════════════════════

class TestTransportBatch8:

    # TB-1: transport downstream failure fail-closed — OSError → ABORTED
    def test_TB1_downstream_oserror_fail_closed(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        """downstream OSError → ABORTED (fail-closed, NO RETRY)"""
        with mock.patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert result.failure_reason is not None
        assert "TRANSPORT_ERROR" in result.failure_reason

    # TB-2: transport receipt/state mismatch deny — HTTP 301 (비허용 상태코드)
    def test_TB2_unexpected_status_deny(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        """HTTP 301 (비허용) → ABORTED + UNEXPECTED_STATUS"""
        resp = MagicMock()
        resp.status = 301
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert "UNEXPECTED_STATUS" in result.failure_reason

    # TB-3: transport unknown status deny — HTTP 204 (비허용)
    def test_TB3_http_204_not_in_success_statuses(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        """HTTP 204 (성공 집합 외) → ABORTED"""
        resp = MagicMock()
        resp.status = 204
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with mock.patch("urllib.request.urlopen", return_value=resp):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert "UNEXPECTED_STATUS" in result.failure_reason

    # TB-4: transport failure propagation — failure_reason이 결과에 항상 포함
    def test_TB4_failure_reason_always_propagated(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        """실패 시 failure_reason이 TransportResult에 반드시 포함"""
        import urllib.error
        err = urllib.error.HTTPError("http://x", 503, "Service Unavailable", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert result.failure_reason is not None
        assert len(result.failure_reason) > 0

    # TB-5: transport payload validation — result 필드 ENUM 외 값 → PAYLOAD_INVALID
    def test_TB5_invalid_result_enum_deny(self, bypass_caller, mock_endpoint):
        """result 필드에 ENUM 외 값 → PAYLOAD_INVALID → ABORTED"""
        bad_payload = {
            "event_type": "DEPLOYMENT_EVENT",
            "deployment_id": "DEPLOY-178-BADENUM",
            "approval_id": "EAG-1",
            "artifact_hash": "a" * 64,
            "target": "SESSION_CONTEXT",
            "result": "UNKNOWN_INVALID_STATUS",  # ENUM 외
            "timestamp": "2026-05-30T00:00:00+09:00",
            "session": 178,
        }
        result = transport_client.send(bad_payload)
        assert result.status == RESULT_ABORTED
        assert "PAYLOAD_INVALID" in result.failure_reason

    # TB-6: transport missing field deny — session 필드 누락
    def test_TB6_missing_session_field_deny(self, bypass_caller, mock_endpoint):
        """session 필드 누락 → PAYLOAD_INVALID → ABORTED"""
        bad_payload = {
            "event_type": "DEPLOYMENT_EVENT",
            "deployment_id": "DEPLOY-178-NOSESSION",
            "approval_id": "EAG-1",
            "artifact_hash": "b" * 64,
            "target": "SESSION_CONTEXT",
            "result": "SUCCESS",
            "timestamp": "2026-05-30T00:00:00+09:00",
            # session 누락
        }
        result = transport_client.send(bad_payload)
        assert result.status == RESULT_ABORTED
        assert "PAYLOAD_INVALID" in result.failure_reason

    # TB-7: transport malformed input — dict가 아닌 list 입력 → 예외 발생 (fail-closed)
    def test_TB7_non_dict_payload_raises(self, bypass_caller, mock_endpoint):
        """list 입력 → transport_contract 내부 AttributeError (fail-closed)"""
        with pytest.raises(Exception):
            transport_client.send(["not", "a", "dict"])


# ══════════════════════════════════════════════════════════════════════════════
# Validator 계열 3건 (priority: evidence deny → mismatch fail-closed)
# ══════════════════════════════════════════════════════════════════════════════

class TestValidatorBatch8:

    # VB-1: validator missing evidence deny — artifact_hash 없음
    def test_VB1_missing_artifact_hash_deny(self, tmp_path):
        """artifact_hash 필드 없음 → R3_INVALID_ARTIFACT_HASH"""
        rd = tmp_path / "deployment_receipts"
        rd.mkdir()
        bad = {
            "deployment_id": "D-001",
            "deploy_type": "TIER1_EAG_DEPLOY",
            "actor": "deploy_executor",
            "approval_id": "EAG-1",
            "artifact_hash": "",  # 빈 문자열 → 무효
            "target": "SESSION_CONTEXT",
            "result": "SUCCESS",
            "timestamp": "2026-05-30T00:00:00+09:00",
            "request_id": "sync_orchestrator",
            "session": 178,
            "receipt_version": "DEPLOYMENT_RECEIPT_v1",
        }
        (rd / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        with patch.object(receipt_validator, "RECEIPT_DIR", rd):
            result = receipt_validator.validate()
        assert result["verdict"] == "FAIL"
        issues = result["details"][0]["issues"]
        assert any("R3_INVALID_ARTIFACT_HASH" in i for i in issues)

    # VB-2: validator invalid evidence deny — artifact_hash 비hex 문자 포함
    def test_VB2_invalid_artifact_hash_nonhex_deny(self, tmp_path):
        """artifact_hash에 비hex 문자 포함 → R3_INVALID_ARTIFACT_HASH"""
        rd = tmp_path / "deployment_receipts"
        rd.mkdir()
        bad = {
            "deployment_id": "D-002",
            "deploy_type": "TIER1_EAG_DEPLOY",
            "actor": "deploy_executor",
            "approval_id": "EAG-1",
            "artifact_hash": "z" * 64,  # 비hex
            "target": "SESSION_CONTEXT",
            "result": "SUCCESS",
            "timestamp": "2026-05-30T00:00:00+09:00",
            "request_id": "sync_orchestrator",
            "session": 178,
            "receipt_version": "DEPLOYMENT_RECEIPT_v1",
        }
        (rd / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        with patch.object(receipt_validator, "RECEIPT_DIR", rd):
            result = receipt_validator.validate()
        assert result["verdict"] == "FAIL"
        issues = result["details"][0]["issues"]
        assert any("R3_INVALID_ARTIFACT_HASH" in i for i in issues)

    # VB-3: validator mismatch fail-closed — overall FAIL propagation
    def test_VB3_fail_propagates_to_overall(self):
        """validator 1건 FAIL → overall_verdict FAIL (fail-closed 전파)"""
        def _fail():
            return {"validator": "receipt", "verdict": "FAIL", "details": [{"e": "x"}]}
        def _pass(name):
            return lambda: {"validator": name, "verdict": "PASS"}

        with patch.object(receipt_validator, "validate", _fail), \
             patch.object(consistency_validator, "validate", _pass("consistency")), \
             patch.object(
                 __import__("tools.sync_layer.validator.transport_validator",
                             fromlist=["transport_validator"]),
                 "validate", _pass("transport")
             ), \
             patch.object(
                 __import__("tools.sync_layer.validator.fallback_validator",
                             fromlist=["fallback_validator"]),
                 "validate", _pass("fallback")
             ):
            report = validation_runner.run_all()
        assert report["overall_verdict"] == "FAIL"


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])

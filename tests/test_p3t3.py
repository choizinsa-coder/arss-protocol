"""
test_p3t3.py
P3-T3 n8n Transport Layer Tests — Layer A (Schema) + Layer B (Mock Endpoint)
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

Layer A: transport_contract 스키마 검증 (11개)
Layer B: transport_client HTTP Mock 검증 (10개)
Enforcement: Allowed Caller 강제 차단 검증 (1개)
합계: 22개
"""

import sys
import pytest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.transport import transport_contract, transport_client
from tools.sync_layer.transport.transport_types import (
    TransportResult,
    RESULT_SUCCESS,
    RESULT_ABORTED,
    EVENT_TYPE_DEPLOYMENT,
    EVENT_TYPE_SYNC,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def dep_payload():
    return {
        "event_type": "DEPLOYMENT_EVENT",
        "deployment_id": "DEPLOY-169-20260529T100000Z-ABCDEF",
        "approval_id": "EAG-1-S169",
        "artifact_hash": "a" * 64,
        "target": "SESSION_CONTEXT",
        "result": "SUCCESS",
        "timestamp": "2026-05-29T10:00:00+09:00",
        "session": 169,
    }


@pytest.fixture
def sync_payload():
    return {
        "event_type": "SYNC_EVENT",
        "event_id": "SYNC-169-001",
        "source": "sync_orchestrator",
        "payload_hash": "b" * 64,
        "timestamp": "2026-05-29T10:00:00+09:00",
        "session": 169,
    }


def _mock_urlopen(status=200):
    """urlopen context manager mock 생성 헬퍼."""
    resp = mock.MagicMock()
    resp.status = status
    resp.__enter__ = lambda s: s
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# Layer A — Schema Tests (transport_contract)
# ══════════════════════════════════════════════════════════════════════════════

class TestTransportContract:

    # A-01
    def test_valid_deployment_event_passes(self, dep_payload):
        valid, err = transport_contract.validate_payload(dep_payload)
        assert valid is True
        assert err == ""

    # A-02
    def test_valid_sync_event_passes(self, sync_payload):
        valid, err = transport_contract.validate_payload(sync_payload)
        assert valid is True
        assert err == ""

    # A-03
    def test_deployment_missing_field_fails(self, dep_payload):
        del dep_payload["approval_id"]
        valid, err = transport_contract.validate_payload(dep_payload)
        assert valid is False
        assert "MISSING_FIELDS" in err

    # A-04
    def test_deployment_invalid_result_enum_fails(self, dep_payload):
        dep_payload["result"] = "INVALID_STATUS"
        valid, err = transport_contract.validate_payload(dep_payload)
        assert valid is False
        assert "INVALID_RESULT" in err

    # A-05
    def test_sync_missing_field_fails(self, sync_payload):
        del sync_payload["source"]
        valid, err = transport_contract.validate_payload(sync_payload)
        assert valid is False
        assert "MISSING_FIELDS" in err

    # A-06
    def test_unknown_event_type_fails(self):
        payload = {"event_type": "UNKNOWN_EVENT"}
        valid, err = transport_contract.validate_payload(payload)
        assert valid is False
        assert "INVALID_EVENT_TYPE" in err

    # A-07
    def test_empty_payload_fails(self):
        valid, err = transport_contract.validate_payload({})
        assert valid is False
        assert "EMPTY_OR_INVALID_PAYLOAD" in err

    # A-08
    def test_none_payload_fails(self):
        valid, err = transport_contract.validate_payload(None)
        assert valid is False

    # A-09
    def test_extra_fields_tolerated(self, dep_payload):
        dep_payload["extra_field"] = "extra_value"
        valid, err = transport_contract.validate_payload(dep_payload)
        assert valid is True

    # A-10
    def test_payload_hash_is_deterministic_and_64chars(self, dep_payload):
        h1 = transport_contract.compute_payload_hash(dep_payload)
        h2 = transport_contract.compute_payload_hash(dep_payload)
        assert h1 == h2
        assert len(h1) == 64

    # A-11
    def test_extract_event_id_deployment_and_sync(self, dep_payload, sync_payload):
        assert transport_contract.extract_event_id(dep_payload) == dep_payload["deployment_id"]
        assert transport_contract.extract_event_id(sync_payload) == sync_payload["event_id"]


# ══════════════════════════════════════════════════════════════════════════════
# Layer B — Mock Endpoint Tests (transport_client)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=False)
def bypass_caller(monkeypatch):
    """테스트 환경: Allowed Caller 검증 bypass용 fixture (명시 적용)."""
    monkeypatch.setattr(
        "tools.sync_layer.transport.transport_client._enforce_allowed_caller",
        lambda: None,
    )


@pytest.fixture(autouse=False)
def mock_endpoint(monkeypatch):
    """transport_registry.get_active_endpoint mock."""
    monkeypatch.setattr(
        "tools.sync_layer.transport.transport_client.get_active_endpoint",
        lambda event_type: "http://localhost:5678/webhook/test",
    )


class TestTransportClient:

    # B-01
    def test_send_http_200_returns_success(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(200)):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_SUCCESS
        assert result.failure_reason is None

    # B-02
    def test_send_http_202_returns_success(
        self, sync_payload, bypass_caller, mock_endpoint
    ):
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(202)):
            result = transport_client.send(sync_payload)
        assert result.status == RESULT_SUCCESS

    # B-03
    def test_send_http_500_returns_aborted(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        import urllib.error
        err = urllib.error.HTTPError("http://x", 500, "Server Error", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert "HTTP_ERROR: 500" in result.failure_reason

    # B-04
    def test_send_http_400_returns_aborted(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        import urllib.error
        err = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED

    # B-05
    def test_send_timeout_returns_aborted(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert "TRANSPORT_ERROR" in result.failure_reason

    # B-06
    def test_send_connection_refused_returns_aborted(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        import urllib.error
        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED

    # B-07
    def test_send_endpoint_not_found_returns_aborted(
        self, dep_payload, bypass_caller, monkeypatch
    ):
        monkeypatch.setattr(
            "tools.sync_layer.transport.transport_client.get_active_endpoint",
            lambda _: None,
        )
        result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        assert "ENDPOINT_NOT_FOUND" in result.failure_reason

    # B-08
    def test_send_invalid_payload_returns_aborted(self, bypass_caller, mock_endpoint):
        invalid = {"event_type": "DEPLOYMENT_EVENT"}  # 필드 누락
        result = transport_client.send(invalid)
        assert result.status == RESULT_ABORTED
        assert "PAYLOAD_INVALID" in result.failure_reason

    # B-09
    def test_transport_result_fields_complete(
        self, dep_payload, bypass_caller, mock_endpoint
    ):
        with mock.patch("urllib.request.urlopen", return_value=_mock_urlopen(200)):
            result = transport_client.send(dep_payload)
        assert result.event_type == EVENT_TYPE_DEPLOYMENT
        assert result.event_id == dep_payload["deployment_id"]
        assert len(result.payload_hash) == 64
        assert result.session == 169
        assert result.endpoint == "http://localhost:5678/webhook/test"

    # B-10
    def test_failure_record_written_on_transport_error(
        self, dep_payload, bypass_caller, mock_endpoint, tmp_path
    ):
        import urllib.error
        with mock.patch(
            "tools.sync_layer.transport.transport_notification.FAILURE_RECORD_DIR",
            tmp_path / "transport_failures",
        ):
            with mock.patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("err"),
            ):
                result = transport_client.send(dep_payload)
        assert result.status == RESULT_ABORTED
        records = list((tmp_path / "transport_failures").glob("FAIL-*.json"))
        assert len(records) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Enforcement — Allowed Caller 강제 차단 (Jeni EAG-3 HG-1)
# ══════════════════════════════════════════════════════════════════════════════

class TestAllowedCallerEnforcement:
    """bypass fixture 없음 — 실제 stack frame 검증."""

    # E-01
    def test_direct_call_from_test_raises_unauthorized(self):
        """테스트 모듈은 ALLOWED_CALLER_MODULES 외부 → RuntimeError 발생."""
        with pytest.raises(RuntimeError, match="UNAUTHORIZED_CALLER"):
            transport_client._enforce_allowed_caller()

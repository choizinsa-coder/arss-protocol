"""
test_p3t4.py
P3-T4 Fallback Layer Tests
SSOT: Domi Phase 3 Design v1.0 + B안 Gap 해소 (S170) / EAG-1 Approved (비오(Joshua))

Layer A — failure record schema test     (A-01 ~ A-03)
Layer B — classification test            (B-01 ~ B-03)
Layer C — fallback action policy test    (C-01 ~ C-03)
Layer D — receipt generation test        (D-01 ~ D-03)
Layer E — duplicate processing prevention(E-01 ~ E-03)
Layer F — P3-T5 interface contract test  (F-01 ~ F-03)
합계: 18개
"""

import json
import os
import sys
import pytest
from pathlib import Path
from unittest import mock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.fallback import fallback_classifier, fallback_receipt, fallback_scanner
from tools.sync_layer.fallback.fallback_types import (
    CLASSIFICATION_RETRYABLE,
    CLASSIFICATION_NON_RETRYABLE,
    CLASSIFICATION_INVALID,
    RESULT_SUCCESS,
    RESULT_ESCALATED,
    RESULT_FATAL,
    ACTION_ESCALATED_ONLY,
    ACTION_SECONDARY_ATTEMPT,
    RECEIPT_VERSION,
    FallbackRecord,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_failure_record():
    return {
        "event_id": "DEPLOY-170-20260529T100000Z-AABBCC",
        "event_type": "DEPLOYMENT_EVENT",
        "endpoint": "http://localhost:5678/webhook/aiba-deployment",
        "failure_reason": "HTTP_ERROR: 500",
        "payload_hash": "a" * 64,
        "session": 170,
        "timestamp": "2026-05-29T10:00:00+09:00",
        "record_version": "TRANSPORT_FAILURE_RECORD_v1",
        "p3_task": "P3-T3",
    }


@pytest.fixture
def valid_fallback_record(valid_failure_record):
    return FallbackRecord(
        event_id=valid_failure_record["event_id"],
        event_type=valid_failure_record["event_type"],
        endpoint=valid_failure_record["endpoint"],
        failure_reason=valid_failure_record["failure_reason"],
        payload_hash=valid_failure_record["payload_hash"],
        session=valid_failure_record["session"],
        timestamp=valid_failure_record["timestamp"],
        record_version=valid_failure_record["record_version"],
        source_path="registry/transport_failures/FAIL-DEPLOY-170.json",
    )


@pytest.fixture
def bypass_caller(monkeypatch):
    """Allowed Caller 검증 bypass (테스트 환경 전용)."""
    monkeypatch.setattr(
        "tools.sync_layer.fallback.fallback_handler._enforce_allowed_caller",
        lambda: None,
    )


@pytest.fixture
def mock_fallback_endpoints_disabled(monkeypatch):
    """secondary_enabled=false 엔드포인트 설정 mock."""
    config = {
        "secondary_enabled": False,
        "secondary_endpoint": None,
        "manual_escalation_required": True,
        "approved_by": None,
        "approval_ref": None,
    }
    monkeypatch.setattr(
        "tools.sync_layer.fallback.fallback_handler._load_endpoint_config",
        lambda event_type: config,
    )


@pytest.fixture
def mock_fallback_endpoints_enabled(monkeypatch):
    """secondary_enabled=true 엔드포인트 설정 mock."""
    config = {
        "secondary_enabled": True,
        "secondary_endpoint": "http://localhost:5678/webhook/aiba-fallback",
        "manual_escalation_required": False,
        "approved_by": "비오(Joshua)",
        "approval_ref": "EAG-FALLBACK-001",
    }
    monkeypatch.setattr(
        "tools.sync_layer.fallback.fallback_handler._load_endpoint_config",
        lambda event_type: config,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Layer A — Failure Record Schema Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFailureRecordSchema:

    # A-01
    def test_valid_failure_record_classifies_correctly(self, valid_failure_record):
        """유효한 transport_failure_record는 올바르게 분류된다."""
        result = fallback_classifier.classify_failure_record(valid_failure_record)
        assert result in (CLASSIFICATION_RETRYABLE, CLASSIFICATION_NON_RETRYABLE)

    # A-02
    def test_empty_record_returns_invalid(self):
        """빈 dict는 INVALID_RECORD를 반환한다."""
        result = fallback_classifier.classify_failure_record({})
        assert result == CLASSIFICATION_INVALID

    # A-03
    def test_missing_required_field_returns_invalid(self, valid_failure_record):
        """필수 필드(payload_hash) 누락 시 INVALID_RECORD를 반환한다."""
        del valid_failure_record["payload_hash"]
        result = fallback_classifier.classify_failure_record(valid_failure_record)
        assert result == CLASSIFICATION_INVALID


# ══════════════════════════════════════════════════════════════════════════════
# Layer B — Classification Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestClassification:

    # B-01
    def test_http_5xx_is_retryable(self, valid_failure_record):
        """HTTP_ERROR: 5xx → RETRYABLE_CANDIDATE."""
        valid_failure_record["failure_reason"] = "HTTP_ERROR: 503"
        result = fallback_classifier.classify_failure_record(valid_failure_record)
        assert result == CLASSIFICATION_RETRYABLE

    # B-02
    def test_http_4xx_is_non_retryable(self, valid_failure_record):
        """HTTP_ERROR: 4xx → NON_RETRYABLE."""
        valid_failure_record["failure_reason"] = "HTTP_ERROR: 400"
        result = fallback_classifier.classify_failure_record(valid_failure_record)
        assert result == CLASSIFICATION_NON_RETRYABLE

    # B-03
    def test_payload_invalid_is_non_retryable(self, valid_failure_record):
        """PAYLOAD_INVALID → NON_RETRYABLE."""
        valid_failure_record["failure_reason"] = "PAYLOAD_INVALID: missing fields"
        result = fallback_classifier.classify_failure_record(valid_failure_record)
        assert result == CLASSIFICATION_NON_RETRYABLE


# ══════════════════════════════════════════════════════════════════════════════
# Layer C — Fallback Action Policy Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFallbackActionPolicy:

    # C-01
    def test_secondary_disabled_returns_escalated(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """secondary_enabled=false → ACTION_ESCALATED_ONLY, RESULT_ESCALATED."""
        from tools.sync_layer.fallback import fallback_handler
        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "receipts"):
            result = fallback_handler.handle(valid_fallback_record)
        assert result["action"] == ACTION_ESCALATED_ONLY
        assert result["result"] == RESULT_ESCALATED
        assert result["manual_path_required"] is True

    # C-02
    def test_secondary_enabled_success_returns_success(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_enabled, tmp_path
    ):
        """secondary_enabled=true, HTTP 200 → ACTION_SECONDARY_ATTEMPT, RESULT_SUCCESS."""
        from tools.sync_layer.fallback import fallback_handler

        resp = mock.MagicMock()
        resp.status = 200
        resp.__enter__ = lambda s: s
        resp.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("urllib.request.urlopen", return_value=resp):
            with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "receipts"):
                result = fallback_handler.handle(valid_fallback_record)

        assert result["action"] == ACTION_SECONDARY_ATTEMPT
        assert result["result"] == RESULT_SUCCESS
        assert result["manual_path_required"] is False

    # C-03
    def test_secondary_enabled_failure_returns_fatal(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_enabled, tmp_path
    ):
        """secondary_enabled=true, HTTP 실패 → RESULT_FATAL (FALLBACK_EXHAUSTED)."""
        import urllib.error
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "receipts"):
                result = fallback_handler.handle(valid_fallback_record)

        assert result["result"] == RESULT_FATAL
        assert result["manual_path_required"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Layer D — Receipt Generation Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestReceiptGeneration:

    # D-01
    def test_receipt_is_created_on_escalation(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """ESCALATED 처리 시 receipt 파일이 생성된다."""
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "receipts"):
            result = fallback_handler.handle(valid_fallback_record)

        assert result["receipt_saved"] is True
        receipt_files = list((tmp_path / "receipts").glob("FB-*.json"))
        assert len(receipt_files) == 1

    # D-02
    def test_receipt_fields_complete(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """receipt에 P3-T5 필수 6개 항목이 모두 존재한다."""
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "receipts"):
            fallback_handler.handle(valid_fallback_record)

        receipt_file = list((tmp_path / "receipts").glob("FB-*.json"))[0]
        receipt = json.loads(receipt_file.read_text())

        # P3-T5 입력 계약 6개
        assert receipt.get("fallback_id", "").startswith("FB-")       # exists
        assert receipt.get("source_failure_record", "").startswith("FAIL-")  # source_failure_record exists
        assert len(receipt.get("payload_hash", "")) == 64              # payload_hash
        assert receipt.get("result") in (RESULT_SUCCESS, RESULT_ESCALATED, RESULT_FATAL)  # result enum
        assert receipt.get("session") == valid_fallback_record.session  # session match
        assert receipt.get("validation_hint") == "P3-T5_REQUIRED"      # validation_hint

    # D-03
    def test_receipt_saved_to_correct_path(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """receipt는 registry/fallback_receipts/ 하위에 저장된다."""
        from tools.sync_layer.fallback import fallback_handler
        receipt_dir = tmp_path / "receipts"

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", receipt_dir):
            result = fallback_handler.handle(valid_fallback_record)

        expected_path = receipt_dir / f"{result['fallback_id']}.json"
        assert expected_path.exists()


# ══════════════════════════════════════════════════════════════════════════════
# Layer E — Duplicate Processing Prevention Tests (Jeni TA-1)
# ══════════════════════════════════════════════════════════════════════════════

class TestDuplicateProcessingPrevention:

    # E-01
    def test_atomic_rename_prevents_duplicate_claim(self, tmp_path):
        """동일 파일에 대해 두 번째 atomic rename은 None을 반환한다."""
        fail_file = tmp_path / "FAIL-test-001.json"
        fail_file.write_text("{}")

        first_claim = fallback_scanner._atomic_claim(fail_file)
        assert first_claim is not None

        # 원본 파일이 사라졌으므로 두 번째 claim은 None
        second_claim = fallback_scanner._atomic_claim(fail_file)
        assert second_claim is None

    # E-02
    def test_already_processing_file_is_skipped(self, tmp_path):
        """FAIL-*.PROCESSING 파일은 scan 대상에서 제외된다."""
        (tmp_path / "FAIL-event-001.PROCESSING").write_text("{}")

        with mock.patch.object(fallback_scanner, "FAILURE_RECORD_DIR", tmp_path):
            candidates = fallback_scanner.list_unhandled()

        assert len(candidates) == 0

    # E-03
    def test_processed_marker_persists_after_handling(self, tmp_path):
        """처리 완료 후 FAIL-*.PROCESSED 파일이 남는다."""
        processing_file = tmp_path / "FAIL-event-001.PROCESSING"
        processing_file.write_text("{}")

        result = fallback_scanner._mark_processed(processing_file)

        assert result is True
        assert (tmp_path / "FAIL-event-001.PROCESSED").exists()
        assert not processing_file.exists()


# ══════════════════════════════════════════════════════════════════════════════
# Layer F — P3-T5 Interface Contract Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestP3T5InterfaceContract:

    # F-01
    def test_all_p3t5_input_conditions_present(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """fallback_receipt에 P3-T5 입력 계약 6개 조건이 전부 충족된다."""
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "r"):
            fallback_handler.handle(valid_fallback_record)

        receipts = list((tmp_path / "r").glob("FB-*.json"))
        assert len(receipts) == 1
        r = json.loads(receipts[0].read_text())

        assert r["fallback_id"]              # exists
        assert r["source_failure_record"]    # source_failure_record exists
        assert r["payload_hash"]             # payload_hash
        assert r["result"]                   # result enum valid
        assert isinstance(r["session"], int) # session
        assert r["receipt_version"] == RECEIPT_VERSION  # processed marker (version)

    # F-02
    def test_validation_hint_is_p3t5_required(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """validation_hint 필드가 'P3-T5_REQUIRED'이다."""
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "r"):
            fallback_handler.handle(valid_fallback_record)

        r = json.loads(list((tmp_path / "r").glob("FB-*.json"))[0].read_text())
        assert r["validation_hint"] == "P3-T5_REQUIRED"

    # F-03
    def test_receipt_session_matches_source_record(
        self, valid_fallback_record, bypass_caller, mock_fallback_endpoints_disabled, tmp_path
    ):
        """receipt.session == source failure record의 session과 일치한다."""
        from tools.sync_layer.fallback import fallback_handler

        with mock.patch.object(fallback_receipt, "FALLBACK_RECEIPT_DIR", tmp_path / "r"):
            fallback_handler.handle(valid_fallback_record)

        r = json.loads(list((tmp_path / "r").glob("FB-*.json"))[0].read_text())
        assert r["session"] == valid_fallback_record.session

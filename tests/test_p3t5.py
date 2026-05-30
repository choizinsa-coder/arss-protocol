"""
test_p3t5.py
P3-T5 Validation Layer 테스트
EAG 승인: 비오(Joshua) S171

Layer A: receipt_validator    (A1~A3)
Layer B: consistency_validator (B1~B3)
Layer C: transport_validator   (C1~C3)
Layer D: fallback_validator    (D1~D3)
Layer E: validation_runner 집계 (E1~E3)
Layer F: 통합 검증             (F1~F3)
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.validator import receipt_validator
from tools.sync_layer.validator import consistency_validator
from tools.sync_layer.validator import transport_validator
from tools.sync_layer.validator import fallback_validator
from tools.sync_layer.validator import validation_runner


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def make_valid_receipt() -> dict:
    return {
        "deployment_id": "DEPLOY-171-20260530T000000Z-AAAAAA",
        "deploy_type": "TIER1_EAG_DEPLOY",
        "actor": "deploy_executor",
        "approval_id": "EAG-1",
        "artifact_hash": "a" * 64,
        "target": "SESSION_CONTEXT",
        "result": "SUCCESS",
        "timestamp": "2026-05-30T00:00:00+09:00",
        "request_id": "sync_orchestrator",
        "session": 171,
        "receipt_version": "DEPLOYMENT_RECEIPT_v1",
    }


# ── Layer A: receipt_validator ────────────────────────────────────────────────

class TestReceiptValidatorA:

    def test_A1_pass_valid_receipt(self, tmp_path):
        """A1: 유효한 DEPLOYMENT_RECEIPT_v1 → PASS"""
        rd = tmp_path / "deployment_receipts"
        rd.mkdir()
        (rd / "DEPLOY-171.json").write_text(
            json.dumps(make_valid_receipt()), encoding="utf-8"
        )
        with patch.object(receipt_validator, "RECEIPT_DIR", rd):
            result = receipt_validator.validate()
        assert result["verdict"] == "PASS"
        assert result["checked"] == 1
        assert result["failed"] == 0

    def test_A2_fail_missing_fields(self, tmp_path):
        """A2: 필수 필드 누락 → FAIL"""
        rd = tmp_path / "deployment_receipts"
        rd.mkdir()
        bad = {"deployment_id": "D-001", "receipt_version": "DEPLOYMENT_RECEIPT_v1"}
        (rd / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
        with patch.object(receipt_validator, "RECEIPT_DIR", rd):
            result = receipt_validator.validate()
        assert result["verdict"] == "FAIL"
        assert result["failed"] == 1
        issues = result["details"][0]["issues"]
        assert any("R1_MISSING_FIELDS" in i for i in issues)

    def test_A3_unknown_dir_missing(self, tmp_path):
        """A3: receipt 디렉터리 없음 → UNKNOWN"""
        with patch.object(receipt_validator, "RECEIPT_DIR", tmp_path / "nonexistent"):
            result = receipt_validator.validate()
        assert result["verdict"] == "UNKNOWN"


# ── Layer B: consistency_validator ───────────────────────────────────────────

class TestConsistencyValidatorB:

    def _write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_B1_pass_all_match(self, tmp_path):
        """B1: POINTER / MANIFEST / FINAL 3-way 일치 → PASS"""
        ptr = tmp_path / "POINTER.json"
        mft = tmp_path / "MANIFEST.json"
        fin = tmp_path / "FINAL.json"
        self._write(ptr, {
            "session_count": 170, "context_hash": "abc", "updated_at": "T1",
            "canonical_file": fin.name,
        })
        self._write(mft, {"session_count": 170, "context_hash": "abc", "updated_at": "T1"})
        self._write(fin, {"session_count": 170, "context_hash": "abc"})
        with patch.object(consistency_validator, "POINTER_PATH", ptr), \
             patch.object(consistency_validator, "MANIFEST_PATH", mft), \
             patch.object(consistency_validator, "VPS_ROOT", tmp_path):
            result = consistency_validator.validate()
        assert result["verdict"] == "PASS"
        assert result["mismatches"] == []

    def test_B2_fail_session_count_mismatch(self, tmp_path):
        """B2: MANIFEST session_count 불일치 → FAIL"""
        ptr = tmp_path / "POINTER.json"
        mft = tmp_path / "MANIFEST.json"
        fin = tmp_path / "FINAL.json"
        self._write(ptr, {
            "session_count": 170, "context_hash": "abc", "updated_at": "T1",
            "canonical_file": fin.name,
        })
        self._write(mft, {"session_count": 169, "context_hash": "abc", "updated_at": "T1"})
        self._write(fin, {"session_count": 170, "context_hash": "abc"})
        with patch.object(consistency_validator, "POINTER_PATH", ptr), \
             patch.object(consistency_validator, "MANIFEST_PATH", mft), \
             patch.object(consistency_validator, "VPS_ROOT", tmp_path):
            result = consistency_validator.validate()
        assert result["verdict"] == "FAIL"
        assert any(m["field"] == "session_count" for m in result["mismatches"])

    def test_B3_unknown_pointer_missing(self, tmp_path):
        """B3: POINTER 파일 없음 → UNKNOWN"""
        mft = tmp_path / "MANIFEST.json"
        mft.write_text("{}", encoding="utf-8")
        with patch.object(consistency_validator, "POINTER_PATH", tmp_path / "MISSING.json"), \
             patch.object(consistency_validator, "MANIFEST_PATH", mft):
            result = consistency_validator.validate()
        assert result["verdict"] == "UNKNOWN"


# ── Layer C: transport_validator ─────────────────────────────────────────────

class TestTransportValidatorC:

    def _ep_file(self, tmp_path, url="http://localhost:5678/wh", active=True):
        ep = tmp_path / "transport_endpoints.json"
        ep.write_text(json.dumps({
            "version": "TRANSPORT_REGISTRY_v1",
            "endpoints": {
                "DEPLOYMENT_EVENT": {"url": url, "active": active}
            },
        }), encoding="utf-8")
        return ep

    def test_C1_pass_tcp_reachable(self, tmp_path):
        """C1: TCP connection 성공 → PASS"""
        ep = self._ep_file(tmp_path)
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=None)
        mock_cm.__exit__ = MagicMock(return_value=False)
        with patch.object(transport_validator, "ENDPOINTS_PATH", ep), \
             patch("tools.sync_layer.validator.transport_validator.socket") as ms:
            ms.create_connection.return_value = mock_cm
            result = transport_validator.validate()
        assert result["verdict"] == "PASS"
        assert result["checked"] == 1
        assert result["failed"] == 0

    def test_C2_fail_connection_refused(self, tmp_path):
        """C2: ConnectionRefusedError → FAIL"""
        ep = self._ep_file(tmp_path, url="http://localhost:9999/wh")
        with patch.object(transport_validator, "ENDPOINTS_PATH", ep), \
             patch("tools.sync_layer.validator.transport_validator.socket") as ms:
            ms.create_connection.side_effect = ConnectionRefusedError()
            result = transport_validator.validate()
        assert result["verdict"] == "FAIL"
        assert any("CONNECTION_REFUSED" in d.get("reason", "") for d in result["details"])

    def test_C3_unknown_timeout(self, tmp_path):
        """C3: TimeoutError → UNKNOWN"""
        ep = self._ep_file(tmp_path)
        with patch.object(transport_validator, "ENDPOINTS_PATH", ep), \
             patch("tools.sync_layer.validator.transport_validator.socket") as ms:
            ms.create_connection.side_effect = TimeoutError()
            result = transport_validator.validate()
        assert result["verdict"] == "UNKNOWN"
        assert any("TIMEOUT" in d.get("reason", "") for d in result["details"])


# ── Layer D: fallback_validator ──────────────────────────────────────────────

class TestFallbackValidatorD:

    def test_D1_pass_valid_receipt_with_marker(self, tmp_path):
        """D1: 유효한 fallback receipt + PROCESSED 마커 → PASS"""
        rd = tmp_path / "fallback_receipts"
        fd = tmp_path / "transport_failures"
        rd.mkdir(); fd.mkdir()
        event_id = "EVT-001"
        receipt = {
            "fallback_id": f"FB-{event_id}",
            "source_failure_record": str(fd / f"FAIL-{event_id}.json"),
            "event_id": event_id,
            "payload_hash": "b" * 64,
            "result": "ESCALATED",
            "session": 171,
        }
        (rd / f"FB-{event_id}.json").write_text(json.dumps(receipt), encoding="utf-8")
        (fd / f"FAIL-{event_id}.PROCESSED").touch()
        with patch.object(fallback_validator, "FALLBACK_RECEIPT_DIR", rd), \
             patch.object(fallback_validator, "FAILURE_RECORD_DIR", fd):
            result = fallback_validator.validate()
        assert result["verdict"] == "PASS"
        assert result["checked"] == 1

    def test_D2_fail_processed_marker_missing(self, tmp_path):
        """D2: PROCESSED 마커 없음 → FAIL"""
        rd = tmp_path / "fallback_receipts"
        fd = tmp_path / "transport_failures"
        rd.mkdir(); fd.mkdir()
        event_id = "EVT-002"
        receipt = {
            "fallback_id": f"FB-{event_id}",
            "source_failure_record": str(fd / f"FAIL-{event_id}.json"),
            "event_id": event_id,
            "payload_hash": "c" * 64,
            "result": "SUCCESS",
            "session": 171,
        }
        (rd / f"FB-{event_id}.json").write_text(json.dumps(receipt), encoding="utf-8")
        # PROCESSED 마커 없음
        with patch.object(fallback_validator, "FALLBACK_RECEIPT_DIR", rd), \
             patch.object(fallback_validator, "FAILURE_RECORD_DIR", fd):
            result = fallback_validator.validate()
        assert result["verdict"] == "FAIL"
        issues = result["details"][0]["issues"]
        assert any("F3_PROCESSED_MARKER_NOT_FOUND" in i for i in issues)

    def test_D3_unknown_no_receipts(self, tmp_path):
        """D3: fallback receipt 없음 → UNKNOWN"""
        rd = tmp_path / "fallback_receipts"
        rd.mkdir()
        fd = tmp_path / "transport_failures"
        with patch.object(fallback_validator, "FALLBACK_RECEIPT_DIR", rd), \
             patch.object(fallback_validator, "FAILURE_RECORD_DIR", fd):
            result = fallback_validator.validate()
        assert result["verdict"] == "UNKNOWN"


# ── Layer E: validation_runner 집계 ─────────────────────────────────────────

class TestValidationRunnerE:

    def _p(self, name="x"):
        return lambda: {"validator": name, "verdict": "PASS"}

    def _f(self, name="y"):
        return lambda: {"validator": name, "verdict": "FAIL", "details": [{"e": "x"}]}

    def _u(self, name="z"):
        return lambda: {"validator": name, "verdict": "UNKNOWN"}

    def test_E1_overall_pass_all_pass(self):
        """E1: 모든 validator PASS → overall PASS"""
        with patch.object(receipt_validator, "validate", self._p("receipt")), \
             patch.object(consistency_validator, "validate", self._p("consistency")), \
             patch.object(transport_validator, "validate", self._p("transport")), \
             patch.object(fallback_validator, "validate", self._p("fallback")):
            report = validation_runner.run_all()
        assert report["overall_verdict"] == "PASS"
        assert report["report_type"] == "ValidationReport"

    def test_E2_overall_fail_one_fail(self):
        """E2: 1개 FAIL → overall FAIL (FAIL > UNKNOWN > PASS)"""
        with patch.object(receipt_validator, "validate", self._f("receipt")), \
             patch.object(consistency_validator, "validate", self._u("consistency")), \
             patch.object(transport_validator, "validate", self._p("transport")), \
             patch.object(fallback_validator, "validate", self._p("fallback")):
            report = validation_runner.run_all()
        assert report["overall_verdict"] == "FAIL"

    def test_E3_overall_unknown_no_fail(self):
        """E3: FAIL 없음 + UNKNOWN 존재 → overall UNKNOWN"""
        with patch.object(receipt_validator, "validate", self._p("receipt")), \
             patch.object(consistency_validator, "validate", self._u("consistency")), \
             patch.object(transport_validator, "validate", self._p("transport")), \
             patch.object(fallback_validator, "validate", self._p("fallback")):
            report = validation_runner.run_all()
        assert report["overall_verdict"] == "UNKNOWN"


# ── Layer F: 통합 검증 ────────────────────────────────────────────────────────

class TestIntegrationF:

    def _pass(self, name="x"):
        return lambda: {"validator": name, "verdict": "PASS"}

    def test_F1_report_structure_complete(self):
        """F1: ValidationReport 필수 구조 + HG-2 ready 확인"""
        with patch.object(receipt_validator, "validate", self._pass("receipt")), \
             patch.object(consistency_validator, "validate", self._pass("consistency")), \
             patch.object(transport_validator, "validate", self._pass("transport")), \
             patch.object(fallback_validator, "validate", self._pass("fallback")):
            report = validation_runner.run_all()
        required = {
            "report_type", "validator_version", "overall_verdict",
            "executed_at", "validator_results", "evidence_refs",
            "p3_task", "hg2_ready",
        }
        assert required.issubset(report.keys())
        assert report["hg2_ready"] is True
        assert report["p3_task"] == "P3-T5"
        assert len(report["validator_results"]) == 4

    def test_F2_exception_treated_as_unknown(self):
        """F2: validator 예외 발생 → UNKNOWN 처리 (fail-closed)"""
        def boom():
            raise RuntimeError("unexpected")

        with patch.object(receipt_validator, "validate", boom), \
             patch.object(consistency_validator, "validate", self._pass("consistency")), \
             patch.object(transport_validator, "validate", self._pass("transport")), \
             patch.object(fallback_validator, "validate", self._pass("fallback")):
            report = validation_runner.run_all()
        assert report["overall_verdict"] == "UNKNOWN"
        assert any(r.get("verdict") == "UNKNOWN" for r in report["validator_results"])

    def test_F3_all_validators_always_executed(self):
        """F3: 1개 FAIL에도 나머지 3개 validator 모두 실행됨"""
        called = []

        def make(name, verdict):
            def fn():
                called.append(name)
                return {"validator": name, "verdict": verdict}
            return fn

        with patch.object(receipt_validator, "validate", make("receipt", "FAIL")), \
             patch.object(consistency_validator, "validate", make("consistency", "PASS")), \
             patch.object(transport_validator, "validate", make("transport", "UNKNOWN")), \
             patch.object(fallback_validator, "validate", make("fallback", "PASS")):
            validation_runner.run_all()

        assert set(called) == {"receipt", "consistency", "transport", "fallback"}

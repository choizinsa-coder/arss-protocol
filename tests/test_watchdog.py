import json
import pytest
from tools.eps_v1_3_d.watchdog import emit_system_error_receipt


# ── 정상 path ──────────────────────────────────────────────────
def test_emit_produces_valid_receipt_json(capsys):
    """정상 호출 → stdout에 유효한 JSON receipt 출력"""
    emit_system_error_receipt("JOB-001", "/opt/arss/test.json")
    captured = capsys.readouterr().out

    # stdout에서 JSON 블록 추출 (첫 번째 줄은 "watchdog skeleton loaded")
    lines = captured.strip().splitlines()
    json_text = "\n".join(lines[1:])  # 첫 줄 skip
    receipt = json.loads(json_text)

    assert receipt["receipt_type"] == "system_error"
    assert receipt["job_id"] == "JOB-001"
    assert receipt["target_artifact_path"] == "/opt/arss/test.json"
    assert receipt["verdict"] == "SYSTEM_ERROR"
    assert receipt["generated_by"] == "watchdog"
    assert receipt["receipt_integrity_ok"] is False


def test_emit_default_error_code(capsys):
    """error_code 미지정 → 기본값 VERIFIER_CRASH"""
    emit_system_error_receipt("JOB-002", "/opt/arss/test2.json")
    captured = capsys.readouterr().out
    lines = captured.strip().splitlines()
    receipt = json.loads("\n".join(lines[1:]))
    assert receipt["error_code"] == "VERIFIER_CRASH"


# ── failure path ───────────────────────────────────────────────
def test_emit_custom_error_code(capsys):
    """custom error_code → receipt에 반영"""
    emit_system_error_receipt("JOB-003", "/tmp/x.json", error_code="TIMEOUT_ERROR")
    captured = capsys.readouterr().out
    lines = captured.strip().splitlines()
    receipt = json.loads("\n".join(lines[1:]))
    assert receipt["error_code"] == "TIMEOUT_ERROR"


def test_emit_required_fields_present(capsys):
    """필수 필드 전체 존재 확인"""
    emit_system_error_receipt("JOB-004", "/tmp/artifact.json")
    captured = capsys.readouterr().out
    lines = captured.strip().splitlines()
    receipt = json.loads("\n".join(lines[1:]))

    required = {
        "receipt_type", "receipt_version", "receipt_id",
        "job_id", "generated_at_kst", "generated_by",
        "error_source", "error_code", "target_artifact_path",
        "artifact_stage", "verdict", "receipt_integrity_ok",
    }
    for field in required:
        assert field in receipt, f"필수 필드 누락: {field}"


def test_emit_receipt_id_prefixed_se(capsys):
    """receipt_id 형식 확인 — SE- 접두사"""
    emit_system_error_receipt("JOB-005", "/tmp/x.json")
    captured = capsys.readouterr().out
    lines = captured.strip().splitlines()
    receipt = json.loads("\n".join(lines[1:]))
    assert receipt["receipt_id"].startswith("SE-")


def test_emit_artifact_stage_staging(capsys):
    """artifact_stage = STAGING 고정값 확인"""
    emit_system_error_receipt("JOB-006", "/tmp/x.json")
    captured = capsys.readouterr().out
    lines = captured.strip().splitlines()
    receipt = json.loads("\n".join(lines[1:]))
    assert receipt["artifact_stage"] == "STAGING"

import json
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tools.governance.conditional_eag_registry as ceag_mod
from tools.governance.conditional_eag_registry import (
    ConditionalEAGEntry,
    ConditionalEAGError,
    ExecutionResult,
    evaluate_condition,
    get_all_entries,
    get_entry,
    record_execution,
    register,
)


def _make_entry(tmp_path, monkeypatch, entry_id="CEAG-T01"):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    return ConditionalEAGEntry(
        id=entry_id,
        condition_description="GHS.Calibration_Error_Rate > 0.20",
        action_description="Emergency Calibration Review",
        limit_per_days=30,
        expires_at="2099-01-01T00:00:00+00:00",
        eag_approval_id="EAG-S326-CEAG-001",
    )


# TC-01: 정상 등록
def test_register_success(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    result = register(entry)
    assert result["id"] == "CEAG-T01"
    assert "registered_at" in result
    assert result["schema"] == "conditional_eag_entry_v1"


# TC-02: 중복 id 재등록 거부
def test_register_duplicate(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    with pytest.raises(ConditionalEAGError, match="duplicate"):
        register(entry)


# TC-03: 필드 누락 거부
def test_register_missing_field(tmp_path, monkeypatch):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    entry = ConditionalEAGEntry(
        id="",
        condition_description="GHS.Calibration_Error_Rate > 0.20",
        action_description="test",
        limit_per_days=30,
        expires_at="2099-01-01T00:00:00+00:00",
        eag_approval_id="EAG-TEST",
    )
    with pytest.raises(ConditionalEAGError, match="id"):
        register(entry)


# TC-04: 등록 후 조회 -- id 일치
def test_get_entry_found(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    found = get_entry("CEAG-T01")
    assert found is not None
    assert found["id"] == "CEAG-T01"


# TC-05: 미등록 id 조회 -- None
def test_get_entry_not_found(tmp_path, monkeypatch):
    _make_entry(tmp_path, monkeypatch)
    result = get_entry("CEAG-NONEXISTENT")
    assert result is None


# TC-06: 전체 조회 -- 2건 등록 후 len==2
def test_get_all_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    for i in range(2):
        e = ConditionalEAGEntry(
            id="CEAG-T0{}".format(i),
            condition_description="GHS.Calibration_Error_Rate > 0.20",
            action_description="test",
            limit_per_days=30,
            expires_at="2099-01-01T00:00:00+00:00",
            eag_approval_id="EAG-TEST",
        )
        register(e)
    assert len(get_all_entries()) == 2


# TC-07: 조건 충족 -- calibration_error_rate=0.25
def test_evaluate_condition_met(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    met, reason = evaluate_condition("CEAG-T01", {"calibration_error_rate": 0.25})
    assert met is True
    assert reason == "CONDITION_MET"


# TC-08: 조건 미충족 -- calibration_error_rate=0.10
def test_evaluate_condition_not_met(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    met, reason = evaluate_condition("CEAG-T01", {"calibration_error_rate": 0.10})
    assert met is False
    assert reason == "CONDITION_NOT_MET"


# TC-09: 만료된 항목 -- EXPIRED
def test_evaluate_condition_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    entry = ConditionalEAGEntry(
        id="CEAG-EXP",
        condition_description="GHS.Calibration_Error_Rate > 0.20",
        action_description="test",
        limit_per_days=30,
        expires_at="2020-01-01T00:00:00+00:00",
        eag_approval_id="EAG-TEST",
    )
    register(entry)
    met, reason = evaluate_condition("CEAG-EXP", {"calibration_error_rate": 0.9})
    assert met is False
    assert reason == "EXPIRED"


# TC-10: 미등록 id 조건 평가 -- ENTRY_NOT_FOUND
def test_evaluate_condition_not_found(tmp_path, monkeypatch):
    _make_entry(tmp_path, monkeypatch)
    met, reason = evaluate_condition("CEAG-NONE", {"calibration_error_rate": 0.9})
    assert met is False
    assert reason == "ENTRY_NOT_FOUND"


# TC-11: 최초 실행 -- ALLOW
def test_record_execution_allow(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    result = record_execution("CEAG-T01", "calibration_error=0.30")
    assert result == ExecutionResult.ALLOW.value


# TC-12: 한도 초과 재실행 -- DENIED
def test_record_execution_limit_exceeded(tmp_path, monkeypatch):
    entry = _make_entry(tmp_path, monkeypatch)
    register(entry)
    record_execution("CEAG-T01", "first")
    result = record_execution("CEAG-T01", "second")
    assert result == ExecutionResult.DENIED.value


# TC-13: 전역 회로 차단기 -- 24시간 내 4번째 실행
def test_record_execution_circuit_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    now = datetime.now(timezone.utc)
    for i in range(3):
        execution = {
            "schema": "conditional_eag_execution_v1",
            "version": "1.0.0",
            "entry_id": "CEAG-OTHER-{}".format(i),
            "trigger_reason": "seed",
            "executed_at": now.isoformat(),
            "result": ExecutionResult.ALLOW.value,
        }
        (tmp_path / "executions.jsonl").parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path / "executions.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(execution) + "\n")
    entry = ConditionalEAGEntry(
        id="CEAG-NEW",
        condition_description="GHS.Calibration_Error_Rate > 0.20",
        action_description="test",
        limit_per_days=30,
        expires_at="2099-01-01T00:00:00+00:00",
        eag_approval_id="EAG-TEST",
    )
    register(entry)
    result = record_execution("CEAG-NEW", "trigger")
    assert result == ExecutionResult.CIRCUIT_BREAKER_OPEN.value


# TC-14: 만료 항목 실행 -- DENIED
def test_record_execution_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(ceag_mod, "REGISTRY_PATH",
                        tmp_path / "registry.jsonl")
    monkeypatch.setattr(ceag_mod, "EXECUTIONS_PATH",
                        tmp_path / "executions.jsonl")
    entry = ConditionalEAGEntry(
        id="CEAG-EXP2",
        condition_description="GHS.Calibration_Error_Rate > 0.20",
        action_description="test",
        limit_per_days=30,
        expires_at="2020-01-01T00:00:00+00:00",
        eag_approval_id="EAG-TEST",
    )
    register(entry)
    result = record_execution("CEAG-EXP2", "trigger")
    assert result == ExecutionResult.DENIED.value

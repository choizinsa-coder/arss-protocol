"""
tests/test_sync_orchestrator.py
AIBA Sync Layer P3-T1 pytest 검증
EAG-1 Approved (S168) — 비오(Joshua)

커버리지:
  T-01 ~ T-05: event_store 단위 테스트
  T-06 ~ T-10: run_event_driven_sync 분기 전체
  T-11 ~ T-14: run_reconciliation 분기 전체
  T-15:        get_orchestrator_status 구조 검증
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.sync_layer.event_store import (
    emit_final_created_event,
    load_pending_event,
    mark_event_consumed,
    check_missed_event,
    get_event_store_status,
    EVENT_STATUS_PENDING,
    EVENT_STATUS_CONSUMED,
)
from tools.sync_layer.sync_orchestrator import (
    run_event_driven_sync,
    run_reconciliation,
    get_orchestrator_status,
    ORCHESTRATION_EVENT_DRIVEN,
    ORCHESTRATION_NO_EVENT,
    ORCHESTRATION_SESSION_MISMATCH,
    ORCHESTRATION_SYNC_STALE,
    ORCHESTRATION_SYNC_FAILED,
    RECONCILIATION_STALE_DETECTED,
    RECONCILIATION_ALREADY_SYNCED,
    RECONCILIATION_NO_FINAL,
    RECONCILIATION_SYNC_FAILED,
)


# ── 픽스처 ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_event_dir(tmp_path, monkeypatch):
    """event/ 디렉터리를 tmp_path로 대체."""
    event_dir = tmp_path / "event"
    event_dir.mkdir()
    monkeypatch.setattr("tools.sync_layer.event_store.EVENT_DIR", event_dir)
    monkeypatch.setattr(
        "tools.sync_layer.event_store.FINAL_CREATED_EVENT_PATH",
        event_dir / "FINAL_CREATED_EVENT.json",
    )
    return event_dir


@pytest.fixture
def tmp_deploy_dir(tmp_path, monkeypatch):
    """DEPLOY_REQUEST_PATH를 tmp_path로 대체."""
    event_dir = tmp_path / "event"
    event_dir.mkdir(exist_ok=True)
    deploy_path = event_dir / "DEPLOY_REQUEST.json"
    monkeypatch.setattr("tools.sync_layer.sync_orchestrator.EVENT_DIR", event_dir)
    monkeypatch.setattr(
        "tools.sync_layer.sync_orchestrator.DEPLOY_REQUEST_PATH",
        deploy_path,
    )
    return event_dir


@pytest.fixture
def sample_final_path(tmp_path):
    """실제로 존재하는 FINAL 파일 경로."""
    final = tmp_path / "SESSION_CONTEXT_S168_FINAL.json"
    final.write_text('{"session_count": 168}', encoding="utf-8")
    return final


@pytest.fixture
def commit_result():
    """execute_close_bundle COMMIT 응답 샘플."""
    return {
        "decision": "COMMIT",
        "session": 168,
        "final_file": "SESSION_CONTEXT_S168_FINAL.json",
        "pointer_updated": True,
        "manifest_fresh": True,
    }


@pytest.fixture
def stale_result():
    """execute_close_bundle STALE 응답 샘플."""
    return {
        "decision": "STALE",
        "reason": "CLOSE_BUNDLE_FAILED: hash mismatch",
        "errors": ["hash mismatch"],
    }


# ── T-01: emit_final_created_event PENDING 이벤트 생성 ─────────────────────

def test_T01_emit_creates_pending_event(tmp_event_dir, sample_final_path):
    """emit_final_created_event가 PENDING 상태 이벤트 파일을 생성한다."""
    import tools.sync_layer.event_store as es
    event = emit_final_created_event(168, sample_final_path)

    assert event["status"] == EVENT_STATUS_PENDING
    assert event["session"] == 168
    assert event["event_type"] == "FINAL_CREATED"
    assert event["emitted_by"] == "close_bundle"
    assert "event_id" in event

    event_file = es.FINAL_CREATED_EVENT_PATH
    assert event_file.exists()
    loaded = json.loads(event_file.read_text())
    assert loaded["status"] == EVENT_STATUS_PENDING


# ── T-02: load_pending_event PENDING 반환 ───────────────────────────────────

def test_T02_load_pending_event_returns_event(tmp_event_dir, sample_final_path):
    """PENDING 이벤트가 존재하면 반환한다."""
    import tools.sync_layer.event_store as es
    emit_final_created_event(168, sample_final_path)

    event = load_pending_event()
    assert event is not None
    assert event["session"] == 168
    assert event["status"] == EVENT_STATUS_PENDING


# ── T-03: load_pending_event CONSUMED이면 None ──────────────────────────────

def test_T03_load_pending_event_returns_none_when_consumed(tmp_event_dir, sample_final_path):
    """CONSUMED 이벤트는 load_pending_event가 None 반환."""
    import tools.sync_layer.event_store as es
    event = emit_final_created_event(168, sample_final_path)
    mark_event_consumed(event)

    result = load_pending_event()
    assert result is None


# ── T-04: mark_event_consumed 상태 변경 ─────────────────────────────────────

def test_T04_mark_event_consumed_updates_status(tmp_event_dir, sample_final_path):
    """mark_event_consumed가 CONSUMED로 상태를 갱신하고 consumed_at을 기록."""
    import tools.sync_layer.event_store as es
    event = emit_final_created_event(168, sample_final_path)
    ok = mark_event_consumed(event)

    assert ok is True
    assert event["status"] == EVENT_STATUS_CONSUMED
    assert "consumed_at" in event

    loaded = json.loads(es.FINAL_CREATED_EVENT_PATH.read_text())
    assert loaded["status"] == EVENT_STATUS_CONSUMED


# ── T-05: check_missed_event 로직 검증 ──────────────────────────────────────

def test_T05_check_missed_event_detects_stale_pointer():
    """pointer_session < target_session이면 True 반환."""
    assert check_missed_event(168, 167) is True
    assert check_missed_event(168, 168) is False
    assert check_missed_event(168, None) is False


# ── T-06: run_event_driven_sync — 이벤트 없음 ───────────────────────────────

def test_T06_event_driven_sync_no_event(tmp_event_dir, tmp_deploy_dir, sample_final_path):
    """PENDING 이벤트가 없으면 NO_EVENT 반환."""
    with patch("tools.sync_layer.sync_orchestrator.load_pending_event", return_value=None):
        result = run_event_driven_sync(168, sample_final_path)

    assert result["orchestration"] == ORCHESTRATION_NO_EVENT
    assert result["sync_result"] is None
    assert result["deploy_request_created"] is False
    assert result["manual_path_required"] is False


# ── T-07: run_event_driven_sync — 세션 불일치 ───────────────────────────────

def test_T07_event_driven_sync_session_mismatch(tmp_event_dir, tmp_deploy_dir, sample_final_path):
    """이벤트 세션과 요청 세션 불일치 시 SESSION_MISMATCH + manual_path_required."""
    stale_event = {
        "event_type": "FINAL_CREATED",
        "session": 167,  # 기대값 168과 불일치
        "status": EVENT_STATUS_PENDING,
    }
    with patch("tools.sync_layer.sync_orchestrator.load_pending_event", return_value=stale_event):
        result = run_event_driven_sync(168, sample_final_path)

    assert result["orchestration"] == ORCHESTRATION_SESSION_MISMATCH
    assert result["manual_path_required"] is True
    assert result["deploy_request_created"] is False


# ── T-08: run_event_driven_sync — COMMIT 성공 ───────────────────────────────

def test_T08_event_driven_sync_commit_success(
    tmp_event_dir, tmp_deploy_dir, sample_final_path, commit_result
):
    """COMMIT 응답 시 EVENT_DRIVEN + deploy_request_created=True."""
    pending_event = {"session": 168, "status": EVENT_STATUS_PENDING}

    with patch("tools.sync_layer.sync_orchestrator.load_pending_event", return_value=pending_event), \
         patch("tools.sync_layer.sync_orchestrator.execute_close_bundle", return_value=commit_result), \
         patch("tools.sync_layer.sync_orchestrator.mark_event_consumed"):

        result = run_event_driven_sync(168, sample_final_path)

    assert result["orchestration"] == ORCHESTRATION_EVENT_DRIVEN
    assert result["sync_result"]["decision"] == "COMMIT"
    assert result["deploy_request_created"] is True
    assert result["manual_path_required"] is False


# ── T-09: run_event_driven_sync — STALE 응답 ────────────────────────────────

def test_T09_event_driven_sync_stale_result(
    tmp_event_dir, tmp_deploy_dir, sample_final_path, stale_result
):
    """execute_close_bundle STALE 시 SYNC_STALE + manual_path_required."""
    pending_event = {"session": 168, "status": EVENT_STATUS_PENDING}

    with patch("tools.sync_layer.sync_orchestrator.load_pending_event", return_value=pending_event), \
         patch("tools.sync_layer.sync_orchestrator.execute_close_bundle", return_value=stale_result), \
         patch("tools.sync_layer.sync_orchestrator.mark_event_consumed"):

        result = run_event_driven_sync(168, sample_final_path)

    assert result["orchestration"] == ORCHESTRATION_SYNC_STALE
    assert result["manual_path_required"] is True
    assert result["deploy_request_created"] is False


# ── T-10: run_event_driven_sync — execute_close_bundle 예외 ─────────────────

def test_T10_event_driven_sync_exception_is_fail_closed(
    tmp_event_dir, tmp_deploy_dir, sample_final_path
):
    """execute_close_bundle 예외 시 SYNC_FAILED + manual_path_required (Fail-Closed)."""
    pending_event = {"session": 168, "status": EVENT_STATUS_PENDING}

    with patch("tools.sync_layer.sync_orchestrator.load_pending_event", return_value=pending_event), \
         patch("tools.sync_layer.sync_orchestrator.execute_close_bundle",
               side_effect=RuntimeError("POINTER_CREATION_FAILED")):

        result = run_event_driven_sync(168, sample_final_path)

    assert result["orchestration"] == ORCHESTRATION_SYNC_FAILED
    assert result["manual_path_required"] is True
    assert result["deploy_request_created"] is False
    assert "POINTER_CREATION_FAILED" in result.get("error", "")


# ── T-11: run_reconciliation — FINAL 없음 ───────────────────────────────────

def test_T11_reconciliation_no_final(tmp_deploy_dir, tmp_path):
    """FINAL 파일이 없으면 NO_FINAL 반환 (수동 개입 불필요)."""
    missing_path = tmp_path / "SESSION_CONTEXT_S168_FINAL.json"

    result = run_reconciliation(168, missing_path)

    assert result["reconciliation"] == RECONCILIATION_NO_FINAL
    assert result["manual_path_required"] is False
    assert result["deploy_request_created"] is False


# ── T-12: run_reconciliation — 이미 동기화됨 ────────────────────────────────

def test_T12_reconciliation_already_synced(tmp_deploy_dir, sample_final_path):
    """POINTER session == target_session이면 ALREADY_SYNCED."""
    with patch(
        "tools.sync_layer.sync_orchestrator._load_current_pointer_session",
        return_value=168,
    ):
        result = run_reconciliation(168, sample_final_path)

    assert result["reconciliation"] == RECONCILIATION_ALREADY_SYNCED
    assert result["manual_path_required"] is False
    assert result["deploy_request_created"] is False


# ── T-13: run_reconciliation — stale 감지 + COMMIT 성공 ─────────────────────

def test_T13_reconciliation_stale_commit_success(
    tmp_deploy_dir, sample_final_path, commit_result
):
    """stale 감지 후 execute_close_bundle COMMIT → STALE_DETECTED + deploy_request_created."""
    with patch(
        "tools.sync_layer.sync_orchestrator._load_current_pointer_session",
        return_value=167,  # 167 < 168 → stale
    ), patch(
        "tools.sync_layer.sync_orchestrator.execute_close_bundle",
        return_value=commit_result,
    ):
        result = run_reconciliation(168, sample_final_path)

    assert result["reconciliation"] == RECONCILIATION_STALE_DETECTED
    assert result["sync_result"]["decision"] == "COMMIT"
    assert result["deploy_request_created"] is True
    assert result["manual_path_required"] is False


# ── T-14: run_reconciliation — stale + execute_close_bundle 예외 ─────────────

def test_T14_reconciliation_stale_exception_is_fail_closed(
    tmp_deploy_dir, sample_final_path
):
    """stale 감지 후 execute_close_bundle 예외 → SYNC_FAILED + manual_path_required."""
    with patch(
        "tools.sync_layer.sync_orchestrator._load_current_pointer_session",
        return_value=167,
    ), patch(
        "tools.sync_layer.sync_orchestrator.execute_close_bundle",
        side_effect=FileNotFoundError("FINAL_FILE_MISSING"),
    ):
        result = run_reconciliation(168, sample_final_path)

    assert result["reconciliation"] == RECONCILIATION_SYNC_FAILED
    assert result["manual_path_required"] is True
    assert result["deploy_request_created"] is False
    assert "FINAL_FILE_MISSING" in result.get("error", "")


# ── T-15: get_orchestrator_status 구조 검증 ──────────────────────────────────

def test_T15_get_orchestrator_status_structure():
    """get_orchestrator_status가 필수 필드를 포함한다."""
    status = get_orchestrator_status()

    assert status["component"] == "sync_orchestrator"
    assert status["layer"] == "sync_layer"
    assert status["p3_task"] == "P3-T1"
    assert status["eag_authorized"] is True
    assert status["fail_closed"] is True
    assert status["manual_path_preserved"] is True
    assert "event_store" in status
    assert "deploy_request_path" in status

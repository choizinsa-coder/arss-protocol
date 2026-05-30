"""
test_binding_governance_monitor.py
P4-B Binding Governance Layer — binding_governance_monitor 검증
SSOT: Domi P4-B Design (S173) / EAG-1/2 Approved 비오(Joshua)
P4-C1 패치 (S174): TC-10 failure path 보강 (_save_index 실패 graceful 처리)

TC-1: run_once — 빈 index → acknowledged_count=0
TC-2: run_once — NEW alert 1건 → ACKNOWLEDGED 전환 + queue 등재
TC-3: run_once — ACKNOWLEDGED alert → 재전환 없음
TC-4: run_once — RESOLVED alert → 전환 없음
TC-5: run_once — NEW 1건 + ACKNOWLEDGED 1건 혼합 → NEW만 전환
TC-6: get_pending_observations — ACKNOWLEDGED queue 항목 반환
TC-7: get_monitor_status — 필수 필드 구조 검증
TC-8: _find_active_alert_entry — ACTIVE 상태 탐지 (binding_guard 연동)
TC-9: _find_active_alert_entry — RESOLVED 상태는 탐지 안 됨
TC-10: run_once — _save_index 실패(False) 시 acknowledged_ids 정상 반환 (RULE-8 failure path)
"""

import sys
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.sync_layer.governance.binding_governance_monitor import (
    run_once,
    get_pending_observations,
    get_monitor_status,
    _load_index,
    _save_index,
    _load_action_queue,
    _acknowledge_alert,
    _build_queue_entry,
)
from tools.sync_layer.transport.binding_guard import (
    _find_active_alert_entry,
    ACTIVE_ALERT_STATUSES,
)


# ── 픽스처 ─────────────────────────────────────────────────────────────────

def _make_index(alerts: list) -> dict:
    return {"version": "1.0", "last_updated": "2026-05-30T00:00:00+09:00", "alerts": alerts}


def _make_queue(entries: list) -> dict:
    return {"version": "1.0", "last_updated": "2026-05-30T00:00:00+09:00", "queue": entries}


def _make_alert(alert_id: str, endpoint_id: str, status: str) -> dict:
    return {
        "alert_id": alert_id,
        "endpoint_id": endpoint_id,
        "url": f"http://localhost:5678/webhook/{endpoint_id.lower()}",
        "reason": "WEBHOOK_NOT_REGISTERED",
        "status": status,
        "created_at": "2026-05-30T12:00:00+09:00",
        "last_seen_at": "2026-05-30T12:00:00+09:00",
        "duplicate_count": 0,
        "file_path": f"registry/binding_alerts/{alert_id}.json",
    }


# ── TC-1: 빈 index → no-op ──────────────────────────────────────────────────

def test_tc1_run_once_empty_index():
    empty_index = _make_index([])
    empty_queue = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=empty_index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=empty_queue), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index") as mock_save_idx, \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_action_queue") as mock_save_q:
        result = run_once()
    assert result["acknowledged_count"] == 0
    assert result["acknowledged_ids"] == []
    assert result["total_alerts"] == 0
    mock_save_idx.assert_not_called()
    mock_save_q.assert_not_called()


# ── TC-2: NEW alert → ACKNOWLEDGED 전환 + queue 등재 ──────────────────────

def test_tc2_run_once_new_alert_transitions():
    alert = _make_alert("ALERT_001", "DEPLOYMENT_EVENT", "NEW")
    index = _make_index([alert])
    queue_data = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index") as mock_save_idx, \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_action_queue") as mock_save_q:
        result = run_once()
    assert result["acknowledged_count"] == 1
    assert "ALERT_001" in result["acknowledged_ids"]
    assert alert["status"] == "ACKNOWLEDGED"
    assert "acknowledged_at" in alert
    assert len(queue_data["queue"]) == 1
    assert queue_data["queue"][0]["alert_id"] == "ALERT_001"
    mock_save_idx.assert_called_once()
    mock_save_q.assert_called_once()


# ── TC-3: ACKNOWLEDGED alert → 재전환 없음 ────────────────────────────────

def test_tc3_run_once_already_acknowledged():
    alert = _make_alert("ALERT_002", "SYNC_EVENT", "ACKNOWLEDGED")
    index = _make_index([alert])
    queue_data = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index") as mock_save_idx:
        result = run_once()
    assert result["acknowledged_count"] == 0
    assert alert["status"] == "ACKNOWLEDGED"
    mock_save_idx.assert_not_called()


# ── TC-4: RESOLVED alert → 전환 없음 ─────────────────────────────────────

def test_tc4_run_once_resolved_alert():
    alert = _make_alert("ALERT_003", "DEPLOYMENT_EVENT", "RESOLVED")
    index = _make_index([alert])
    queue_data = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index") as mock_save_idx:
        result = run_once()
    assert result["acknowledged_count"] == 0
    assert alert["status"] == "RESOLVED"
    mock_save_idx.assert_not_called()


# ── TC-5: NEW + ACKNOWLEDGED 혼합 → NEW만 전환 ────────────────────────────

def test_tc5_run_once_mixed_alerts():
    alert_new = _make_alert("ALERT_004", "DEPLOYMENT_EVENT", "NEW")
    alert_ack = _make_alert("ALERT_005", "SYNC_EVENT", "ACKNOWLEDGED")
    index = _make_index([alert_new, alert_ack])
    queue_data = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index"), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_action_queue"):
        result = run_once()
    assert result["acknowledged_count"] == 1
    assert alert_new["status"] == "ACKNOWLEDGED"
    assert alert_ack["status"] == "ACKNOWLEDGED"  # 변경 없음
    assert len(queue_data["queue"]) == 1
    assert queue_data["queue"][0]["alert_id"] == "ALERT_004"


# ── TC-6: get_pending_observations — ACKNOWLEDGED 항목 반환 ───────────────

def test_tc6_get_pending_observations():
    entries = [
        {"alert_id": "A1", "status": "ACKNOWLEDGED"},
        {"alert_id": "A2", "status": "ACKNOWLEDGED"},
    ]
    queue_data = _make_queue(entries)
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data):
        result = get_pending_observations()
    assert len(result) == 2
    assert all(e["status"] == "ACKNOWLEDGED" for e in result)


# ── TC-7: get_monitor_status 구조 검증 ────────────────────────────────────

def test_tc7_get_monitor_status():
    status = get_monitor_status()
    assert status["component"] == "binding_governance_monitor"
    assert status["layer"] == "sync_layer/governance"
    assert status["p4_task"] == "P4-B"
    assert status["queue_consumer"] == "Caddy"
    assert status["auto_eag_pending"] is False
    assert status["fail_closed"] is True
    assert "alert_index_path" in status
    assert "action_queue_path" in status


# ── TC-8: _find_active_alert_entry — ACTIVE 상태 탐지 ─────────────────────

def test_tc8_find_active_alert_entry_active():
    for status in ("NEW", "ACKNOWLEDGED", "EAG_PENDING"):
        index = _make_index([_make_alert("ALERT_X", "DEPLOYMENT_EVENT", status)])
        result = _find_active_alert_entry(index, "DEPLOYMENT_EVENT")
        assert result is not None, f"status={status} 탐지 실패"
        assert result["status"] == status


# ── TC-9: _find_active_alert_entry — RESOLVED/EXPIRED → None ─────────────

def test_tc9_find_active_alert_entry_terminal():
    for status in ("RESOLVED", "EXPIRED"):
        index = _make_index([_make_alert("ALERT_Y", "DEPLOYMENT_EVENT", status)])
        result = _find_active_alert_entry(index, "DEPLOYMENT_EVENT")
        assert result is None, f"status={status} 는 ACTIVE가 아님"


# ── TC-10: _save_index 실패 시 graceful 처리 (RULE-8 failure path) ─────────

def test_tc10_run_once_save_failure_graceful():
    """_save_index 실패(False 반환) 시에도 run_once acknowledged_ids 정상 반환 (RULE-8 failure path)"""
    alert = _make_alert("ALERT_010", "DEPLOYMENT_EVENT", "NEW")
    index = _make_index([alert])
    queue_data = _make_queue([])
    with patch("tools.sync_layer.governance.binding_governance_monitor._load_index", return_value=index), \
         patch("tools.sync_layer.governance.binding_governance_monitor._load_action_queue", return_value=queue_data), \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_index", return_value=False) as mock_save_idx, \
         patch("tools.sync_layer.governance.binding_governance_monitor._save_action_queue", return_value=False):
        result = run_once()
    # 저장 실패에도 acknowledged_ids는 정상 반환 (외부 I/O 실패는 내부 전환 상태에 영향 없음)
    assert result["acknowledged_count"] == 1
    assert "ALERT_010" in result["acknowledged_ids"]
    mock_save_idx.assert_called_once()

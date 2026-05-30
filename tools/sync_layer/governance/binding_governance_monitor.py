"""
binding_governance_monitor.py
AIBA Sync Layer — Binding Governance Monitor (P4-B)
SSOT: Domi P4-B Design (S173) / EAG-1 Approved 비오(Joshua)

역할:
  - registry/binding_alerts/index.json polling
  - NEW → ACKNOWLEDGED 전환 (Detection/Governance 계층 분리)
  - governance_action_queue 기록 (Caddy Observation 대기열)

원칙:
  Detection(binding_guard) ≠ Governance Decision ≠ Endpoint Mutation
  Queue Consumer = Caddy (GAP-P4B-001 확정)
  자동 EAG_PENDING 전환 금지
  Deadlock 방지: Alert 존재가 Transport 전체를 Block하지 않음

금지:
  - transport_endpoints.json 자동 갱신
  - EAG_PENDING 자동 전환
  - Endpoint Mutation
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
ALERT_INDEX_PATH = VPS_ROOT / "registry" / "binding_alerts" / "index.json"
ACTION_QUEUE_PATH = VPS_ROOT / "registry" / "binding_alerts" / "action_queue.json"

ACTIVE_STATUSES = {"NEW", "ACKNOWLEDGED", "EAG_PENDING"}
TERMINAL_STATUSES = {"RESOLVED", "EXPIRED"}


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _now_kst() -> str:
    """현재 KST ISO8601 반환. CC=1"""
    return datetime.now(KST).isoformat()


def _load_json(path: Path, default: dict) -> dict:
    """JSON 파일 로드. 실패 시 default 반환. CC=2"""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("LOAD_FAILED: %s — %s", path, exc)
        return default


def _save_json(path: Path, data: dict) -> bool:
    """JSON 파일 저장. 성공 시 True. CC=2"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        logger.error("SAVE_FAILED: %s — %s", path, exc)
        return False


def _load_index() -> dict:
    """Alert index 로드. CC=1"""
    default = {"version": "1.0", "last_updated": _now_kst(), "alerts": []}
    return _load_json(ALERT_INDEX_PATH, default)


def _save_index(index: dict) -> bool:
    """Alert index 저장. last_updated 갱신 포함. CC=1"""
    index["last_updated"] = _now_kst()
    return _save_json(ALERT_INDEX_PATH, index)


def _load_action_queue() -> dict:
    """Action queue 로드. CC=1"""
    default = {"version": "1.0", "last_updated": _now_kst(), "queue": []}
    return _load_json(ACTION_QUEUE_PATH, default)


def _save_action_queue(queue_data: dict) -> bool:
    """Action queue 저장. last_updated 갱신 포함. CC=1"""
    queue_data["last_updated"] = _now_kst()
    return _save_json(ACTION_QUEUE_PATH, queue_data)


def _acknowledge_alert(alert: dict) -> None:
    """
    Alert 상태 NEW → ACKNOWLEDGED 전환.
    binding_governance_monitor 책임 (GAP-P4B-002 확정).
    CC=1
    """
    alert["status"] = "ACKNOWLEDGED"
    alert["acknowledged_at"] = _now_kst()


def _build_queue_entry(alert: dict) -> dict:
    """Action queue 항목 생성. CC=1"""
    return {
        "alert_id": alert.get("alert_id", ""),
        "endpoint_id": alert.get("endpoint_id", ""),
        "url": alert.get("url", ""),
        "reason": alert.get("reason", ""),
        "status": "ACKNOWLEDGED",
        "queued_at": _now_kst(),
        "instruction": (
            "Caddy 관측 → 비오(Joshua) EAG 승인 후 Endpoint 변경 절차 진행. "
            "자동 EAG_PENDING 전환 금지."
        ),
    }


# ── 메인 진입점 ─────────────────────────────────────────────────────────────

def run_once() -> dict:
    """
    Polling 1회 실행.
    index.json에서 NEW 상태 Alert 감지 → ACKNOWLEDGED 전환 → action_queue 기록.
    자동 EAG_PENDING 전환 금지 (GAP-P4B-001 확정).
    CC=5
    """
    index = _load_index()
    alerts = index.get("alerts", [])
    queue_data = _load_action_queue()

    acknowledged = []
    for alert in alerts:
        if alert.get("status") != "NEW":
            continue
        _acknowledge_alert(alert)
        queue_data["queue"].append(_build_queue_entry(alert))
        acknowledged.append(alert.get("alert_id", ""))
        logger.info(
            "ALERT_ACKNOWLEDGED: alert_id=%s endpoint_id=%s",
            alert.get("alert_id", ""),
            alert.get("endpoint_id", ""),
        )

    if acknowledged:
        _save_index(index)
        _save_action_queue(queue_data)
        logger.info("MONITOR_RUN_ONCE: %d alert(s) acknowledged", len(acknowledged))

    return {
        "acknowledged_count": len(acknowledged),
        "acknowledged_ids": acknowledged,
        "total_alerts": len(alerts),
        "run_at": _now_kst(),
    }


def get_pending_observations() -> list:
    """
    Caddy Observation 대기열 조회.
    governance_action_queue에서 ACKNOWLEDGED 항목 반환.
    CC=2
    """
    queue_data = _load_action_queue()
    return [
        entry for entry in queue_data.get("queue", [])
        if entry.get("status") == "ACKNOWLEDGED"
    ]


def get_monitor_status() -> dict:
    """모니터 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "binding_governance_monitor",
        "layer": "sync_layer/governance",
        "p4_task": "P4-B",
        "alert_index_path": str(ALERT_INDEX_PATH),
        "action_queue_path": str(ACTION_QUEUE_PATH),
        "active_statuses": sorted(ACTIVE_STATUSES),
        "terminal_statuses": sorted(TERMINAL_STATUSES),
        "queue_consumer": "Caddy",
        "auto_eag_pending": False,
        "fail_closed": True,
    }

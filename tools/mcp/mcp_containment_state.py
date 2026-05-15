"""
mcp_containment_state.py
HARD_CONTAINMENT Recovery Protocol v1.2
Task:  PT-S125-BOOT-ONDEMAND-001 Recovery Governance Layer
EAG:   EAG-3 비오(Joshua) 승인 (S130)
설계:  도미 FINAL ANCHOR (S130)

책임:
- HARD_CONTAINMENT 상태 관리 (local file canonical authority)
- FAIL_CLOSED default: 파일 없음/parse 실패 시 containment_active=True
- 재시작 시 containment 상태 복원 (mandatory)
- chmod 600 적용
- 자동 해제 금지 (auto-release FORBIDDEN)

State Topology:
  NORMAL -> HARD_CONTAINMENT -> RECOVERY_OBSERVATION_MODE -> NORMAL
"""

from __future__ import annotations

import json
import os
import stat
import time
import uuid
from typing import Optional

# ── 상수 ──────────────────────────────────────────────────────────────────────

CONTAINMENT_STATE_PATH = (
    "/opt/arss/engine/arss-protocol/tools/mcp/mcp_containment_state.json"
)

RECOVERY_STATUS_LOCKED = "LOCKED"
RECOVERY_STATUS_IN_PROGRESS = "IN_PROGRESS"
RECOVERY_STATUS_OBSERVATION = "RECOVERY_OBSERVATION_MODE"

VALID_TRIGGER_IDS = frozenset({
    "HC-T-01", "HC-T-02", "HC-T-03",
    "HC-T-04", "HC-T-05", "HC-T-06", "HC-T-07",
})


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _generate_incident_id() -> str:
    suffix = uuid.uuid4().hex[:8].upper()
    return f"HC-INC-{suffix}"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime())


def _apply_permissions(path: str) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _fail_closed_state(reason: str = "FAIL_CLOSED_DEFAULT") -> dict:
    return {
        "containment_active": True,
        "trigger_id": "UNKNOWN",
        "entered_at": _now_iso(),
        "incident_id": _generate_incident_id(),
        "recovery_status": RECOVERY_STATUS_LOCKED,
        "fail_closed_reason": reason,
    }


# ── 상태 Read/Write ────────────────────────────────────────────────────────────

def load_state(path: str = CONTAINMENT_STATE_PATH) -> dict:
    """
    containment 상태 파일 로드.
    파일 없음 / parse 실패 / 구조 이상 -> FAIL_CLOSED.
    """
    if not os.path.exists(path):
        return _fail_closed_state("STATE_FILE_MISSING")

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, ValueError):
        return _fail_closed_state("STATE_FILE_PARSE_ERROR")

    required_keys = {"containment_active", "trigger_id", "entered_at",
                     "incident_id", "recovery_status"}
    if not required_keys.issubset(data.keys()):
        return _fail_closed_state("STATE_FILE_SCHEMA_ERROR")

    if not isinstance(data.get("containment_active"), bool):
        return _fail_closed_state("STATE_FILE_TYPE_ERROR")

    return data


def save_state(state: dict, path: str = CONTAINMENT_STATE_PATH) -> bool:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        _apply_permissions(path)
        return True
    except OSError:
        return False


# ── 공개 API ──────────────────────────────────────────────────────────────────

def is_active(path: str = CONTAINMENT_STATE_PATH) -> bool:
    """containment 활성 여부. 파일 없음/parse 실패 -> FAIL_CLOSED -> True."""
    state = load_state(path)
    return bool(state.get("containment_active", True))


def get_state(path: str = CONTAINMENT_STATE_PATH) -> dict:
    """현재 containment 상태 반환 (readonly)."""
    return load_state(path)


def enter_containment(
    trigger_id: str,
    path: str = CONTAINMENT_STATE_PATH,
) -> dict:
    """
    HARD_CONTAINMENT 진입.
    재진입 = NEW INCIDENT (trust 상속 금지).
    자동 해제 FORBIDDEN.
    """
    if trigger_id not in VALID_TRIGGER_IDS:
        trigger_id = "UNKNOWN"

    new_state = {
        "containment_active": True,
        "trigger_id": trigger_id,
        "entered_at": _now_iso(),
        "incident_id": _generate_incident_id(),
        "recovery_status": RECOVERY_STATUS_LOCKED,
    }
    save_state(new_state, path)
    return new_state


def enter_observation_mode(
    path: str = CONTAINMENT_STATE_PATH,
) -> dict:
    """
    RECOVERY_OBSERVATION_MODE 전환 (RC-P-08 호출용).
    비오 RC-P-07 승인 이후에만 호출.
    containment_active=True 유지 (auto-release FORBIDDEN).
    """
    state = load_state(path)
    state["recovery_status"] = RECOVERY_STATUS_OBSERVATION
    state["observation_entered_at"] = _now_iso()
    save_state(state, path)
    return state


def release_containment(
    path: str = CONTAINMENT_STATE_PATH,
) -> dict:
    """
    HARD_CONTAINMENT 해제.
    자동 호출 FORBIDDEN — 비오 수동 승인 경로에서만 사용.
    """
    state = load_state(path)
    state["containment_active"] = False
    state["recovery_status"] = "RELEASED"
    state["released_at"] = _now_iso()
    save_state(state, path)
    return state


def update_recovery_status(
    status: str,
    path: str = CONTAINMENT_STATE_PATH,
) -> dict:
    """RC-P 진행 중 상태 갱신."""
    state = load_state(path)
    state["recovery_status"] = status
    state["status_updated_at"] = _now_iso()
    save_state(state, path)
    return state


def read_containment_state(path: str = CONTAINMENT_STATE_PATH) -> dict:
    """HC-A-02: containment state read (readonly whitelist 허용 동작)."""
    return get_state(path)

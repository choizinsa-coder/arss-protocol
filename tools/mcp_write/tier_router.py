"""
tier_router.py — MCP Write Plane Tier Router v1.0.0
EAG-1 (S164): Write Plane Restore

역할:
  - Write Plane 4-state 관리 (NORMAL / LOCKED_TIER1 / LOCKED_ALL / RECOVERY)
  - 경로 기반 Tier1 / Tier2 분류
  - 상태 + 경로 결합 라우팅 결정

설계 근거:
  - LOCKED_TIER1: Tier1 차단, Tier2 허용 (Sandbox 작업 지속 가능)
  - LOCKED_ALL: 전체 차단
  - os.path.realpath 사용으로 symlink / .. 우회 차단 (제니 TRUST-ADVISORY 반영)
  - 상태 저장: registry/mcp_write/state/plane_state.json (SSOT)
"""

import json
import os
import sys
import threading
from datetime import datetime, timezone
from enum import Enum

_ROOT = "/opt/arss/engine/arss-protocol"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

STATE_FILE = f"{_ROOT}/registry/mcp_write/state/plane_state.json"

SANDBOX_PATHS = [
    os.path.realpath(f"{_ROOT}/tools/sandbox"),
    os.path.realpath(f"{_ROOT}/tools/tmp"),
    os.path.realpath(f"{_ROOT}/tests/sandbox"),
]

_state_lock = threading.Lock()


# ── Enums ──────────────────────────────────────────────────────────────

class WritePlaneState(Enum):
    NORMAL = "NORMAL"
    LOCKED_TIER1 = "LOCKED_TIER1"   # Tier1 중단, Tier2 허용
    LOCKED_ALL = "LOCKED_ALL"        # 전체 정지
    RECOVERY = "RECOVERY"             # 복구 모드


class TierClassification(Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"


# ── Exceptions ────────────────────────────────────────────────────────

class WritePlaneLockedError(Exception):
    """Write Plane 잠금 상태로 인한 거부."""
    def __init__(self, reason: str, state: str):
        self.reason = reason
        self.state = state
        super().__init__(f"WritePlane DENY [{state}]: {reason}")


# ── 상태 영속화 ───────────────────────────────────────────────────────

def _load_state() -> WritePlaneState:
    """상태 파일 로드. 없거나 손상 시 NORMAL 반환 (Fail-Safe)."""
    if not os.path.exists(STATE_FILE):
        return WritePlaneState.NORMAL
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return WritePlaneState(data.get("state", "NORMAL"))
    except Exception:
        return WritePlaneState.NORMAL


def _persist_state(state: WritePlaneState, reason: str = "") -> None:
    """상태를 파일에 저장 (호출자가 _state_lock 보유 중이어야 함)."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    data = {
        "state": state.value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    }
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── 공개 상태 API ─────────────────────────────────────────────────────

def get_write_plane_state() -> WritePlaneState:
    """현재 Write Plane 상태 반환."""
    with _state_lock:
        return _load_state()


def set_write_plane_state(state: WritePlaneState, reason: str = "") -> None:
    """
    Write Plane 상태 변경.
    호출 권한: 비오(Beo) 명령 경로 또는 Lifecycle Manager Fail-Closed 경로만 허용.
    """
    with _state_lock:
        _persist_state(state, reason)


# ── Tier 분류 ─────────────────────────────────────────────────────────

def classify_tier(target_path: str) -> TierClassification:
    """
    경로 기반 Tier 분류.
    sandbox 경로 내부 → TIER2
    그 외 → TIER1

    os.path.realpath 사용으로 symlink / .. 우회 차단.
    (제니 TRUST-ADVISORY: EAG-2 구현 주의사항 선반영)
    """
    try:
        real_path = os.path.realpath(os.path.abspath(target_path))
    except Exception:
        return TierClassification.TIER1

    for sandbox in SANDBOX_PATHS:
        real_sandbox = os.path.realpath(sandbox)
        if real_path == real_sandbox or real_path.startswith(real_sandbox + os.sep):
            return TierClassification.TIER2

    return TierClassification.TIER1


# ── 라우팅 결정 ───────────────────────────────────────────────────────

def route_request(target_path: str) -> TierClassification:
    """
    현재 상태 + 경로 기반으로 최종 라우팅 결정.

    상태별 동작:
      LOCKED_ALL      → 전체 차단 (TIER1 / TIER2 모두 거부)
      LOCKED_TIER1    → TIER1 차단, TIER2 통과
      NORMAL/RECOVERY → 경로 분류 결과 그대로 라우팅
    """
    state = get_write_plane_state()
    tier = classify_tier(target_path)

    if state == WritePlaneState.LOCKED_ALL:
        raise WritePlaneLockedError(
            "LOCKED_ALL — 전체 Write 차단. 비오님 해제 필요.",
            state=state.value,
        )

    if state == WritePlaneState.LOCKED_TIER1 and tier == TierClassification.TIER1:
        raise WritePlaneLockedError(
            "LOCKED_TIER1 — Tier1 Write 차단. Pending receipt 처리 후 해제 가능.",
            state=state.value,
        )

    return tier

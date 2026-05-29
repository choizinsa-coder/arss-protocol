"""
event_store.py
AIBA Sync Layer — File-backed Event Store
SSOT: Domi Phase 3 Design (S168) / EAG-1 Approved (비오(Joshua))

역할:
  - FINAL_CREATED_EVENT 생성/읽기/소비 (File-backed)
  - event/ 디렉터리 관리
  - Missed Event 방지 (fsync 기반 영속성 보장)

설계 근거 (GAP-2 해소):
  - 생성 주체: Session Close Bundle (context_writer 아님)
  - 전달 방식: File-backed (in-memory / webhook 배제 — 유실 방지)
  - Missed Event: Periodic Reconciliation으로 최종 복구

금지:
  - context_writer.py 인터페이스 변경
  - 이 모듈에서 execute_close_bundle 직접 호출
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
EVENT_DIR = VPS_ROOT / "event"
FINAL_CREATED_EVENT_PATH = EVENT_DIR / "FINAL_CREATED_EVENT.json"
KST = timezone(timedelta(hours=9))

EVENT_STATUS_PENDING = "PENDING"
EVENT_STATUS_CONSUMED = "CONSUMED"
EVENT_STATUS_MISSED = "MISSED"


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _fsync_write(path: Path, content: str) -> bool:
    """
    파일 쓰기 + fsync 시도.
    fsync 실패는 비치명(non-fatal) — False 반환 후 caller가 처리.

    반환: True = 파일 쓰기 + fsync 성공
          False = 파일은 쓰였으나 fsync 실패 또는 쓰기 자체 실패
    """
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
                return True
            except OSError as exc:
                logger.warning(
                    "FSYNC_DEGRADED: path=%s — %s. File written but OS sync not confirmed.",
                    path, exc,
                )
                return False
    except OSError as exc:
        logger.error("FILE_WRITE_FAILED: path=%s — %s", path, exc)
        return False


def _build_event_id(session: int, final_path: Path) -> str:
    """이벤트 고유 ID 생성."""
    raw = f"{session}:{final_path}"
    return f"evt_{session}_{hashlib.sha256(raw.encode()).hexdigest()[:8]}"


# ── 공개 API ────────────────────────────────────────────────────────────────

def ensure_event_dir() -> None:
    """event/ 디렉터리가 없으면 생성."""
    EVENT_DIR.mkdir(parents=True, exist_ok=True)


def emit_final_created_event(session: int, final_path: Path) -> dict:
    """
    FINAL_CREATED_EVENT 파일을 생성하고 저장한다.

    호출 주체: Session Close Bundle (GAP-2 결정)
    저장 위치: event/FINAL_CREATED_EVENT.json

    반환: 생성된 이벤트 dict
    """
    ensure_event_dir()
    event = {
        "event_type": "FINAL_CREATED",
        "session": session,
        "final_file": final_path.name,
        "final_path": str(final_path),
        "emitted_by": "close_bundle",
        "emitted_at": datetime.now(KST).isoformat(),
        "status": EVENT_STATUS_PENDING,
        "event_id": _build_event_id(session, final_path),
    }
    fsync_ok = _fsync_write(
        FINAL_CREATED_EVENT_PATH,
        json.dumps(event, ensure_ascii=False, indent=2),
    )
    if not fsync_ok:
        event["fsync_warning"] = "EMIT_FSYNC_DEGRADED"
        logger.warning("EMIT_FSYNC_DEGRADED: session=%s", session)
    return event


def load_pending_event() -> Optional[dict]:
    """
    PENDING 상태의 FINAL_CREATED_EVENT를 반환한다.
    파일 없거나 CONSUMED/MISSED 상태면 None 반환.

    반환: PENDING 이벤트 dict | None
    """
    if not FINAL_CREATED_EVENT_PATH.exists():
        return None
    try:
        raw = FINAL_CREATED_EVENT_PATH.read_text(encoding="utf-8")
        event = json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("EVENT_LOAD_FAILED: %s", exc)
        return None

    if event.get("status") == EVENT_STATUS_PENDING:
        return event
    return None


def mark_event_consumed(event: dict) -> bool:
    """
    이벤트를 CONSUMED 상태로 갱신하고 fsync 저장.

    반환: 저장 성공 여부 (fsync 실패 포함)
    """
    event["status"] = EVENT_STATUS_CONSUMED
    event["consumed_at"] = datetime.now(KST).isoformat()
    return _fsync_write(
        FINAL_CREATED_EVENT_PATH,
        json.dumps(event, ensure_ascii=False, indent=2),
    )


def check_missed_event(target_session: int, pointer_session: Optional[int]) -> bool:
    """
    이벤트 유실(Missed Event) 여부 판정.
    POINTER가 target_session보다 낮으면 missed로 판단.

    반환: True = 이벤트 유실 가능성 있음 (Reconciliation 필요)
    """
    if pointer_session is None:
        return False
    return pointer_session < target_session


def get_event_store_status() -> dict:
    """이벤트 스토어 현재 상태 요약 (관측/감사용)."""
    event_exists = FINAL_CREATED_EVENT_PATH.exists()
    current_status = None
    if event_exists:
        try:
            raw = json.loads(FINAL_CREATED_EVENT_PATH.read_text(encoding="utf-8"))
            current_status = raw.get("status")
        except (json.JSONDecodeError, OSError):
            current_status = "UNREADABLE"

    return {
        "component": "event_store",
        "layer": "sync_layer",
        "p3_task": "P3-T1",
        "event_dir": str(EVENT_DIR),
        "event_file": str(FINAL_CREATED_EVENT_PATH),
        "event_file_exists": event_exists,
        "current_event_status": current_status,
    }

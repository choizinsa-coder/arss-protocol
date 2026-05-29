"""
sync_orchestrator.py
AIBA Sync Layer — Sync Orchestrator
SSOT: Domi Phase 3 Design (S168) / EAG-1 Approved (비오(Joshua))

역할:
  - FINAL_CREATED_EVENT 소비 → execute_close_bundle 호출 → Deploy Request 생성
  - Periodic Reconciliation: FINAL 존재 + POINTER 미동기화 감지 → 자동 복구
  - 실패 시 Fail-Closed + 수동 경로 유지 (SPOF 방지)

핵심 흐름:
  [이벤트 기반]
  FINAL_CREATED_EVENT(PENDING) → run_event_driven_sync()
  → execute_close_bundle() → DEPLOY_REQUEST 생성

  [Periodic Reconciliation]
  FINAL 존재 + POINTER.session < target_session → run_reconciliation()
  → execute_close_bundle() → DEPLOY_REQUEST 생성

  [공통 실패 정책]
  어떤 단계에서도 실패 → manual_path_required=True 반환
  수동 SCP + 수동 업로드 경로 항상 유지

제약:
  - context_writer.execute_close_bundle 인터페이스 변경 금지
  - POINTER / MANIFEST 직접 쓰기 금지 (context_writer 독점)
  - Deploy Request = P3-T2 Deploy Gate 입력 아티팩트
"""

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tools.context_gateway.context_writer import execute_close_bundle
from tools.context_gateway.pointer_manager import load_pointer
from tools.sync_layer.event_store import (
    load_pending_event,
    mark_event_consumed,
    check_missed_event,
    get_event_store_status,
)

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
EVENT_DIR = VPS_ROOT / "event"
DEPLOY_REQUEST_PATH = EVENT_DIR / "DEPLOY_REQUEST.json"
KST = timezone(timedelta(hours=9))

ORCHESTRATION_EVENT_DRIVEN = "EVENT_DRIVEN"
ORCHESTRATION_NO_EVENT = "NO_EVENT"
ORCHESTRATION_SESSION_MISMATCH = "SESSION_MISMATCH"
ORCHESTRATION_SYNC_STALE = "SYNC_STALE"
ORCHESTRATION_SYNC_FAILED = "SYNC_FAILED"

RECONCILIATION_STALE_DETECTED = "STALE_DETECTED"
RECONCILIATION_ALREADY_SYNCED = "ALREADY_SYNCED"
RECONCILIATION_NO_FINAL = "NO_FINAL"
RECONCILIATION_SYNC_FAILED = "SYNC_FAILED"


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _fsync_write(path: Path, content: str) -> bool:
    """파일 쓰기 + fsync. 실패 시 False 반환."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
                return True
            except OSError as exc:
                logger.warning("FSYNC_DEGRADED: path=%s — %s", path, exc)
                return False
    except OSError as exc:
        logger.error("FILE_WRITE_FAILED: path=%s — %s", path, exc)
        return False


def _load_current_pointer_session() -> Optional[int]:
    """
    현재 POINTER의 canonical_session 반환.
    로드 실패 시 None 반환 (Fail-Closed 처리는 caller 담당).
    """
    try:
        pointer = load_pointer()
        return pointer.get("canonical_session")
    except Exception as exc:
        logger.warning("POINTER_LOAD_FAILED: %s", exc)
        return None


def _detect_stale_sync(session: int, final_path: Path) -> bool:
    """
    FINAL 파일이 존재하고 POINTER가 해당 세션보다 오래되었으면 True.
    Periodic Reconciliation 핵심 판단 로직.
    """
    if not final_path.exists():
        return False
    pointer_session = _load_current_pointer_session()
    if pointer_session is None:
        # POINTER 로드 불가 = 동기화 필요로 간주
        return True
    return pointer_session < session


def _generate_deploy_request(session: int, sync_result: dict) -> bool:
    """
    Sync 성공 후 Deploy Request를 생성한다 (→ P3-T2 Deploy Gate 입력).
    반환: 파일 쓰기 성공 여부
    """
    EVENT_DIR.mkdir(parents=True, exist_ok=True)
    deploy_request = {
        "request_type": "DEPLOY_REQUEST",
        "session": session,
        "sync_decision": sync_result.get("decision"),
        "final_file": sync_result.get("final_file"),
        "pointer_updated": sync_result.get("pointer_updated", False),
        "manifest_fresh": sync_result.get("manifest_fresh", False),
        "requested_at": datetime.now(KST).isoformat(),
        "requested_by": "sync_orchestrator",
        "status": "PENDING_GATE",
        "p3_task": "P3-T1",
    }
    return _fsync_write(
        DEPLOY_REQUEST_PATH,
        json.dumps(deploy_request, ensure_ascii=False, indent=2),
    )


def _build_manual_path_response(orchestration_key: str, reason: str, error: str = "") -> dict:
    """수동 경로 필요 응답 공통 빌더."""
    result = {
        orchestration_key: ORCHESTRATION_SYNC_FAILED
        if "FAIL" in orchestration_key.upper()
        else orchestration_key,
        "sync_result": None,
        "deploy_request_created": False,
        "manual_path_required": True,
        "reason": reason,
    }
    if error:
        result["error"] = error
    return result


# ── 이벤트 기반 동기화 ──────────────────────────────────────────────────────

def run_event_driven_sync(session: int, final_path: Path) -> dict:
    """
    이벤트 기반 동기화 진입점.
    FINAL_CREATED_EVENT(PENDING)를 소비하고 Close Bundle을 실행한다.

    반환: {
        "orchestration": str,
        "sync_result": dict | None,
        "deploy_request_created": bool,
        "manual_path_required": bool,
        ...
    }
    """
    event = load_pending_event()
    if event is None:
        return {
            "orchestration": ORCHESTRATION_NO_EVENT,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": False,
        }

    if event.get("session") != session:
        logger.warning(
            "EVENT_SESSION_MISMATCH: event.session=%s expected=%s",
            event.get("session"), session,
        )
        return {
            "orchestration": ORCHESTRATION_SESSION_MISMATCH,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": True,
            "reason": f"event.session={event.get('session')} != expected={session}",
        }

    return _execute_sync_with_event(session, final_path, event)


def _execute_sync_with_event(session: int, final_path: Path, event: dict) -> dict:
    """이벤트 소비 → execute_close_bundle → Deploy Request 생성."""
    try:
        sync_result = execute_close_bundle(session=session, final_path=final_path)
    except Exception as exc:
        logger.error("SYNC_EXECUTE_FAILED: session=%s error=%s", session, exc)
        return {
            "orchestration": ORCHESTRATION_SYNC_FAILED,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": True,
            "error": str(exc),
        }

    mark_event_consumed(event)

    if sync_result.get("decision") != "COMMIT":
        logger.warning(
            "SYNC_STALE: session=%s reason=%s",
            session, sync_result.get("reason"),
        )
        return {
            "orchestration": ORCHESTRATION_SYNC_STALE,
            "sync_result": sync_result,
            "deploy_request_created": False,
            "manual_path_required": True,
        }

    deploy_ok = _generate_deploy_request(session, sync_result)
    return {
        "orchestration": ORCHESTRATION_EVENT_DRIVEN,
        "sync_result": sync_result,
        "deploy_request_created": deploy_ok,
        "manual_path_required": not deploy_ok,
    }


# ── Periodic Reconciliation ─────────────────────────────────────────────────

def run_reconciliation(session: int, final_path: Path) -> dict:
    """
    Periodic Reconciliation 실행.
    이벤트 유실 시에도 FINAL + POINTER 불일치를 감지하고 동기화한다.
    (Eventual Consistency 보장 안전망)

    반환: {
        "reconciliation": str,
        "sync_result": dict | None,
        "deploy_request_created": bool,
        "manual_path_required": bool,
        ...
    }
    """
    if not final_path.exists():
        return {
            "reconciliation": RECONCILIATION_NO_FINAL,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": False,
        }

    stale = _detect_stale_sync(session, final_path)
    if not stale:
        return {
            "reconciliation": RECONCILIATION_ALREADY_SYNCED,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": False,
        }

    logger.info(
        "RECONCILIATION_STALE_DETECTED: session=%s final=%s — triggering sync",
        session, final_path.name,
    )
    return _execute_reconciliation_sync(session, final_path)


def _execute_reconciliation_sync(session: int, final_path: Path) -> dict:
    """Reconciliation 경로: stale 감지 → execute_close_bundle."""
    try:
        sync_result = execute_close_bundle(session=session, final_path=final_path)
    except Exception as exc:
        logger.error("RECONCILIATION_SYNC_FAILED: session=%s error=%s", session, exc)
        return {
            "reconciliation": RECONCILIATION_SYNC_FAILED,
            "sync_result": None,
            "deploy_request_created": False,
            "manual_path_required": True,
            "error": str(exc),
        }

    if sync_result.get("decision") != "COMMIT":
        return {
            "reconciliation": RECONCILIATION_STALE_DETECTED,
            "sync_result": sync_result,
            "deploy_request_created": False,
            "manual_path_required": True,
        }

    deploy_ok = _generate_deploy_request(session, sync_result)
    return {
        "reconciliation": RECONCILIATION_STALE_DETECTED,
        "sync_result": sync_result,
        "deploy_request_created": deploy_ok,
        "manual_path_required": not deploy_ok,
    }


# ── 상태 조회 ───────────────────────────────────────────────────────────────

def get_orchestrator_status() -> dict:
    """Sync Orchestrator 현재 상태 요약 (관측/감사용)."""
    return {
        "component": "sync_orchestrator",
        "layer": "sync_layer",
        "p3_task": "P3-T1",
        "eag_authorized": True,
        "fail_closed": True,
        "manual_path_preserved": True,
        "deploy_request_path": str(DEPLOY_REQUEST_PATH),
        "event_store": get_event_store_status(),
    }

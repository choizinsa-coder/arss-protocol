"""
tier2_handler.py — Tier2 Sandbox Write Handler v1.0.0
EAG-1 (S164): Write Plane Restore

역할: Tier2 Sandbox 자율 기록 담당 (approval 불필요)

처리 흐름:
  1. os.path.realpath 경로 정규화 (symlink / .. 우회 차단)
  2. sandbox 경계 확인 (CONTRACT-02)
  3. 금지 확장자 확인 (CONTRACT-03)
  4. 파일 쓰기
  5. audit 기록

허용 경로 (CONTRACT-02):
  tools/sandbox/
  tools/tmp/
  tests/sandbox/

금지 확장자 (CONTRACT-03):
  .py / .service / .conf / .sh / .env / .pem / .key

CONTRACT-01: approval 없이 처리 가능 (Tier2 진입 자체가 증거)

보안 주의 (제니 TRUST-ADVISORY):
  os.path.realpath 사용으로 symbolic link / 상위 디렉토리 이동(..) 완전 차단.
  단순 os.path.abspath 만으로는 symlink 우회 가능 — realpath 필수.
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone

_ROOT = "/opt/arss/engine/arss-protocol"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools.mcp_write.tier_router import (
    SANDBOX_PATHS,
    set_write_plane_state,
    WritePlaneState,
)

AUDIT_DIR = f"{_ROOT}/registry/mcp_write/audit"
AUDIT_FILE = f"{AUDIT_DIR}/mcp_write_audit.jsonl"

FORBIDDEN_EXTENSIONS = {".py", ".service", ".conf", ".sh", ".env", ".pem", ".key"}


# ── 예외 ─────────────────────────────────────────────────────────────

class Tier2DenyError(Exception):
    """Tier2 처리 거부."""
    def __init__(self, reason: str, contract: str = ""):
        self.reason = reason
        self.contract = contract
        super().__init__(f"TIER2 DENY [{contract}]: {reason}")


# ── 내부 헬퍼 ────────────────────────────────────────────────────────

def _append_audit(event: dict, audit_file: str = None) -> None:
    """
    audit.jsonl에 이벤트 추가.
    Fail-Closed: 실패 시 LOCKED_TIER1 진입.
    """
    target = audit_file or AUDIT_FILE
    os.makedirs(os.path.dirname(target), exist_ok=True)
    try:
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as e:
        try:
            set_write_plane_state(
                WritePlaneState.LOCKED_TIER1,
                reason=f"tier2 audit append failed: {e}",
            )
        except Exception:
            pass
        raise Tier2DenyError(
            f"FAIL-CLOSED: audit 기록 실패 (CONTRACT-09): {e}",
            contract="CONTRACT-09",
        )


# ── 경계 검증 ─────────────────────────────────────────────────────────

def _is_in_sandbox(real_path: str) -> bool:
    """
    realpath 기반 sandbox 경계 검증.
    CONTRACT-02: sandbox 외부 접근 거부.
    """
    for sandbox in SANDBOX_PATHS:
        real_sandbox = os.path.realpath(sandbox)
        if real_path == real_sandbox or real_path.startswith(real_sandbox + os.sep):
            return True
    return False


def _check_extension(target_path: str) -> None:
    """
    CONTRACT-03: 금지 확장자 거부.
    """
    _, ext = os.path.splitext(target_path)
    if ext.lower() in FORBIDDEN_EXTENSIONS:
        raise Tier2DenyError(
            f"금지 확장자: {ext} (CONTRACT-03)",
            contract="CONTRACT-03",
        )


# ── 메인 처리 흐름 ────────────────────────────────────────────────────

def handle_tier2_write(
    target_path: str,
    content: str,
    audit_file: str = None,
    sandbox_paths: list = None,
) -> dict:
    """
    Tier2 write 전체 흐름 실행 (approval 불필요 — CONTRACT-01).

    Args:
        target_path   : 대상 파일 경로
        content       : 기록 내용
        audit_file    : override (테스트용)
        sandbox_paths : override (테스트용) — realpath 적용 목록

    Returns:
        {ok: True, tier: "TIER2", event_id, target_path}

    Raises:
        Tier2DenyError: 경계 위반 / 금지 확장자
    """
    event_id = uuid.uuid4().hex

    # 1. os.path.realpath 경로 정규화 — symlink / .. 우회 차단
    try:
        real_path = os.path.realpath(os.path.abspath(target_path))
    except Exception as e:
        raise Tier2DenyError(f"경로 정규화 실패: {e}")

    # 2. CONTRACT-02: sandbox 경계 확인
    effective_sandboxes = sandbox_paths or SANDBOX_PATHS
    in_sandbox = False
    for sb in effective_sandboxes:
        real_sb = os.path.realpath(sb)
        if real_path == real_sb or real_path.startswith(real_sb + os.sep):
            in_sandbox = True
            break

    if not in_sandbox:
        raise Tier2DenyError(
            f"sandbox 경계 탈출 시도: {real_path} (CONTRACT-02)",
            contract="CONTRACT-02",
        )

    # 3. CONTRACT-03: 금지 확장자 확인
    _check_extension(target_path)

    # 4. 파일 쓰기
    try:
        parent = os.path.dirname(real_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        _append_audit({
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tier": "TIER2",
            "actor": "caddy",
            "operation": "WRITE",
            "target_path": real_path,
            "result": "FAIL",
            "failure_reason": str(e),
        }, audit_file)
        raise Tier2DenyError(f"파일 쓰기 실패: {e}")

    # 5. audit 기록
    _append_audit({
        "event_id": event_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tier": "TIER2",
        "actor": "caddy",
        "operation": "WRITE",
        "target_path": real_path,
        "result": "PASS",
        "failure_reason": None,
    }, audit_file)

    return {
        "ok": True,
        "tier": "TIER2",
        "event_id": event_id,
        "target_path": real_path,
    }

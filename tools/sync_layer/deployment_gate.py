"""
deployment_gate.py
AIBA Sync Layer — Deployment Gate
SSOT: Domi Phase 3 Design (S168) / EAG-2 Approved (비오(Joshua))

역할:
  - DEPLOY_REQUEST 수신 → 배포 승인 검증
  - Tier 1 / Tier 2 경로 분류
  - Gate PASS 시만 deploy_executor 진입 허용

위치:
  Write Plane 이후 — deploy_executor 이전
  권한 혼합 방지 원칙 (D-05 준수)

Gate 검증 항목:
  G-1: DEPLOY_REQUEST 상태 확인 (PENDING_GATE)
  G-2: sync_decision 확인 (COMMIT 필수)
  G-3: pointer_updated + manifest_fresh 확인
  G-4: session 정합성 확인
  G-5: Tier 1 — approval_id 형식 확인 (APPROVAL-* 패턴)
  G-6: Tier 2 — target_path Sandbox Namespace 확인

금지:
  - EAG 없이 Tier 1 PASS 판정
  - context_gateway 컴포넌트 인터페이스 변경
  - Gate가 직접 파일 배포 수행
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tools.context_gateway.write_tier_policy import (
    WriteTier,
    classify_path,
    assert_tier2_safe,
)

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
EVENT_DIR = VPS_ROOT / "event"
DEPLOY_REQUEST_PATH = EVENT_DIR / "DEPLOY_REQUEST.json"

APPROVAL_ID_PATTERN = re.compile(r"^APPROVAL-.+")

GATE_RESULT_PASS = "GATE_PASS"
GATE_RESULT_REJECT = "GATE_REJECT"

DEPLOY_TIER_1 = "TIER_1"
DEPLOY_TIER_2 = "TIER_2"


# ── 데이터 클래스 ───────────────────────────────────────────────────────────

@dataclass
class GateDecision:
    """Gate 검증 결과"""
    passed: bool
    tier: Optional[str] = None
    deploy_request: Optional[dict] = None
    approval_id: Optional[str] = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ── 내부 검증 함수 ──────────────────────────────────────────────────────────

def _validate_request_status(request: dict, decision: GateDecision) -> None:
    """[G-1] DEPLOY_REQUEST 상태 확인"""
    status = request.get("status")
    if status != "PENDING_GATE":
        decision.add_error(
            f"INVALID_REQUEST_STATUS: expected=PENDING_GATE actual={status}"
        )


def _validate_sync_decision(request: dict, decision: GateDecision) -> None:
    """[G-2] sync_decision COMMIT 필수 확인"""
    sync_decision = request.get("sync_decision")
    if sync_decision != "COMMIT":
        decision.add_error(
            f"SYNC_DECISION_NOT_COMMIT: sync_decision={sync_decision} — "
            "비커밋 상태의 DEPLOY_REQUEST는 Gate 통과 불가"
        )


def _validate_sync_completeness(request: dict, decision: GateDecision) -> None:
    """[G-3] pointer_updated + manifest_fresh 확인"""
    if not request.get("pointer_updated"):
        decision.add_error("POINTER_NOT_UPDATED: Close Bundle 미완료 상태")
    if not request.get("manifest_fresh"):
        decision.add_error("MANIFEST_NOT_FRESH: Close Bundle 미완료 상태")


def _validate_session(request: dict, expected_session: Optional[int],
                       decision: GateDecision) -> None:
    """[G-4] 세션 정합성 확인"""
    if expected_session is None:
        return
    req_session = request.get("session")
    if req_session != expected_session:
        decision.add_error(
            f"SESSION_MISMATCH: request.session={req_session} expected={expected_session}"
        )


def _validate_tier1_approval(approval_id: Optional[str],
                               decision: GateDecision) -> None:
    """[G-5] Tier 1 approval_id 형식 확인 (APPROVAL-* 패턴)"""
    if not approval_id:
        decision.add_error(
            "APPROVAL_ID_MISSING: Tier 1 배포는 approval_id 필수 — EAG 승인 없이 진행 불가"
        )
        return
    if not APPROVAL_ID_PATTERN.match(approval_id):
        decision.add_error(
            f"APPROVAL_ID_INVALID: '{approval_id}'는 APPROVAL-* 형식 불일치"
        )


def _validate_tier2_path(target_path: Path, decision: GateDecision) -> None:
    """[G-6] Tier 2 target_path Sandbox Namespace 확인"""
    try:
        assert_tier2_safe(target_path)
    except RuntimeError as exc:
        decision.add_error(f"TIER2_PATH_VIOLATION: {exc}")


# ── Tier 분류 ───────────────────────────────────────────────────────────────

def classify_deploy_tier(
    request: dict,
    target_path: Optional[Path] = None,
) -> str:
    """
    DEPLOY_REQUEST 기반 배포 Tier 분류.

    Tier 1 조건:
      - request_type == DEPLOY_REQUEST
      - sync_decision == COMMIT (Session Context 동기화 배포)

    Tier 2 조건:
      - target_path가 Sandbox Namespace에 속함

    반환: DEPLOY_TIER_1 | DEPLOY_TIER_2
    """
    if (
        request.get("request_type") == "DEPLOY_REQUEST"
        and request.get("sync_decision") == "COMMIT"
    ):
        return DEPLOY_TIER_1

    if target_path is not None:
        tier = classify_path(target_path)
        if tier == WriteTier.TIER_2:
            return DEPLOY_TIER_2

    return DEPLOY_TIER_1  # Default: 최상위 보호 — Fail-Closed


# ── 공개 API ────────────────────────────────────────────────────────────────

def validate_tier1_deploy(
    request: dict,
    approval_id: str,
    expected_session: Optional[int] = None,
) -> GateDecision:
    """
    Tier 1 배포 Gate 검증 진입점.
    EAG approval_id 형식 확인 포함.

    반환: GateDecision (passed=True/False)
    """
    decision = GateDecision(passed=True, tier=DEPLOY_TIER_1)
    decision.deploy_request = request
    decision.approval_id = approval_id

    _validate_request_status(request, decision)
    _validate_sync_decision(request, decision)
    _validate_sync_completeness(request, decision)
    _validate_session(request, expected_session, decision)
    _validate_tier1_approval(approval_id, decision)

    if decision.passed:
        logger.info(
            "GATE_PASS_TIER1: session=%s approval_id=%s",
            request.get("session"), approval_id,
        )
    else:
        logger.warning(
            "GATE_REJECT_TIER1: session=%s errors=%s",
            request.get("session"), decision.errors,
        )

    return decision


def validate_tier2_deploy(
    request: dict,
    target_path: Path,
    expected_session: Optional[int] = None,
) -> GateDecision:
    """
    Tier 2 배포 Gate 검증 진입점.
    Sandbox Namespace 확인 포함.

    반환: GateDecision (passed=True/False)
    """
    decision = GateDecision(passed=True, tier=DEPLOY_TIER_2)
    decision.deploy_request = request

    _validate_tier2_path(target_path, decision)
    _validate_session(request, expected_session, decision)

    if decision.passed:
        logger.info(
            "GATE_PASS_TIER2: target=%s", target_path,
        )
    else:
        logger.warning(
            "GATE_REJECT_TIER2: target=%s errors=%s",
            target_path, decision.errors,
        )

    return decision


def load_deploy_request() -> Optional[dict]:
    """
    DEPLOY_REQUEST.json 로드.
    파일 없거나 파싱 실패 시 None 반환.
    """
    if not DEPLOY_REQUEST_PATH.exists():
        return None
    try:
        return json.loads(DEPLOY_REQUEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("DEPLOY_REQUEST_LOAD_FAILED: %s", exc)
        return None


def get_gate_status() -> dict:
    """Deployment Gate 상태 요약 (관측/감사용)."""
    return {
        "component": "deployment_gate",
        "layer": "sync_layer",
        "p3_task": "P3-T2",
        "tier1_requires_approval_id": True,
        "tier2_sandbox_only": True,
        "fail_closed": True,
        "deploy_request_path": str(DEPLOY_REQUEST_PATH),
    }

"""
deploy_executor.py
AIBA Sync Layer — Deploy Executor (Authority of Record)
SSOT: Domi Phase 3 Design (S168) / EAG-2 Approved (비오(Joshua))

역할:
  - Deployment Gate PASS 후 실제 배포 실행
  - deployment_receipt 생성 (Authority of Record)
  - Tier 1: registry/deployment_receipts/ 저장 (365일 보존)
  - Tier 2: 배포 위치 근처 receipts/ 저장 (90일 보존)

Authority of Record 원칙 (GAP-1 해소):
  "누가 배포했는가" = deploy_executor 기록 (n8n 아님)

Receipt 스키마 (도미 BRIEFING-DOMI-S168-P3-003 확정):
  Tier 1: deployment_id / deploy_type / actor / approval_id /
          artifact_hash / target / result / timestamp /
          request_id / session / receipt_version
  Tier 2: deployment_id / path / hash / result / timestamp

result enum: SUCCESS / FAILED / REJECTED / ABORTED

금지:
  - Gate 검증 없이 실행 (caller 책임으로 전제)
  - Tier 2 receipt에 approval_id 포함
  - n8n에 Authority of Record 위임
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tools.sync_layer.deployment_gate import (
    GateDecision,
    DEPLOY_TIER_1,
    DEPLOY_TIER_2,
    GATE_RESULT_PASS,
    GATE_RESULT_REJECT,
)
from tools.context_gateway.write_tier_policy import assert_tier2_safe

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
TIER1_RECEIPT_DIR = VPS_ROOT / "registry" / "deployment_receipts"
KST = timezone(timedelta(hours=9))

RECEIPT_VERSION = "DEPLOYMENT_RECEIPT_v1"
DEPLOY_TYPE_TIER1 = "TIER1_EAG_DEPLOY"
DEPLOY_TYPE_TIER2 = "TIER2_SANDBOX_DEPLOY"
ACTOR = "deploy_executor"

RESULT_SUCCESS = "SUCCESS"
RESULT_FAILED = "FAILED"
RESULT_REJECTED = "REJECTED"
RESULT_ABORTED = "ABORTED"


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _now_kst() -> str:
    """현재 KST 시각 ISO8601 반환."""
    return datetime.now(KST).isoformat()


def _build_deployment_id(session: int, artifact_hash: str) -> str:
    """
    deployment_id 생성.
    형식: DEPLOY-{SESSION}-{UTC_TS}-{SHORT_HASH}
    """
    utc_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_hash = artifact_hash[:6].upper() if artifact_hash else "000000"
    return f"DEPLOY-{session}-{utc_ts}-{short_hash}"


def _compute_hash(path: Path) -> Optional[str]:
    """파일 SHA256 계산. 실패 시 None."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, Exception):
        return None


def _compute_content_hash(content: str) -> str:
    """문자열 내용 SHA256 계산."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _fsync_write(path: Path, content: str) -> bool:
    """파일 쓰기 + fsync. 실패 시 False."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
                return True
            except OSError as exc:
                logger.warning("FSYNC_DEGRADED: %s — %s", path, exc)
                return False
    except OSError as exc:
        logger.error("FILE_WRITE_FAILED: %s — %s", path, exc)
        return False


def _save_tier1_receipt(receipt: dict) -> bool:
    """Tier 1 receipt를 registry/deployment_receipts/ 에 저장."""
    TIER1_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{receipt['deployment_id']}.json"
    path = TIER1_RECEIPT_DIR / filename
    return _fsync_write(path, json.dumps(receipt, ensure_ascii=False, indent=2))


def _save_tier2_receipt(receipt: dict, target_path: Path) -> bool:
    """Tier 2 receipt를 배포 위치 근처 receipts/ 디렉터리에 저장."""
    receipt_dir = target_path.parent / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{receipt['deployment_id']}.json"
    path = receipt_dir / filename
    return _fsync_write(path, json.dumps(receipt, ensure_ascii=False, indent=2))


# ── Tier 1 실행 ─────────────────────────────────────────────────────────────

def _build_tier1_receipt(
    gate: GateDecision,
    result: str,
    artifact_hash: str,
    target: str,
) -> dict:
    """Tier 1 deployment_receipt 빌드."""
    request = gate.deploy_request or {}
    session = request.get("session", 0)
    deployment_id = _build_deployment_id(session, artifact_hash)

    return {
        "deployment_id": deployment_id,
        "deploy_type": DEPLOY_TYPE_TIER1,
        "actor": ACTOR,
        "approval_id": gate.approval_id,
        "artifact_hash": artifact_hash,
        "target": target,
        "result": result,
        "timestamp": _now_kst(),
        "request_id": request.get("requested_by", "sync_orchestrator"),
        "session": session,
        "receipt_version": RECEIPT_VERSION,
    }


def execute_tier1_deploy(
    gate: GateDecision,
    final_path: Path,
    target: str = "SESSION_CONTEXT",
) -> dict:
    """
    Tier 1 배포 실행.
    Gate PASS 확인 → artifact_hash 계산 → receipt 생성 → 저장.

    반환: {
        "result": SUCCESS | FAILED | REJECTED,
        "receipt": dict,
        "receipt_saved": bool,
        "tier": TIER_1,
    }
    """
    if not gate.passed:
        receipt = _build_tier1_receipt(gate, RESULT_REJECTED, "", target)
        _save_tier1_receipt(receipt)
        return {
            "result": RESULT_REJECTED,
            "receipt": receipt,
            "receipt_saved": True,
            "tier": DEPLOY_TIER_1,
            "errors": gate.errors,
        }

    artifact_hash = _compute_hash(final_path) if final_path.exists() else ""
    if not artifact_hash:
        logger.error("ARTIFACT_HASH_FAILED: path=%s", final_path)
        receipt = _build_tier1_receipt(gate, RESULT_FAILED, "", target)
        saved = _save_tier1_receipt(receipt)
        return {
            "result": RESULT_FAILED,
            "receipt": receipt,
            "receipt_saved": saved,
            "tier": DEPLOY_TIER_1,
            "error": "ARTIFACT_HASH_FAILED",
        }

    receipt = _build_tier1_receipt(gate, RESULT_SUCCESS, artifact_hash, target)
    saved = _save_tier1_receipt(receipt)

    logger.info(
        "TIER1_DEPLOY_SUCCESS: deployment_id=%s session=%s",
        receipt["deployment_id"], receipt["session"],
    )
    return {
        "result": RESULT_SUCCESS,
        "receipt": receipt,
        "receipt_saved": saved,
        "tier": DEPLOY_TIER_1,
    }


# ── Tier 2 실행 ─────────────────────────────────────────────────────────────

def _build_tier2_receipt(
    target_path: Path,
    content_hash: str,
    result: str,
) -> dict:
    """Tier 2 경량 deployment_receipt 빌드."""
    session = 0  # Tier 2는 session 미포함 — 경량화 원칙
    deployment_id = _build_deployment_id(session, content_hash)
    return {
        "deployment_id": deployment_id,
        "path": str(target_path),
        "hash": content_hash,
        "result": result,
        "timestamp": _now_kst(),
    }


def execute_tier2_deploy(
    gate: GateDecision,
    target_path: Path,
    content: str,
) -> dict:
    """
    Tier 2 배포 실행.
    Gate PASS 확인 → Sandbox Namespace 재검증 → 파일 쓰기 → 경량 receipt 생성.

    반환: {
        "result": SUCCESS | FAILED | REJECTED,
        "receipt": dict,
        "receipt_saved": bool,
        "tier": TIER_2,
    }
    """
    if not gate.passed:
        content_hash = _compute_content_hash(content)
        receipt = _build_tier2_receipt(target_path, content_hash, RESULT_REJECTED)
        return {
            "result": RESULT_REJECTED,
            "receipt": receipt,
            "receipt_saved": False,
            "tier": DEPLOY_TIER_2,
            "errors": gate.errors,
        }

    # Sandbox Namespace 재검증 (방어적 중복 확인)
    try:
        assert_tier2_safe(target_path)
    except RuntimeError as exc:
        content_hash = _compute_content_hash(content)
        receipt = _build_tier2_receipt(target_path, content_hash, RESULT_REJECTED)
        return {
            "result": RESULT_REJECTED,
            "receipt": receipt,
            "receipt_saved": False,
            "tier": DEPLOY_TIER_2,
            "error": str(exc),
        }

    content_hash = _compute_content_hash(content)
    write_ok = _fsync_write(target_path, content)

    if not write_ok:
        receipt = _build_tier2_receipt(target_path, content_hash, RESULT_FAILED)
        saved = _save_tier2_receipt(receipt, target_path)
        return {
            "result": RESULT_FAILED,
            "receipt": receipt,
            "receipt_saved": saved,
            "tier": DEPLOY_TIER_2,
            "error": "FILE_WRITE_FAILED",
        }

    receipt = _build_tier2_receipt(target_path, content_hash, RESULT_SUCCESS)
    saved = _save_tier2_receipt(receipt, target_path)

    logger.info(
        "TIER2_DEPLOY_SUCCESS: deployment_id=%s path=%s",
        receipt["deployment_id"], target_path,
    )
    return {
        "result": RESULT_SUCCESS,
        "receipt": receipt,
        "receipt_saved": saved,
        "tier": DEPLOY_TIER_2,
    }


# ── 상태 조회 ───────────────────────────────────────────────────────────────

def get_executor_status() -> dict:
    """Deploy Executor 상태 요약 (관측/감사용)."""
    tier1_count = 0
    if TIER1_RECEIPT_DIR.exists():
        tier1_count = len(list(TIER1_RECEIPT_DIR.glob("*.json")))

    return {
        "component": "deploy_executor",
        "layer": "sync_layer",
        "p3_task": "P3-T2",
        "actor": ACTOR,
        "receipt_version": RECEIPT_VERSION,
        "authority_of_record": True,
        "tier1_receipt_dir": str(TIER1_RECEIPT_DIR),
        "tier1_receipt_count": tier1_count,
        "tier2_receipt_location": "sandbox/receipts/ (배포 위치 근처)",
        "result_enum": [RESULT_SUCCESS, RESULT_FAILED, RESULT_REJECTED, RESULT_ABORTED],
    }

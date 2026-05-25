"""
manifest_manager.py
AIBA Context Gateway — Stale Manifest Manager
SSOT: Domi Phase A Design / EAG-1 Approved (S151)
Phase B patch: "degraded" 상태 추가 (S152)

역할:
  - SESSION_CONTEXT_STALE_MANIFEST.json 생성 / 갱신 / 검증 / 로드
  - shard/projection stale 상태 표시 (판단 차단용 신호판)
  - 금지: shard 자동 수정 / 운영 shard write-back / projection 강제 생성
  - 소유권: Caddy-owned, Beo-gated
"""

import json
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
MANIFEST_FILENAME = "SESSION_CONTEXT_STALE_MANIFEST.json"
MANIFEST_PATH = VPS_ROOT / MANIFEST_FILENAME

KST = timezone(timedelta(hours=9))

# projection_status 허용 값 — Phase B: "degraded" 추가
VALID_PROJECTION_STATUSES = {"fresh", "stale", "unknown", "not_required", "degraded"}

# blocking_flags 정의
FLAG_STALE_PROJECTION = "STALE_PROJECTION"
FLAG_HASH_MISMATCH = "HASH_MISMATCH"
FLAG_POINTER_MISSING = "POINTER_MISSING"
FLAG_MANIFEST_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"

REQUIRED_MANIFEST_FIELDS = {
    "manifest_session",
    "context_hash",
    "pointer_hash",
    "generated_at",
    "generated_by",
    "projection_status",
    "shard_status_summary",
    "role_projection_status",
    "blocking_flags",
}

ALLOWED_AGENTS = {"domi", "jeni", "caddy"}

# stale 상태에서 금지되는 에이전트 행동
STALE_BLOCKED_ACTIONS = [
    "DESIGN_CONFIRMATION",
    "TRUST_READY",
    "EAG_RECOMMENDATION",
]


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _compute_hash(data: dict) -> str:
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(serialized).hexdigest()


# ── 공개 API ───────────────────────────────────────────────────────────────

def load_manifest() -> Optional[dict]:
    """
    MANIFEST_PATH에서 SESSION_CONTEXT_STALE_MANIFEST.json 로드.
    파일 없음 또는 파싱 실패 시 None 반환.
    """
    if not MANIFEST_PATH.exists():
        return None
    try:
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def validate_manifest(manifest: dict) -> tuple[bool, list[str]]:
    """
    Manifest 구조 검증.
    반환: (is_valid: bool, errors: list[str])
    """
    errors = []

    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            errors.append(f"MISSING_FIELD: {field}")

    if errors:
        return False, errors

    # projection_status 값 검증
    ps = manifest.get("projection_status", "")
    if ps not in VALID_PROJECTION_STATUSES:
        errors.append(f"INVALID_PROJECTION_STATUS: {ps!r}")

    # role_projection_status 에이전트 키 검증
    rps = manifest.get("role_projection_status", {})
    for agent in rps:
        if agent not in ALLOWED_AGENTS:
            errors.append(f"UNKNOWN_AGENT_IN_ROLE_PROJECTION: {agent}")
        if rps[agent] not in VALID_PROJECTION_STATUSES:
            errors.append(f"INVALID_ROLE_STATUS[{agent}]: {rps[agent]!r}")

    # blocking_flags 타입 검증
    if not isinstance(manifest.get("blocking_flags"), list):
        errors.append("blocking_flags must be a list")

    return len(errors) == 0, errors


def create_manifest(
    session: int,
    context_hash: str,
    pointer_hash: str,
    projection_status: str,
    shard_status_summary: dict,
    role_projection_status: dict,
    blocking_flags: list,
    generated_by: str = "caddy",
) -> dict:
    """
    신규 SESSION_CONTEXT_STALE_MANIFEST 생성.
    Phase A: 상태 표시만 수행. shard write-back 금지.
    """
    if projection_status not in VALID_PROJECTION_STATUSES:
        raise ValueError(f"Invalid projection_status: {projection_status!r}")

    for agent, status in role_projection_status.items():
        if agent not in ALLOWED_AGENTS:
            raise ValueError(f"Unknown agent: {agent!r}")
        if status not in VALID_PROJECTION_STATUSES:
            raise ValueError(f"Invalid role status for {agent}: {status!r}")

    manifest = {
        "manifest_session": session,
        "context_hash": context_hash,
        "pointer_hash": pointer_hash,
        "generated_at": datetime.now(KST).isoformat(),
        "generated_by": generated_by,
        "projection_status": projection_status,
        "shard_status_summary": shard_status_summary,
        "role_projection_status": role_projection_status,
        "blocking_flags": blocking_flags,
        "stale_blocked_actions": STALE_BLOCKED_ACTIONS if blocking_flags else [],
        "phase": "A",
        "write_back_allowed": False,  # Phase A 불변 제약
    }
    return manifest


def save_manifest(manifest: dict) -> Path:
    """
    MANIFEST_PATH에 Manifest 저장.
    반환: 저장된 파일 경로
    """
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return MANIFEST_PATH


def get_manifest_hash(manifest: dict) -> str:
    """Manifest dict SHA256 반환 (Close Bundle 검증용)"""
    return _compute_hash(manifest)


def is_blocking(manifest: dict) -> bool:
    """blocking_flags가 하나라도 존재하면 True"""
    return bool(manifest.get("blocking_flags"))


def get_blocking_flags(manifest: dict) -> list:
    """현재 blocking_flags 반환"""
    return manifest.get("blocking_flags", [])


def verify_close_bundle_consistency(
    session_count: int,
    context_hash: str,
    updated_at: str,
    pointer: dict,
    manifest: dict,
) -> tuple[bool, list[str]]:
    """
    Close Bundle 3-way 일치 검증.
    SESSION_CONTEXT_FINAL / POINTER / MANIFEST의
    session_count · context_hash · updated_at 일치 여부 확인.
    반환: (is_consistent: bool, errors: list[str])
    """
    errors = []

    ptr_session = pointer.get("current_session")
    mfst_session = manifest.get("manifest_session")

    if ptr_session != session_count:
        errors.append(
            f"SESSION_COUNT_MISMATCH: context={session_count} pointer={ptr_session}"
        )
    if mfst_session != session_count:
        errors.append(
            f"SESSION_COUNT_MISMATCH: context={session_count} manifest={mfst_session}"
        )

    ptr_hash = pointer.get("context_hash")
    mfst_hash = manifest.get("context_hash")

    if ptr_hash != context_hash:
        errors.append(
            f"CONTEXT_HASH_MISMATCH: context≠pointer ({context_hash[:8]}...≠{str(ptr_hash)[:8]}...)"
        )
    if mfst_hash != context_hash:
        errors.append(
            f"CONTEXT_HASH_MISMATCH: context≠manifest ({context_hash[:8]}...≠{str(mfst_hash)[:8]}...)"
        )

    ptr_updated = pointer.get("updated_at")
    mfst_generated = manifest.get("generated_at")
    if ptr_updated != mfst_generated:
        errors.append(
            f"TIMESTAMP_MISMATCH: pointer.updated_at={ptr_updated} "
            f"manifest.generated_at={mfst_generated}"
        )

    return len(errors) == 0, errors


def build_fresh_manifest(
    session: int,
    context_hash: str,
    pointer_hash: str,
) -> dict:
    """
    모든 shard fresh 상태의 기본 Manifest 생성 헬퍼.
    세션 종료 시 정상 종료 시나리오에서 사용.
    """
    shard_status_summary = {
        "context/tasks/active.json": "fresh",
        "context/tasks/hold.json": "fresh",
        "context/tasks/blocked.json": "fresh",
        "context/tasks/pending.json": "fresh",
        "context/lessons/lessons.json": "fresh",
        "context/metrics/visibility_history.json": "fresh",
        "context/vps/state.json": "fresh",
        "context/vps/deployed.json": "fresh",
    }
    role_projection_status = {
        "domi": "fresh",
        "jeni": "fresh",
        "caddy": "fresh",
    }
    return create_manifest(
        session=session,
        context_hash=context_hash,
        pointer_hash=pointer_hash,
        projection_status="fresh",
        shard_status_summary=shard_status_summary,
        role_projection_status=role_projection_status,
        blocking_flags=[],
    )


def build_stale_manifest(
    session: int,
    context_hash: str,
    pointer_hash: str,
    reason: str,
    stale_agents: Optional[list] = None,
) -> dict:
    """
    stale 상태 Manifest 생성 헬퍼.
    도미·제니 판단 차단 플래그 포함.
    """
    stale_agents = stale_agents or ["domi", "jeni"]
    role_projection_status = {
        agent: ("stale" if agent in stale_agents else "fresh")
        for agent in ALLOWED_AGENTS
    }
    shard_status_summary = {"reason": reason, "status": "stale"}
    blocking_flags = [FLAG_STALE_PROJECTION]

    return create_manifest(
        session=session,
        context_hash=context_hash,
        pointer_hash=pointer_hash,
        projection_status="stale",
        shard_status_summary=shard_status_summary,
        role_projection_status=role_projection_status,
        blocking_flags=blocking_flags,
    )

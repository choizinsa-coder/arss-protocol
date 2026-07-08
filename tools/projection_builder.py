"""
projection_builder.py
AIBA Projection Builder — Layer 2 (L2-2)
SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL
IMPL-NOTE-03: state anchor stale 기준 (active 파일 수 범위) — S143
Phase A Patch: Pointer-first canonical load + role-scoped projection — S151
"""

import json
import sys
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.context_gateway.pointer_manager import load_canonical_context
from tools.context_gateway.manifest_manager import (
    load_manifest,
    is_blocking,
    FLAG_STALE_PROJECTION,
)

# ── 상수 ───────────────────────────────────────────────────────────────────

TTL_SECONDS = 600  # 10분

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
SANDBOX_ROOT = Path("/opt/arss/engine/arss-protocol/tools/sandbox")

KST = timezone(timedelta(hours=9))

ACTIVE_FILE_THRESHOLD = 10
ALLOWED_AGENTS = {"domi", "jeni", "caddy"}

FORBIDDEN_FIELDS = {
    "chain",
    "hmac",
    "token",
    "credential",
    ".env",
    "ssh_key",
    "tls_private_key",
    "oauth_credential",
    "internal_recovery_route",
    "raw_audit_log",
    "HMAC",
}

# Caddy full operational projection (기존 유지)
ALLOWED_TOP_KEYS = {
    "system_name",
    "system_version",
    "session_count",
    "generated_at",
    "active_tasks",
    "pending_tasks",
    "hold_tasks",
    "vps_state",
    "visibility_metrics_s141",
    "stabilization_mode",
    "s114_roadmap",
    "pytest_status",
    "hold_status",
    "next_session_first_action",
    "session_reentry",
    "code_health",
    "complexity_ceiling_status",
}

# Phase A: 역할별 Projection 필드 (Domi 설계 A-4)
ROLE_PROJECTION_KEYS = {
    "domi": {
        "system_name",
        "system_version",
        "session_count",
        "generated_at",
        "session_reentry",      # current_state / open_gaps
        "agent_focus",          # active_design_tasks
        "active_tasks",         # active_design_tasks
        "canonical_rules",      # governance_constraints
        "enforcement_rules",    # governance_constraints
        "decisions",            # governance_constraints
        "hold_tasks",           # open_gaps
        "complexity_ceiling_status",  # freshness_status
        "context_refactor_direction", # freshness_status
        "sandbox_collaboration",      # freshness_status
    },
    "jeni": {
        "system_name",
        "system_version",
        "session_count",
        "generated_at",
        "code_health",          # risk_flags
        "hold_status",          # risk_flags
        "pytest_status",        # risk_flags
        "canonical_rules",      # trust_status
        "enforcement_rules",    # trust_status / approval_boundary
        "caddy_operational_rules",    # trust_status
        "decisions",            # approval_boundary
        "mcp_read_constants",   # external_exposure
        "crp_governance",       # trust_status
        "complexity_ceiling_status",  # trust_status
    },
    "caddy": ALLOWED_TOP_KEYS,  # full operational projection 유지
}

STALE_OUTPUT = (
    "PROJECTION_STALE: generated_at 기준 TTL 초과.\n"
    "판단 불가. Observation Server 갱신 후 재확인 필요."
)

STALE_PROJECTION_BLOCKED = (
    "STALE_PROJECTION: Manifest blocking_flags 활성화.\n"
    "설계 확정 / TRUST_READY / EAG 권고 금지 상태.\n"
    "비오님 승인 후 Manifest 갱신 필요."
)

# ── 캐시 ───────────────────────────────────────────────────────────────────

_cache: dict = {
    "projection": None,
    "built_at_epoch": 0.0,
    "stale": True,
    "refresh_failed": False,
    "canonical_source": "NONE",
}


def _is_cache_valid() -> bool:
    if _cache["projection"] is None:
        return False
    elapsed = time.time() - _cache["built_at_epoch"]
    return elapsed < TTL_SECONDS


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _strip_forbidden(data: dict) -> dict:
    """재귀적으로 forbidden 필드 제거"""
    if not isinstance(data, dict):
        return data
    result = {}
    for k, v in data.items():
        if any(f.lower() in k.lower() for f in FORBIDDEN_FIELDS):
            continue
        if isinstance(v, dict):
            result[k] = _strip_forbidden(v)
        elif isinstance(v, list):
            result[k] = [
                _strip_forbidden(item) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _count_active_files(agent: str) -> int:
    agent_active_dir = SANDBOX_ROOT / agent / "active"
    if not agent_active_dir.exists():
        return 0
    try:
        return sum(1 for p in agent_active_dir.rglob("*") if p.is_file())
    except Exception:
        return 0


def _build_sandbox_active_file_count() -> dict:
    counts = {}
    any_stale = False
    for agent in sorted(ALLOWED_AGENTS):
        cnt = _count_active_files(agent)
        counts[agent] = cnt
        if cnt > ACTIVE_FILE_THRESHOLD:
            any_stale = True
    total = sum(counts.values())
    return {
        "domi": counts.get("domi", 0),
        "jeni": counts.get("jeni", 0),
        "caddy": counts.get("caddy", 0),
        "total": total,
        "threshold": ACTIVE_FILE_THRESHOLD,
        "recursive": True,
        "state_anchor_stale": any_stale,
        "active_file_count_warning": any_stale,
        "eag_ready_blocked": any_stale,
    }


def _get_role_keys(role: Optional[str]) -> set:
    """역할별 허용 키 반환. None 또는 unknown → caddy(full) 적용"""
    if role in ROLE_PROJECTION_KEYS:
        return ROLE_PROJECTION_KEYS[role]
    return ALLOWED_TOP_KEYS


def _build_projection(
    raw: dict,
    canonical_source: str,
    role: Optional[str] = None,
) -> dict:
    """RAW SESSION_CONTEXT → role-scoped Projection 생성"""
    now_kst = datetime.now(KST)
    epoch_ms = int(time.time() * 1000)

    allowed_keys = _get_role_keys(role)
    filtered = {}
    for k in allowed_keys:
        if k in raw:
            filtered[k] = (
                _strip_forbidden(raw[k]) if isinstance(raw[k], dict) else raw[k]
            )

    sandbox_active = _build_sandbox_active_file_count()
    state_anchor_stale = sandbox_active["state_anchor_stale"]

    payload = {
        "AUTHORITY_LEVEL": "OBSERVATION_ONLY_NO_EXECUTION",
        "generated_at": now_kst.isoformat(),
        "epoch_ms": epoch_ms,
        "ttl_seconds": TTL_SECONDS,
        "execution_allowed": False,
        "purpose": "OBSERVATION_ONLY",
        "stale": False,
        "projection_refresh_failed": False,
        "canonical_source": canonical_source,  # Phase A: POINTER | GLOB_FALLBACK
        "role": role or "caddy",
        "sandbox_active_file_count": sandbox_active,
        "state_anchor_stale": state_anchor_stale,
        "active_file_count_warning": state_anchor_stale,
        "eag_ready_blocked": state_anchor_stale,
        "data": filtered,
    }

    hash_basis = json.dumps(
        {k: v for k, v in payload.items() if k not in ("integrity_hash", "data")},
        sort_keys=True, ensure_ascii=False,
    ).encode()
    payload["integrity_hash"] = hashlib.sha256(hash_basis).hexdigest()

    return payload


def _check_manifest_blocking() -> tuple[bool, str]:
    """
    Manifest blocking_flags 확인.
    반환: (is_blocked: bool, reason: str)
    """
    manifest = load_manifest()
    if manifest is None:
        return False, "MANIFEST_NOT_FOUND"
    if is_blocking(manifest):
        flags = manifest.get("blocking_flags", [])
        return True, f"MANIFEST_BLOCKING: {flags}"
    return False, "MANIFEST_OK"


# ── 공개 API ───────────────────────────────────────────────────────────────

def get_projection(role: Optional[str] = None) -> tuple[dict, bool]:
    """
    On-request + TTL cache hybrid.
    Phase A: Pointer-first canonical load + role-scoped projection.
    STALE_PROJECTION blocking_flags 활성화 시 차단 응답 반환.
    반환: (projection_dict, is_stale)
    """
    # Manifest blocking 선행 확인
    is_blocked, block_reason = _check_manifest_blocking()
    if is_blocked:
        return {
            "AUTHORITY_LEVEL": "OBSERVATION_ONLY_NO_EXECUTION",
            "stale": True,
            "blocked": True,
            "block_reason": block_reason,
            "execution_allowed": False,
            "message": STALE_PROJECTION_BLOCKED,
        }, True

    # TTL 캐시 유효 → 반환 (role 무관하게 raw 재사용 불가 → role별 재빌드)
    # 단순화: role이 다르면 캐시 미사용
    if role is None and _is_cache_valid():
        return _cache["projection"], False

    # Pointer-first canonical load (Phase A 핵심 변경)
    raw, canonical_source = load_canonical_context(fallback_glob=False)

    # 계약 16: GLOB_FALLBACK 결과는 canonical 미채택 -> NONE_STATE 취급
    if raw is not None and canonical_source == "GLOB_FALLBACK":
        raw = None

    if raw is None:
        _cache["refresh_failed"] = True
        return {
            "AUTHORITY_LEVEL": "OBSERVATION_ONLY_NO_EXECUTION",
            "stale": True,
            "projection_refresh_failed": True,
            "execution_allowed": False,
            "failure_source": "NONE_STATE",
            "message": STALE_OUTPUT,
        }, True

    projection = _build_projection(raw, canonical_source, role=role)

    # caddy(default) 캐시 갱신
    if role is None:
        _cache["projection"] = projection
        _cache["built_at_epoch"] = time.time()
        _cache["stale"] = False
        _cache["refresh_failed"] = False
        _cache["canonical_source"] = canonical_source

    return projection, False


def invalidate_cache():
    """캐시 강제 무효화"""
    _cache["projection"] = None
    _cache["built_at_epoch"] = 0.0
    _cache["stale"] = True
    _cache["refresh_failed"] = False
    _cache["canonical_source"] = "NONE"


def check_ttl(projection: dict) -> bool:
    """True = STALE, False = VALID"""
    if projection.get("stale"):
        return True
    generated_at_str = projection.get("generated_at")
    if not generated_at_str:
        return True
    try:
        generated_at = datetime.fromisoformat(generated_at_str)
        elapsed = (datetime.now(KST) - generated_at).total_seconds()
        return elapsed >= TTL_SECONDS
    except Exception:
        return True


def get_stale_output() -> str:
    return STALE_OUTPUT

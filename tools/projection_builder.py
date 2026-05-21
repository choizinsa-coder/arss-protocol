"""
projection_builder.py
AIBA Projection Builder — Layer 2 (L2-2)
SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL
"""

import json
import time
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 상수 ───────────────────────────────────────────────────────────────────

TTL_SECONDS = 600  # 10분

SESSION_CONTEXT_PATH = Path(
    "/opt/arss/engine/arss-protocol/tools/session_context_gen"
)
VPS_ROOT = Path("/opt/arss/engine/arss-protocol")

KST = timezone(timedelta(hours=9))

# 절대 제외 필드 (L2-2)
FORBIDDEN_FIELDS = {
    "chain",          # chain.tip 포함
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

# Projection에 포함 허용하는 최상위 키 whitelist
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

STALE_OUTPUT = (
    "PROJECTION_STALE: generated_at 기준 TTL 초과.\n"
    "판단 불가. Observation Server 갱신 후 재확인 필요."
)

# ── 캐시 (in-memory, 프로세스 범위) ───────────────────────────────────────

_cache: dict = {
    "projection": None,
    "built_at_epoch": 0.0,
    "stale": True,
    "refresh_failed": False,
}


def _is_cache_valid() -> bool:
    if _cache["projection"] is None:
        return False
    elapsed = time.time() - _cache["built_at_epoch"]
    return elapsed < TTL_SECONDS


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


def _load_session_context() -> Optional[dict]:
    """SESSION_CONTEXT_FINAL.json 로드 (최신 파일 탐색)"""
    try:
        candidates = sorted(
            VPS_ROOT.glob("SESSION_CONTEXT_S*_FINAL.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        if not candidates:
            return None
        with open(candidates[0], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _build_projection(raw: dict) -> dict:
    """RAW SESSION_CONTEXT → 필터링된 Projection 생성"""
    now_kst = datetime.now(KST)
    epoch_ms = int(time.time() * 1000)

    filtered = {}
    for k in ALLOWED_TOP_KEYS:
        if k in raw:
            filtered[k] = _strip_forbidden(raw[k]) if isinstance(raw[k], dict) else raw[k]

    payload = {
        "AUTHORITY_LEVEL": "OBSERVATION_ONLY_NO_EXECUTION",
        "generated_at": now_kst.isoformat(),
        "epoch_ms": epoch_ms,
        "ttl_seconds": TTL_SECONDS,
        "execution_allowed": False,
        "purpose": "OBSERVATION_ONLY",
        "stale": False,
        "projection_refresh_failed": False,
        "data": filtered,
    }

    # integrity_hash: payload(data 제외) 기준 SHA256
    hash_basis = json.dumps(
        {k: v for k, v in payload.items() if k not in ("integrity_hash", "data")},
        sort_keys=True, ensure_ascii=False
    ).encode()
    payload["integrity_hash"] = hashlib.sha256(hash_basis).hexdigest()

    return payload


def get_projection() -> tuple[dict, bool]:
    """
    On-request + TTL cache hybrid (GAP-02)
    반환: (projection_dict, is_stale)
    """
    # cache TTL 이내 → 기존 반환
    if _is_cache_valid():
        return _cache["projection"], False

    # cache 없음 또는 TTL 초과 → 새 projection 생성 시도
    raw = _load_session_context()
    if raw is None:
        # 생성 실패 처리
        _cache["refresh_failed"] = True
        if _cache["projection"] is not None:
            # stale projection 반환
            stale_proj = dict(_cache["projection"])
            stale_proj["stale"] = True
            stale_proj["projection_refresh_failed"] = True
            stale_proj["stale_warning"] = "STALE_WARNING: SESSION_CONTEXT 로드 실패"
            return stale_proj, True
        # 캐시도 없으면 stale 전용 응답
        return {
            "AUTHORITY_LEVEL": "OBSERVATION_ONLY_NO_EXECUTION",
            "stale": True,
            "projection_refresh_failed": True,
            "execution_allowed": False,
            "message": STALE_OUTPUT,
        }, True

    # 생성 성공
    projection = _build_projection(raw)
    _cache["projection"] = projection
    _cache["built_at_epoch"] = time.time()
    _cache["stale"] = False
    _cache["refresh_failed"] = False

    return projection, False


def check_ttl(projection: dict) -> bool:
    """
    에이전트 호출 전 TTL 확인 헬퍼
    True = STALE, False = VALID
    """
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

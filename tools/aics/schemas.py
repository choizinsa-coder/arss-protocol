"""
schemas.py
AICS (Agent Identity & Consistency System) — 데이터 구조 정의
영역 9 / 위상 1 / EAG-S271-AICS-001

설계 근거: 도미 [DESIGN] S271 + 제니 TRUST-ADVISORY 반영
  - identity_registry = 누구인가
  - governance_token  = 지금 활동 가능한가
  - hermes_gate       = 무엇을 생성할 수 있는가
  - safe_mode         = 언제 전부 정지되는가
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta


# ── 토큰 기본 수명 (초) ──────────────────────────────────────────────────────
DEFAULT_TOKEN_TTL_SEC = 3600


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


@dataclass
class AgentIdentity:
    """Registry에 등록된 에이전트 정체성."""
    actor_id: str
    role: str
    runtime: str
    status: str = "approved"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GovernanceToken:
    """일회성 거버넌스 토큰. AICS만 발급 가능."""
    token_id: str
    actor_id: str
    session: int
    chain_tip: str
    nonce: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        try:
            exp = datetime.fromisoformat(self.expires_at)
        except (ValueError, TypeError):
            return True
        return now >= exp


# ── 검증 실패 사유 코드 ──────────────────────────────────────────────────────
class AICSReason:
    OK = "OK"
    TOKEN_NOT_FOUND = "AICS_TOKEN_INVALID:NOT_FOUND"
    TOKEN_EXPIRED = "AICS_TOKEN_INVALID:EXPIRED"
    ACTOR_MISMATCH = "AICS_TOKEN_INVALID:ACTOR_MISMATCH"
    SESSION_MISMATCH = "AICS_TOKEN_INVALID:SESSION_MISMATCH"
    CHAIN_TIP_MISMATCH = "AICS_TOKEN_INVALID:CHAIN_TIP_MISMATCH"
    SAFE_MODE_ACTIVE = "AICS_TOKEN_INVALID:SAFE_MODE_ACTIVE"
    ACTOR_NOT_REGISTERED = "AICS_ACTOR_NOT_REGISTERED"
    HERMES_DENIED = "AICS_HERMES_DENIED"
    RECOVERY_DENIED = "AICS_RECOVERY_DENIED"


@dataclass
class ValidationResult:
    """토큰 검증 결과."""
    ok: bool
    reason: str = AICSReason.OK
    actor_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def make_expiry(ttl_sec: int = DEFAULT_TOKEN_TTL_SEC,
                now: datetime | None = None) -> str:
    now = now or utc_now()
    return (now + timedelta(seconds=ttl_sec)).isoformat()

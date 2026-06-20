"""
governance_token.py
AICS — Governance Token (지금 활동 가능한가)
영역 9 / EAG-S271-AICS-001

제니 TRUST-ADVISORY ① 반영:
  validate_token() 은 인메모리 딕셔너리 조회만 수행한다 (파일 I/O 없음).
  영속 백업(active_tokens.json)은 발급/폐기 시점에만 비동기적 성격으로 기록.

토큰 생명주기:
  발급(issue)  : AICS 만 가능. actor_id + session + chain_tip 바인딩.
  검증(validate): 인메모리 조회 — actor/session/chain_tip/만료/safe_mode 대조.
  폐기(revoke) : 세션 종료 / Safe Mode / chain.tip 변경 시 자동.
"""

from __future__ import annotations

import json
import os
import uuid

from .schemas import (
    GovernanceToken,
    ValidationResult,
    AICSReason,
    DEFAULT_TOKEN_TTL_SEC,
    utc_now,
    utc_now_iso,
    make_expiry,
)
from .identity_registry import IdentityRegistry


class GovernanceTokenManager:
    """일회성 거버넌스 토큰 매니저. 발급 권한은 이 클래스에 독점된다."""

    def __init__(self, registry: IdentityRegistry,
                 persist_path: str | None = None):
        self._registry = registry
        self._persist_path = persist_path
        # 인메모리 active token store: token_id -> GovernanceToken
        self._active: dict[str, GovernanceToken] = {}

    # ── 발급 ──────────────────────────────────────────────────────────────
    def issue_token(self, actor_id: str, session: int, chain_tip: str,
                    ttl_sec: int = DEFAULT_TOKEN_TTL_SEC) -> GovernanceToken | None:
        """등록된 에이전트에게만 발급. 미등록 시 None (Fail-Closed)."""
        if not self._registry.is_registered(actor_id):
            return None
        token = GovernanceToken(
            token_id=str(uuid.uuid4()),
            actor_id=actor_id,
            session=session,
            chain_tip=chain_tip,
            nonce=str(uuid.uuid4()),
            issued_at=utc_now_iso(),
            expires_at=make_expiry(ttl_sec),
        )
        self._active[token.token_id] = token
        self._persist()
        return token

    # ── 검증 (인메모리 전용 — advisory ①) ─────────────────────────────────
    def validate_token(self, token_id: str, actor_id: str,
                       current_session: int, current_chain_tip: str,
                       safe_mode_active: bool = False) -> ValidationResult:
        if safe_mode_active:
            return ValidationResult(False, AICSReason.SAFE_MODE_ACTIVE)
        token = self._active.get(token_id)
        if token is None:
            return ValidationResult(False, AICSReason.TOKEN_NOT_FOUND)
        if token.actor_id != actor_id:
            return ValidationResult(False, AICSReason.ACTOR_MISMATCH)
        if token.session != current_session:
            return ValidationResult(False, AICSReason.SESSION_MISMATCH)
        if token.chain_tip != current_chain_tip:
            return ValidationResult(False, AICSReason.CHAIN_TIP_MISMATCH)
        if token.is_expired():
            return ValidationResult(False, AICSReason.TOKEN_EXPIRED)
        return ValidationResult(True, AICSReason.OK, actor_id=actor_id)

    # ── 폐기 ──────────────────────────────────────────────────────────────
    def revoke(self, token_id: str) -> bool:
        existed = token_id in self._active
        self._active.pop(token_id, None)
        if existed:
            self._persist()
        return existed

    def revoke_all(self) -> int:
        """Safe Mode / 세션 종료 시 전체 폐기."""
        n = len(self._active)
        self._active.clear()
        self._persist()
        return n

    def revoke_on_chain_change(self, current_chain_tip: str) -> int:
        """chain.tip 변경 시 불일치 토큰 자동 폐기."""
        stale = [tid for tid, t in self._active.items()
                 if t.chain_tip != current_chain_tip]
        for tid in stale:
            self._active.pop(tid, None)
        if stale:
            self._persist()
        return len(stale)

    def active_count(self) -> int:
        return len(self._active)

    # ── 영속 백업 ─────────────────────────────────────────────────────────
    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            payload = {tid: t.to_dict() for tid, t in self._active.items()}
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            # 영속 실패는 인메모리 동작을 막지 않는다 (advisory ①)
            pass

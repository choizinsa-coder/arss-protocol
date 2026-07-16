"""
aics_runtime.py
AICS — Runtime Admission Control (통합 진입점)
영역 9 / EAG-S271-AICS-001

전체 AICS 구성요소를 단일 진입점으로 묶는다:
  Identity Registry → Governance Token → Admission Control
                    → Safe Mode Kill Switch → Hermes Spawn Gate

도미/Jeni 런타임 /ask 진입점은 admit() 한 번만 호출하면 된다.
admit() 은 인메모리 검증만 수행 (advisory ① — 동기 블로킹 최소화).
"""

from __future__ import annotations

import os

from .schemas import ValidationResult, AICSReason
from .identity_registry import IdentityRegistry
from .governance_token import GovernanceTokenManager
from .safe_mode import SafeModeController
from .hermes_gate import HermesGate


# ── 기본 영속 경로 ──────────────────────────────────────────────────────────
_ARSS_ROOT = "/opt/arss/engine/arss-protocol"
_RUNTIME_DIR = os.path.join(_ARSS_ROOT, "runtime", "aics")
_ACTIVE_TOKENS = os.path.join(_RUNTIME_DIR, "active_tokens.json")
_IDENTITY_REGISTRY = os.path.join(_RUNTIME_DIR, "identity_registry.json")
_SAFE_MODE_FLAG = os.path.join(_RUNTIME_DIR, "safe_mode.flag")


class AICSRuntime:
    """AICS 통합 런타임. 단일 인스턴스로 전 구성요소 조정."""

    def __init__(self,
                 active_tokens_path: str = _ACTIVE_TOKENS,
                 identity_registry_path: str = _IDENTITY_REGISTRY,
                 safe_mode_flag_path: str = _SAFE_MODE_FLAG):
        self.registry = IdentityRegistry(persist_path=identity_registry_path)
        self.tokens = GovernanceTokenManager(
            registry=self.registry, persist_path=active_tokens_path)
        self.safe_mode = SafeModeController(flag_path=safe_mode_flag_path, runtime=self)
        self.hermes = HermesGate(registry=self.registry)

    # ── 발급 ──────────────────────────────────────────────────────────────
    def issue(self, actor_id: str, session: int, chain_tip: str):
        if self.safe_mode.is_active():
            return None
        return self.tokens.issue_token(actor_id, session, chain_tip)

    # ── Admission Control (런타임 /ask 진입점이 호출) ──────────────────────
    def admit(self, token_id: str, actor_id: str,
              current_session: int, current_chain_tip: str) -> ValidationResult:
        """
        에이전트 런타임 진입 허가 판정. 인메모리 검증 전용.
        Safe Mode 활성 시 무조건 거부.
        """
        sm = self.safe_mode.is_active()
        return self.tokens.validate_token(
            token_id=token_id, actor_id=actor_id,
            current_session=current_session,
            current_chain_tip=current_chain_tip,
            safe_mode_active=sm)

    # ── Hermes Spawn 판정 ─────────────────────────────────────────────────
    def can_spawn(self, agent_type: str) -> tuple[bool, str]:
        return self.hermes.request_agent_spawn(
            agent_type, safe_mode_active=self.safe_mode.is_active())

    # ── Safe Mode 제어 ────────────────────────────────────────────────────
    def enable_safe_mode(self, reason: str = "UNSPECIFIED") -> bool:
        return self.safe_mode.enable(reason=reason, token_manager=self.tokens, caller=self)

    def disable_safe_mode(self, eag_approval: str | None = None,
                          technical_match: bool = False) -> tuple[bool, str]:
        return self.safe_mode.disable(
            eag_approval=eag_approval, technical_match=technical_match)

    # ── 세션/체인 생명주기 ────────────────────────────────────────────────
    def on_session_close(self) -> int:
        return self.tokens.revoke_all()

    def on_chain_change(self, current_chain_tip: str) -> int:
        return self.tokens.revoke_on_chain_change(current_chain_tip)

"""
hermes_gate.py
AICS — Hermes Spawn Gate (무엇을 생성할 수 있는가)
영역 9 / EAG-S271-AICS-001

J2-WARN-2 방어 핵심:
  Hermes 가 생성하는 Markdown 내용을 파싱하지 않는다.
  에이전트 생성 권한 자체를 Registry + 토큰으로 강제하여 실행 단계에서 차단한다.

  Hermes Markdown 안에 "새로운 에이전트를 만든다" 가 포함되어도,
  실행 시 actor_type 이 Registry 에 없으면 DENY.
"""

from __future__ import annotations

from .schemas import AICSReason
from .identity_registry import IdentityRegistry


class HermesGate:
    """에이전트 생성(spawn) 요청을 Registry 기준으로 통제."""

    def __init__(self, registry: IdentityRegistry):
        self._registry = registry

    def request_agent_spawn(self, agent_type: str,
                            safe_mode_active: bool = False) -> tuple[bool, str]:
        """
        에이전트 생성 요청 판정.
        반환: (허용여부, 사유코드)

        - Safe Mode 시 무조건 차단
        - Registry 미등록 actor_type 차단 (제로 트러스트)
        """
        if safe_mode_active:
            return False, AICSReason.SAFE_MODE_ACTIVE
        if not self._registry.is_registered(agent_type):
            return False, AICSReason.HERMES_DENIED
        return True, AICSReason.OK

    def is_spawn_allowed(self, agent_type: str,
                        safe_mode_active: bool = False) -> bool:
        allowed, _ = self.request_agent_spawn(agent_type, safe_mode_active)
        return allowed

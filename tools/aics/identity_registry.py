"""
identity_registry.py
AICS — Identity Registry (누구인가)
영역 9 / EAG-S271-AICS-001

등록된 에이전트만 토큰 발급 및 생성 권한을 가진다.
Registry에 없는 actor_type 은 Hermes Gate 에서 원천 차단된다 (J2-9 / J2-WARN-2).
"""

from __future__ import annotations

import json
import os

from .schemas import AgentIdentity


# ── 기본 등록 에이전트 (AIF v1.3 영역 5/9 확정) ──────────────────────────────
_DEFAULT_REGISTRY: dict[str, AgentIdentity] = {
    "domi": AgentIdentity(actor_id="domi", role="DESIGN", runtime="8448"),
    "jeni": AgentIdentity(actor_id="jeni", role="VALIDATION", runtime="8447"),
    "caddy": AgentIdentity(actor_id="caddy", role="IMPLEMENT", runtime="mcp"),
}


class IdentityRegistry:
    """인메모리 Registry. 영속 백업은 runtime/aics/identity_registry.json."""

    def __init__(self, persist_path: str | None = None):
        self._registry: dict[str, AgentIdentity] = dict(_DEFAULT_REGISTRY)
        self._persist_path = persist_path
        if persist_path and os.path.isfile(persist_path):
            self._load(persist_path)

    def _load(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            for actor_id, rec in data.items():
                self._registry[actor_id] = AgentIdentity(
                    actor_id=actor_id,
                    role=rec.get("role", ""),
                    runtime=rec.get("runtime", ""),
                    status=rec.get("status", "approved"),
                )
        except (OSError, ValueError, json.JSONDecodeError):
            # 손상 시 기본 Registry 유지 (Fail-Closed: 미등록 확장 금지)
            pass

    def is_registered(self, actor_id: str) -> bool:
        agent = self._registry.get(actor_id)
        return bool(agent) and agent.status == "approved"

    def get(self, actor_id: str) -> AgentIdentity | None:
        return self._registry.get(actor_id)

    def list_approved(self) -> list[str]:
        return [a for a, ag in self._registry.items() if ag.status == "approved"]

    def to_dict(self) -> dict:
        return {a: ag.to_dict() for a, ag in self._registry.items()}

    def persist(self) -> bool:
        if not self._persist_path:
            return False
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except OSError:
            return False

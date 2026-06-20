"""
dual_verifier.py
영역 3 — Dual Verification (이중 게이트)
EAG-S271-JENIVERIFY-001

TECHNICAL_MATCH  : static_scan(syntax/forbidden) + 내용 해시 정합
GOVERNANCE_ALIGN : AICS validate_token + sandbox_validator(validate_write) 정책
PASS = technical_match AND governance_align

sandbox_validator.validate_write 는 주입식(governance_fn) — 로컬 테스트는
자체 policy, 실배포 시 실제 validate_write 주입(advisory ② 연동).
"""

from __future__ import annotations

import os
from typing import Callable

from .schemas import DualResult, JVReason
from .static_scan import static_scan


# ── 기본 거버넌스 정책 (sandbox_validator 원칙 재현) ─────────────────────────
ALLOWED_EXTENSIONS = frozenset({".md", ".json", ".txt"})
FORBIDDEN_EXTENSIONS = frozenset({
    ".py", ".sh", ".rs", ".env", ".yml", ".yaml",
    ".exe", ".so", ".dll", ".service",
})
SANDBOX_ROOT = "/opt/arss/engine/arss-protocol/tools/sandbox"


def _default_governance_policy(file_name: str, target_path: str) -> tuple[bool, str]:
    """sandbox_validator 원칙 재현 — 확장자/경로 격리 정적 검증."""
    suffix = os.path.splitext(file_name)[1].lower()
    if suffix in FORBIDDEN_EXTENSIONS:
        return False, JVReason.FORBIDDEN_EXTENSION
    # 경로 격리: SANDBOX_ROOT 밖이면 차단
    try:
        real = os.path.realpath(target_path)
        if not (real == os.path.realpath(SANDBOX_ROOT)
                or real.startswith(os.path.realpath(SANDBOX_ROOT) + os.sep)):
            return False, JVReason.PATH_ESCAPE
    except OSError:
        return False, JVReason.PATH_ESCAPE
    return True, JVReason.OK


class DualVerifier:
    """이중 검증 — 기술 정합성과 거버넌스 정합성을 분리 식별."""

    def __init__(self, aics_runtime=None,
                 governance_fn: Callable | None = None):
        self._aics = aics_runtime
        # governance_fn(file_name, target_path) -> (bool, reason)
        self._governance_fn = governance_fn or _default_governance_policy

    # ── TECHNICAL_MATCH ───────────────────────────────────────────────────
    def technical_match(self, source: str) -> tuple[bool, str]:
        scan = static_scan(source)
        return scan.ok, scan.reason

    # ── GOVERNANCE_ALIGN ──────────────────────────────────────────────────
    def governance_align(self, file_name: str, target_path: str,
                         token_id: str | None = None,
                         actor_id: str = "", session: int = 0,
                         chain_tip: str = "") -> tuple[bool, str]:
        # AICS 토큰 선행 검증 (제공 시)
        if self._aics is not None and token_id is not None:
            admit = self._aics.admit(token_id=token_id, actor_id=actor_id,
                                     current_session=session,
                                     current_chain_tip=chain_tip)
            if not admit.ok:
                return False, JVReason.TOKEN_INVALID
        return self._governance_fn(file_name, target_path)

    # ── Dual (둘 다 통과해야 PASS) ────────────────────────────────────────
    def verify(self, source: str, file_name: str, target_path: str,
               token_id: str | None = None, actor_id: str = "",
               session: int = 0, chain_tip: str = "") -> DualResult:
        tech_ok, tech_reason = self.technical_match(source)
        gov_ok, gov_reason = self.governance_align(
            file_name, target_path, token_id, actor_id, session, chain_tip)

        if not tech_ok:
            reason = JVReason.TECHNICAL_FAIL
            detail = tech_reason
        elif not gov_ok:
            reason = JVReason.GOVERNANCE_FAIL
            detail = gov_reason
        else:
            reason = JVReason.OK
            detail = ""

        return DualResult(technical_match=tech_ok, governance_align=gov_ok,
                          reason=reason, detail=detail)

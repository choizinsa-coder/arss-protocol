"""
AICS (Agent Identity & Consistency System)
영역 9 / 위상 1 / EAG-S271-AICS-001

AIF v1.3 보안 3단계 방어 중 '예방(Prevention)' 주책임.

핵심 설계:
  Identity Registry → Governance Token → Runtime Admission Control
                    → Safe Mode Kill Switch → Hermes Spawn Gate

J2-WARN-2 대응: Hermes 를 신뢰하지 않고, 모든 에이전트 생성 권한을
Registry + 일회성 거버넌스 토큰으로 강제하여 실행 단계에서 차단.
"""

from .schemas import (
    AgentIdentity,
    GovernanceToken,
    ValidationResult,
    AICSReason,
)
from .identity_registry import IdentityRegistry
from .governance_token import GovernanceTokenManager
from .safe_mode import SafeModeController
from .hermes_gate import HermesGate
from .aics_runtime import AICSRuntime

__all__ = [
    "AgentIdentity",
    "GovernanceToken",
    "ValidationResult",
    "AICSReason",
    "IdentityRegistry",
    "GovernanceTokenManager",
    "SafeModeController",
    "HermesGate",
    "AICSRuntime",
]

__version__ = "1.0.0"

"""
governance_compiler — AIF v1.3 Area 12
Governance Evidence Compiler

S272 EAG-S272-GOVCOMP-001 승인 — 비오(Joshua)

역할: 거버넌스 증거(EAG approval 영수증)를 정규화하여
      Governance State Projection(GSP)을 생성한다.
      권한 생성/scope 계산/만료 계산을 수행하지 않는다 (Evidence Compiler).
"""

from .governance_compiler import compile_governance
from .governance_state_builder import build_governance_state
from .governance_projection import build_bridge_projection
from .compiler_receipt import build_compiler_receipt

__all__ = [
    "compile_governance",
    "build_governance_state",
    "build_bridge_projection",
    "build_compiler_receipt",
]

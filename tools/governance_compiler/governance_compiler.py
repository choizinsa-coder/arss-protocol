"""
governance_compiler.py
Area 12 — Governance Evidence Compiler 메인 진입점

파이프라인:
  SESSION_CONTEXT.eag_chain
    → Governance State (증거 정규화)
    → Bridge Projection (GSP)
    → Compiler Receipt

OUT OF SCOPE: 권한 생성 / scope 계산 / 만료 계산 / mutation / route 실행 / 디스크 영속화
"""

from __future__ import annotations

from typing import Optional

from .governance_state_builder import build_governance_state
from .governance_projection import build_bridge_projection
from .compiler_receipt import build_compiler_receipt


def compile_governance(
    session_context: dict,
    approvals: Optional[list] = None,
) -> dict:
    """
    Governance Compiler 메인 진입점.

    Args:
        session_context: SESSION_CONTEXT dict.
                         eag_chain 및 session 필드를 사용한다.
                         eag_chain 위치 후보:
                           - session_context["eag_chain"]
                           - session_context["system_changes_s{n}"]["eag_chain"]
                         호출자가 평탄화하여 eag_chain 키로 전달하는 것을 권장.
        approvals: EAG approval 영수증 dict 목록 (Approval Resolver 결과).
                   None 이면 토큰 추출만 수행하고 증거 미연결로 처리.

    Returns:
        {
          "governance_state": {...},
          "projection": {...},   # Bridge가 소비하는 GSP
          "receipt": {...}       # 감사 추적 영수증
        }

        모두 인메모리 dict. 디스크 영속화하지 않는다 (제약 2).
    """
    eag_chain = session_context.get("eag_chain")
    session = session_context.get("session") or session_context.get("session_count")
    if isinstance(session, int):
        session = f"S{session}"

    governance_state = build_governance_state(
        eag_chain=eag_chain,
        approvals=approvals,
        session=session,
    )
    projection = build_bridge_projection(governance_state, session=session)
    receipt = build_compiler_receipt(governance_state, projection, session=session)

    return {
        "governance_state": governance_state,
        "projection": projection,
        "receipt": receipt,
    }

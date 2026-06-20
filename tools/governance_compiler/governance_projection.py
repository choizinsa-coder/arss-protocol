"""
governance_projection.py
Area 12 → Area 6 (Bridge) 인터페이스

Governance State 를 Bridge가 소비하는 단순 상태값으로 투영한다.
Bridge는 VALID / INVALID / REVIEW 만 소비한다 (권한 정보 미포함).

제약 4 (EAG-S272): GSP → Area 6 전달 시점 통제는 Area 6 구현 EAG 시 명기.
이 모듈은 인메모리 dict 만 반환하며 디스크 영속화하지 않는다 (제약 2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from .governance_state_builder import VALID, INVALID, REVIEW


def _projection_hash(governance_state: dict) -> str:
    """
    동일 입력 동일 출력 보장을 위한 결정론적 해시.
    declared_tokens + approval verdict 집합 기반.
    """
    stable = {
        "session": governance_state.get("session"),
        "declared_tokens": sorted(governance_state.get("declared_tokens", [])),
        "verdict": governance_state.get("compiler_verdict"),
        "approval_ids": sorted(
            a.get("approval_id") or "" for a in governance_state.get("approvals", [])
        ),
    }
    serialized = json.dumps(stable, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_bridge_projection(
    governance_state: dict,
    session: Optional[str] = None,
) -> dict:
    """
    Governance State Projection (GSP) 생성.

    Bridge 소비 계약:
      governance_state: VALID | INVALID | REVIEW
      approval_count:   정수
      required_eag_present: bool
      chain_complete:   bool

    권한·scope·actor·expiry 정보를 포함하지 않는다 (Evidence Compiler 원칙).
    """
    verdict = governance_state.get("compiler_verdict", REVIEW)

    # 폴백 강제 (제약 1): 알 수 없는 verdict → REVIEW
    if verdict not in (VALID, INVALID, REVIEW):
        verdict = REVIEW

    approval_count = governance_state.get("approval_count", 0)
    chain_complete = governance_state.get("chain_complete", False)

    # required_eag_present: 선언된 토큰이 1개 이상이고 증거가 연결됨
    required_eag_present = (
        governance_state.get("declared_count", 0) > 0 and approval_count > 0
    )

    projection = {
        "projection_id": f"GSP-{session or governance_state.get('session') or 'UNKNOWN'}",
        "session": session or governance_state.get("session"),
        "governance_state": verdict,
        "approval_count": approval_count,
        "required_eag_present": required_eag_present,
        "chain_complete": chain_complete,
        "_persisted": False,  # 디스크 비영속화 명시 (제약 2)
    }
    projection["projection_hash"] = _projection_hash(governance_state)
    return projection

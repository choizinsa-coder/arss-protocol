"""
governance_state_builder.py
Area 12 — Governance Evidence Compiler core

EAG approval 영수증을 정규화하여 Governance State를 산출한다.

검증 항목 (실제 EAG 토큰 구조 RAW 기반):
  - approval 존재 확인
  - approval_hash 형식 유효성 (sha256: + 64 hex)
  - event_hash 형식 유효성 (sha256: + 64 hex)
  - chain 완결성 (세션 레벨 커버리지)

폴백 원칙 (EAG-S272 제약 1):
  검증 누락·무결성 의심 엣지 케이스는 INVALID 가 아닌 REVIEW 로 수렴.
"""

from __future__ import annotations

import re
from typing import Optional

# sha256:<64 hex> 형식
_HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

# Governance State verdict
VALID = "VALID"
INVALID = "INVALID"
REVIEW = "REVIEW"


def _is_valid_hash(value: Optional[str]) -> bool:
    """approval_hash / event_hash 형식 유효성 확인."""
    if not isinstance(value, str):
        return False
    return bool(_HASH_PATTERN.match(value))


def _extract_tokens(eag_chain) -> list:
    """
    SESSION_CONTEXT.eag_chain 에서 EAG 토큰 문자열 목록을 추출한다.

    두 형식 모두 수용 (캐디 IMPLEMENTABLE NB):
      - 단일 문자열: "EAG-S271-AICS-001, EAG-S271-DIRECTCH-001"
      - 리스트:      ["EAG-S271-AICS-001", "EAG-S271-DIRECTCH-001"]
    """
    if eag_chain is None:
        return []
    if isinstance(eag_chain, str):
        return [t.strip() for t in eag_chain.split(",") if t.strip()]
    if isinstance(eag_chain, list):
        return [str(t).strip() for t in eag_chain if str(t).strip()]
    # 알 수 없는 타입 → 빈 목록 (상위에서 REVIEW 수렴)
    return []


def _normalize_approval(approval: dict) -> dict:
    """
    단일 approval 영수증을 정규화한다.
    실제 토큰 구조 필드만 추출 (권한 정보 생성 금지).

    반환: {approval_id, stage, approved_by, event_hash,
           approval_hash, hash_ok, verdict}
    """
    approval_id = approval.get("approval_id")
    stage = approval.get("stage")
    approved_by = approval.get("approved_by")
    event_hash = approval.get("event_hash")
    approval_hash = approval.get("approval_hash")

    event_ok = _is_valid_hash(event_hash)
    approval_ok = _is_valid_hash(approval_hash)

    # 필수 필드 부재 → REVIEW (폴백, 제약 1)
    if approval_id is None or stage is None or approved_by is None:
        verdict = REVIEW
    elif event_ok and approval_ok:
        verdict = VALID
    elif (event_hash is None) and (approval_hash is None):
        # 해시 자체가 없음 → 무결성 판정 불가 → REVIEW
        verdict = REVIEW
    else:
        # 해시는 있으나 형식 불일치 → 변조 의심 → INVALID
        verdict = INVALID

    return {
        "approval_id": approval_id,
        "stage": stage,
        "approved_by": approved_by,
        "event_hash": event_hash,
        "approval_hash": approval_hash,
        "hash_ok": event_ok and approval_ok,
        "verdict": verdict,
    }


def _aggregate_verdict(normalized: list, chain_complete: bool) -> str:
    """
    개별 approval verdict 와 chain 완결성에서 최종 Governance State 산출.

    폴백 규칙 (제약 1):
      - approval 1건이라도 INVALID → 전체 INVALID
      - approval 1건이라도 REVIEW → 전체 REVIEW (INVALID 없을 때)
      - chain 불완전 → REVIEW
      - 모두 VALID + chain 완결 → VALID
    """
    if not normalized:
        # 증거 없음 → 판정 불가 → REVIEW (폴백)
        return REVIEW

    has_invalid = any(n["verdict"] == INVALID for n in normalized)
    has_review = any(n["verdict"] == REVIEW for n in normalized)

    if has_invalid:
        return INVALID
    if has_review:
        return REVIEW
    if not chain_complete:
        return REVIEW
    return VALID


def build_governance_state(
    eag_chain,
    approvals: Optional[list] = None,
    session: Optional[str] = None,
) -> dict:
    """
    Governance State 생성 (Area 12 핵심 진입점).

    Args:
        eag_chain: SESSION_CONTEXT.eag_chain (문자열 또는 리스트)
        approvals: EAG approval 영수증 dict 목록.
                   None 이면 토큰만 추출하고 증거 미연결로 처리.
        session: 현재 세션 식별자 (예: "S272").

    Returns:
        Governance State dict
    """
    tokens = _extract_tokens(eag_chain)
    approvals = approvals or []

    normalized = [_normalize_approval(a) for a in approvals if isinstance(a, dict)]

    # chain 완결성: 선언된 토큰 수와 정규화된 증거 수 일치 여부
    # 토큰이 없으면 완결성 판정 불가 → False
    if not tokens:
        chain_complete = False
    else:
        chain_complete = len(normalized) >= len(tokens)

    verdict = _aggregate_verdict(normalized, chain_complete)

    return {
        "session": session,
        "declared_tokens": tokens,
        "declared_count": len(tokens),
        "approvals": normalized,
        "approval_count": len(normalized),
        "chain_complete": chain_complete,
        "compiler_verdict": verdict,
    }

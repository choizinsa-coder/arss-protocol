"""
deadlock_models.py  v1.0
AIBA Governance 3-5: Deadlock Protocol 공통 데이터 구조
EAG: EAG-S263-3-5-001
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationResult:
    """에이전트 검증 결과. TRUST_NOT_READY 시 violations 에 위반 항목을 채운다."""
    status:     str                  # TRUST_READY | TRUST_NOT_READY | TRUST_ADVISORY
    violations: list[str] = field(default_factory=list)   # 가드레일 위반 항목
    advisories: list[str] = field(default_factory=list)   # 비차단 권고 항목


@dataclass
class DeadlockState:
    """설계-검증 라운드 추적 상태."""
    proposal_id:          str
    round_count:          int  = 0
    escalation_required:  bool = False
    warning_issued:       bool = False
    last_updated_session: Optional[str] = None

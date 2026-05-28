"""
mcp_filter_policy.py  v1.0.1
READ_ONLY_COGNITION_MODE Filter Specification 구현
설계: 도미 (BRIEFING-DOMI-S129-001 + Recovery Protocol FINAL ANCHOR S130)
EAG-1 승인: 비오(Joshua) S129
EAG-2 승인: 비오(Joshua) S129
EAG-3 승인 (Recovery): 비오(Joshua) S130
TRUST_READY: PASS (제니 S129, BRIEFING-JENI-S129-002)

변경 이력:
- v1.0.0 (S129): 최초 구현
- v1.0.1 (S130): HC-T-04 (filter policy violation escalation) -> HARD_CONTAINMENT 연결
                 _record_violation 내 CONTAINMENT_THRESHOLD 초과 시 enter_containment("HC-T-04") 호출

[구현 범위]
- 강등 판정 기준 D-1~D-5
- 필터링 허용 범위 A-1~A-5
- 필터링 차단 범위 B-1~B-5
- 경계 계약 C-1~C-4
- TA-4: 화이트리스트 하드코딩 고정 (런타임 변경 금지)
- HC-T-04: forbidden category 반복 요청 -> HARD_CONTAINMENT
"""

from __future__ import annotations
import logging as _logging

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CognitionMode(Enum):
    NORMAL = "NORMAL"
    READ_ONLY_COGNITION_MODE = "READ_ONLY_COGNITION_MODE"
    HARD_CONTAINMENT = "HARD_CONTAINMENT"


class FilterVerdict(Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class MetadataCategory(Enum):
    """
    TA-4 준수: 카테고리 목록 하드코딩 고정.
    런타임 동적 변경 금지.
    """
    LOAD_STATE = "LOAD_STATE"
    STATIC_OPERATIONAL_FLAGS = "STATIC_OPERATIONAL_FLAGS"
    NON_SENSITIVE_ROUTING = "NON_SENSITIVE_ROUTING"
    AUDIT_REFERENCE = "AUDIT_REFERENCE"
    STATIC_WHITELIST = "STATIC_WHITELIST"

    AUTHORITY_METADATA = "AUTHORITY_METADATA"
    CROSS_SHARD_CORRELATION = "CROSS_SHARD_CORRELATION"
    OPERATIONAL_PRIORITY = "OPERATIONAL_PRIORITY"
    HISTORICAL_COGNITION = "HISTORICAL_COGNITION"
    NON_WHITELISTED_NAMESPACE = "NON_WHITELISTED_NAMESPACE"

    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# TA-4: 화이트리스트 고정
# ---------------------------------------------------------------------------

_ALLOWED_CATEGORIES: frozenset[MetadataCategory] = frozenset({
    MetadataCategory.LOAD_STATE,
    MetadataCategory.STATIC_OPERATIONAL_FLAGS,
    MetadataCategory.NON_SENSITIVE_ROUTING,
    MetadataCategory.AUDIT_REFERENCE,
    MetadataCategory.STATIC_WHITELIST,
})

_BLOCKED_CATEGORIES: frozenset[MetadataCategory] = frozenset({
    MetadataCategory.AUTHORITY_METADATA,
    MetadataCategory.CROSS_SHARD_CORRELATION,
    MetadataCategory.OPERATIONAL_PRIORITY,
    MetadataCategory.HISTORICAL_COGNITION,
    MetadataCategory.NON_WHITELISTED_NAMESPACE,
    MetadataCategory.UNKNOWN,
})

_WHITELIST_INTEGRITY_HASH: str = hashlib.sha256(
    json.dumps(
        sorted(c.value for c in _ALLOWED_CATEGORIES),
        sort_keys=True
    ).encode()
).hexdigest()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LoadState:
    shard_complete: bool = True
    metadata_index_ok: bool = True
    nonce_continuity_ok: bool = True
    audit_broker_ok: bool = True
    authority_integrity_ok: bool = True
    visibility_contract_ok: bool = True
    audit_continuity_ok: bool = True
    namespace_classified: bool = True
    routing_scope_resolved: bool = True
    retrieval_whitelisted: bool = True


@dataclass
class MetadataRequest:
    namespace: str
    category: MetadataCategory
    requester_id: str
    request_id: str = ""


@dataclass
class FilterResult:
    verdict: FilterVerdict
    category: MetadataCategory
    reason: str
    audit_required: bool = True
    containment_triggered: bool = False


@dataclass
class ViolationRecord:
    namespace: str
    category: MetadataCategory
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Degradation Detector (D-1~D-5)
# ---------------------------------------------------------------------------

class DegradationDetector:
    @staticmethod
    def evaluate(state: LoadState) -> tuple[bool, str]:
        if not state.shard_complete:
            return True, "D-1: shard incomplete"
        if not state.metadata_index_ok:
            return True, "D-1: metadata index mismatch"
        if not state.nonce_continuity_ok:
            return True, "D-1: nonce continuity partial failure"
        if not state.audit_broker_ok:
            return True, "D-1: audit broker unavailable"
        if not state.authority_integrity_ok:
            return True, "D-2: authority integrity verification failed"
        if not state.visibility_contract_ok:
            return True, "D-3: visibility contract (Lock-7) violation detected"
        if not state.audit_continuity_ok:
            return True, "D-4: audit continuity incomplete"
        if not state.namespace_classified:
            return True, "D-5: unclassified namespace"
        if not state.routing_scope_resolved:
            return True, "D-5: unresolved routing scope"
        if not state.retrieval_whitelisted:
            return True, "D-5: non-whitelisted retrieval request"
        return False, ""


# ---------------------------------------------------------------------------
# Filter Policy
# ---------------------------------------------------------------------------

class FilterPolicy:
    """
    READ_ONLY_COGNITION_MODE 메타데이터 필터링 정책.
    default: DENY (Fail-Closed).
    HC-T-04: CONTAINMENT_THRESHOLD 초과 시 enter_containment("HC-T-04") 호출.
    """

    CONTAINMENT_THRESHOLD: int = 3

    def __init__(self) -> None:
        self._violation_log: list[ViolationRecord] = []
        self._containment_active: bool = False
        self._verify_whitelist_integrity()

    def _verify_whitelist_integrity(self) -> None:
        current_hash = hashlib.sha256(
            json.dumps(
                sorted(c.value for c in _ALLOWED_CATEGORIES),
                sort_keys=True
            ).encode()
        ).hexdigest()
        if current_hash != _WHITELIST_INTEGRITY_HASH:
            raise RuntimeError(
                "WHITELIST_INTEGRITY_VIOLATION: "
                "허용 카테고리 목록이 변조되었습니다."
            )

    def evaluate(self, request: MetadataRequest) -> FilterResult:
        if self._containment_active:
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason="C-2: HARD_CONTAINMENT active — all access denied",
                audit_required=True,
                containment_triggered=True,
            )

        if request.category == MetadataCategory.UNKNOWN:
            self._record_violation(request)
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason="C-3: ambiguous category — cannot classify, blocked",
                audit_required=True,
            )

        if request.category in _ALLOWED_CATEGORIES:
            return FilterResult(
                verdict=FilterVerdict.ALLOW,
                category=request.category,
                reason=f"ALLOWED: {request.category.value}",
                audit_required=True,
            )

        if request.category in _BLOCKED_CATEGORIES:
            self._record_violation(request)
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason=f"C-1: blocked category {request.category.value} — deny + audit",
                audit_required=True,
            )

        self._record_violation(request)
        return FilterResult(
            verdict=FilterVerdict.DENY,
            category=request.category,
            reason="FAIL_CLOSED: unclassified — default deny",
            audit_required=True,
        )

    def _record_violation(self, request: MetadataRequest) -> None:
        """
        C-2 + HC-T-04: 위반 기록 및 HARD_CONTAINMENT 판정.
        동일 namespace 위반 횟수 >= CONTAINMENT_THRESHOLD 시
        enter_containment("HC-T-04") 호출.
        """
        record = ViolationRecord(
            namespace=request.namespace,
            category=request.category,
        )
        self._violation_log.append(record)

        namespace_violations = [
            v for v in self._violation_log
            if v.namespace == request.namespace
        ]
        if len(namespace_violations) >= self.CONTAINMENT_THRESHOLD:
            self._containment_active = True
            # HC-T-04: HARD_CONTAINMENT 진입
            _trigger_hct04()

    def get_mode(self) -> CognitionMode:
        if self._containment_active:
            return CognitionMode.HARD_CONTAINMENT
        return CognitionMode.READ_ONLY_COGNITION_MODE

    def get_violation_count(self, namespace: Optional[str] = None) -> int:
        if namespace:
            return sum(1 for v in self._violation_log if v.namespace == namespace)
        return len(self._violation_log)

    def get_load_state_metadata(self) -> dict:
        return {
            "mode": self.get_mode().value,
            "load_state": "READ_ONLY_COGNITION_MODE",
            "visibility_level": "LIMITED",
            "integrity_status": "DEGRADED",
            "write_enabled": False,
            "audit_required": True,
            "containment_active": self._containment_active,
        }


def _trigger_hct04() -> None:
    """HC-T-04: filter policy violation escalation -> HARD_CONTAINMENT 진입."""
    try:
        from mcp_containment_state import enter_containment
        enter_containment("HC-T-04")
    except Exception as _rule6_e:
        _logging.debug("RULE6 mcp_filter_policy: %s", _rule6_e)

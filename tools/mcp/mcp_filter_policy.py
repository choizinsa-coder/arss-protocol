"""
mcp_filter_policy.py
READ_ONLY_COGNITION_MODE Filter Specification 구현
설계: 도미 (BRIEFING-DOMI-S129-001)
EAG-1 승인: 비오(Joshua) S129
EAG-2 승인: 비오(Joshua) S129
TRUST_READY: PASS (제니 S129, BRIEFING-JENI-S129-002)

[구현 범위]
- 강등 판정 기준 D-1~D-5
- 필터링 허용 범위 A-1~A-5
- 필터링 차단 범위 B-1~B-5
- 경계 계약 C-1~C-4
- TA-4: 화이트리스트 하드코딩 고정 (런타임 변경 금지)

[구현 범위 제외]
- HARD_CONTAINMENT 복구 조건 (위험 4 — 별도 Recovery Protocol 설계 필요)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
    런타임 동적 변경 금지. EAG-1 승인 설정 기반.
    """
    # 허용 범주 (A-1~A-5)
    LOAD_STATE = "LOAD_STATE"
    STATIC_OPERATIONAL_FLAGS = "STATIC_OPERATIONAL_FLAGS"
    NON_SENSITIVE_ROUTING = "NON_SENSITIVE_ROUTING"
    AUDIT_REFERENCE = "AUDIT_REFERENCE"
    STATIC_WHITELIST = "STATIC_WHITELIST"

    # 차단 범주 (B-1~B-5)
    AUTHORITY_METADATA = "AUTHORITY_METADATA"
    CROSS_SHARD_CORRELATION = "CROSS_SHARD_CORRELATION"
    OPERATIONAL_PRIORITY = "OPERATIONAL_PRIORITY"
    HISTORICAL_COGNITION = "HISTORICAL_COGNITION"
    NON_WHITELISTED_NAMESPACE = "NON_WHITELISTED_NAMESPACE"

    # 미분류 — FAIL_CLOSED 처리
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# TA-4: 화이트리스트 고정 (하드코딩 — 런타임 변경 금지)
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

# 화이트리스트 무결성 검증용 해시 (TA-4 — 변조 감지)
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
    """시스템 현재 로드 상태 (D-1~D-5 판정 입력)"""
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
    """메타데이터 접근 요청"""
    namespace: str
    category: MetadataCategory
    requester_id: str
    request_id: str = ""


@dataclass
class FilterResult:
    """필터링 결과"""
    verdict: FilterVerdict
    category: MetadataCategory
    reason: str
    audit_required: bool = True
    containment_triggered: bool = False


@dataclass
class ViolationRecord:
    """경계 위반 기록 (C-2 HARD_CONTAINMENT 판정용)"""
    namespace: str
    category: MetadataCategory
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Degradation Detector (D-1~D-5)
# ---------------------------------------------------------------------------

class DegradationDetector:
    """
    강등 판정 기준 D-1~D-5 구현.
    조건 하나라도 만족 시 READ_ONLY_COGNITION_MODE 강등.
    """

    @staticmethod
    def evaluate(state: LoadState) -> tuple[bool, str]:
        """
        Returns (should_degrade: bool, reason: str)
        """
        # D-1: PARTIAL_LOAD 상태
        if not state.shard_complete:
            return True, "D-1: shard incomplete"
        if not state.metadata_index_ok:
            return True, "D-1: metadata index mismatch"
        if not state.nonce_continuity_ok:
            return True, "D-1: nonce continuity partial failure"
        if not state.audit_broker_ok:
            return True, "D-1: audit broker unavailable"

        # D-2: Authority Integrity 실패
        if not state.authority_integrity_ok:
            return True, "D-2: authority integrity verification failed"

        # D-3: Visibility Contract 위반 가능성
        if not state.visibility_contract_ok:
            return True, "D-3: visibility contract (Lock-7) violation detected"

        # D-4: Audit Continuity 불완전
        if not state.audit_continuity_ok:
            return True, "D-4: audit continuity incomplete"

        # D-5: Fail-Closed Trigger
        if not state.namespace_classified:
            return True, "D-5: unclassified namespace"
        if not state.routing_scope_resolved:
            return True, "D-5: unresolved routing scope"
        if not state.retrieval_whitelisted:
            return True, "D-5: non-whitelisted retrieval request"

        return False, ""


# ---------------------------------------------------------------------------
# Filter Policy (A-1~A-5 / B-1~B-5 / C-1~C-4)
# ---------------------------------------------------------------------------

class FilterPolicy:
    """
    READ_ONLY_COGNITION_MODE 메타데이터 필터링 정책.
    default: DENY (Fail-Closed).
    """

    # C-2: 반복 위반 임계값
    CONTAINMENT_THRESHOLD: int = 3

    def __init__(self) -> None:
        self._violation_log: list[ViolationRecord] = []
        self._containment_active: bool = False
        self._verify_whitelist_integrity()

    def _verify_whitelist_integrity(self) -> None:
        """TA-4: 화이트리스트 무결성 검증"""
        current_hash = hashlib.sha256(
            json.dumps(
                sorted(c.value for c in _ALLOWED_CATEGORIES),
                sort_keys=True
            ).encode()
        ).hexdigest()
        if current_hash != _WHITELIST_INTEGRITY_HASH:
            raise RuntimeError(
                "WHITELIST_INTEGRITY_VIOLATION: "
                "허용 카테고리 목록이 변조되었습니다. "
                "EAG-1 승인 없는 변경은 금지됩니다."
            )

    def evaluate(self, request: MetadataRequest) -> FilterResult:
        """
        메타데이터 접근 요청 평가.
        C-2: HARD_CONTAINMENT 활성 시 전체 차단.
        """
        # C-2: HARD_CONTAINMENT 상태 — 전체 차단
        if self._containment_active:
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason="C-2: HARD_CONTAINMENT active — all access denied",
                audit_required=True,
                containment_triggered=True,
            )

        # C-3: 모호성 → 차단 (추정 금지)
        if request.category == MetadataCategory.UNKNOWN:
            self._record_violation(request)
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason="C-3: ambiguous category — cannot classify, blocked",
                audit_required=True,
            )

        # 허용 범주 (A-1~A-5)
        if request.category in _ALLOWED_CATEGORIES:
            return FilterResult(
                verdict=FilterVerdict.ALLOW,
                category=request.category,
                reason=f"ALLOWED: {request.category.value}",
                audit_required=True,
            )

        # 차단 범주 (B-1~B-5) — C-1 적용
        if request.category in _BLOCKED_CATEGORIES:
            self._record_violation(request)
            return FilterResult(
                verdict=FilterVerdict.DENY,
                category=request.category,
                reason=f"C-1: blocked category {request.category.value} — deny + audit",
                audit_required=True,
            )

        # 분류 불가 — FAIL_CLOSED
        self._record_violation(request)
        return FilterResult(
            verdict=FilterVerdict.DENY,
            category=request.category,
            reason="FAIL_CLOSED: unclassified — default deny",
            audit_required=True,
        )

    def _record_violation(self, request: MetadataRequest) -> None:
        """
        C-2: 위반 기록 및 HARD_CONTAINMENT 판정.
        동일 namespace 반복 위반 시 격리 전환.
        """
        record = ViolationRecord(
            namespace=request.namespace,
            category=request.category,
        )
        self._violation_log.append(record)

        # 동일 namespace 위반 횟수 집계
        namespace_violations = [
            v for v in self._violation_log
            if v.namespace == request.namespace
        ]
        if len(namespace_violations) >= self.CONTAINMENT_THRESHOLD:
            self._containment_active = True

    def get_mode(self) -> CognitionMode:
        if self._containment_active:
            return CognitionMode.HARD_CONTAINMENT
        return CognitionMode.READ_ONLY_COGNITION_MODE

    def get_violation_count(self, namespace: Optional[str] = None) -> int:
        if namespace:
            return sum(
                1 for v in self._violation_log
                if v.namespace == namespace
            )
        return len(self._violation_log)

    def get_load_state_metadata(self) -> dict:
        """
        C-4 / Lock-7: LOAD_STATE 가시성 계약.
        상태 가시성 허용, 권한 구조 노출 금지.
        """
        return {
            "mode": self.get_mode().value,
            "load_state": "READ_ONLY_COGNITION_MODE",
            "visibility_level": "LIMITED",
            "integrity_status": "DEGRADED",
            "write_enabled": False,
            "audit_required": True,
            "containment_active": self._containment_active,
            # 권한 구조 노출 금지 — authority lineage 미포함
        }

    # HARD_CONTAINMENT 복구 조건 미구현
    # [DEFERRED] 위험 4 — Recovery Protocol 별도 설계 필요 (도미 의뢰 예정)

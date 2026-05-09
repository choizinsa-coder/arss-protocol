"""
stale_state_detector.py
S101 STATE AUTHORITY ARCHITECTURE — CORE-T0/T1 stale detection
Design ref: REVISION-1 + T2 TIMEOUT POLICY
EAG-2 approved by: 비오(Joshua) S111

Default behavior: DENY on unknown, HOLD on ambiguous.
Stale = SESSION_CONTEXT awareness field diverges from VPS canonical.
"""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class StaleLevel(Enum):
    CLEAN = "CLEAN"
    T1_STALE = "T1_STALE"        # awareness sync mismatch — HOLD
    T0_STALE = "T0_STALE"        # canonical root mismatch — HARD_STOP
    UNKNOWN = "UNKNOWN"          # cannot determine — DENY


class DetectionResult(Enum):
    PASS = "PASS"
    HOLD = "HOLD"
    HARD_STOP = "HARD_STOP"
    DENY = "DENY"


# CORE-T0: canonical survival fields
CORE_T0_FIELDS = [
    "chain.tip",
    "last_rpu",
    "scoring_ledger_hash",
    "enforcement_active",
]

# CORE-T1: awareness reflection fields
CORE_T1_FIELDS = [
    "task_status",
    "eag_stage",
    "active_tasks",
    "blocked_tasks",
    "hold_tasks",
]

# EXCLUDED: narrative — never stale-detected
EXCLUDED_FIELDS = [
    "note",
    "detail",
    "context_summary",
    "narrative_metadata",
    "agent_focus",
    "session_reentry",
]


@dataclass
class FieldStaleReport:
    field_name: str
    tier: str
    session_context_value: Any
    canonical_value: Any
    is_stale: bool
    stale_level: StaleLevel
    detection_result: DetectionResult
    reason: str


@dataclass
class StaleDetectionReport:
    overall_result: DetectionResult
    stale_level: StaleLevel
    t0_violations: list[FieldStaleReport] = field(default_factory=list)
    t1_violations: list[FieldStaleReport] = field(default_factory=list)
    clean_fields: list[str] = field(default_factory=list)
    excluded_fields: list[str] = field(default_factory=list)
    error: Optional[str] = None


def _extract_nested(data: dict, dotted_key: str) -> Any:
    """점 표기법으로 중첩 필드 추출. 경로 없으면 None 반환."""
    keys = dotted_key.split(".")
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _compute_hash(value: Any) -> str:
    """값의 SHA256 해시 반환 (canonical comparison용)."""
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _check_t0_field(
    field_name: str,
    sc_value: Any,
    canonical_value: Any,
) -> FieldStaleReport:
    """T0 필드 단건 검증. 불일치 = HARD_STOP."""
    if sc_value is None and canonical_value is None:
        return FieldStaleReport(
            field_name=field_name,
            tier="T0",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=False,
            stale_level=StaleLevel.CLEAN,
            detection_result=DetectionResult.PASS,
            reason="both None — no data to compare",
        )
    if sc_value is None or canonical_value is None:
        return FieldStaleReport(
            field_name=field_name,
            tier="T0",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=True,
            stale_level=StaleLevel.T0_STALE,
            detection_result=DetectionResult.HARD_STOP,
            reason=f"T0 field missing on one side: sc={sc_value!r} canonical={canonical_value!r}",
        )
    sc_hash = _compute_hash(sc_value)
    can_hash = _compute_hash(canonical_value)
    if sc_hash != can_hash:
        return FieldStaleReport(
            field_name=field_name,
            tier="T0",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=True,
            stale_level=StaleLevel.T0_STALE,
            detection_result=DetectionResult.HARD_STOP,
            reason=f"T0 hash mismatch: sc_hash={sc_hash[:16]}... canonical_hash={can_hash[:16]}...",
        )
    return FieldStaleReport(
        field_name=field_name,
        tier="T0",
        session_context_value=sc_value,
        canonical_value=canonical_value,
        is_stale=False,
        stale_level=StaleLevel.CLEAN,
        detection_result=DetectionResult.PASS,
        reason="T0 hash match",
    )


def _check_t1_field(
    field_name: str,
    sc_value: Any,
    canonical_value: Any,
) -> FieldStaleReport:
    """T1 필드 단건 검증. 불일치 = HOLD."""
    if sc_value is None and canonical_value is None:
        return FieldStaleReport(
            field_name=field_name,
            tier="T1",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=False,
            stale_level=StaleLevel.CLEAN,
            detection_result=DetectionResult.PASS,
            reason="both None — no data to compare",
        )
    if sc_value is None or canonical_value is None:
        return FieldStaleReport(
            field_name=field_name,
            tier="T1",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=True,
            stale_level=StaleLevel.T1_STALE,
            detection_result=DetectionResult.HOLD,
            reason=f"T1 field missing on one side: sc={sc_value!r} canonical={canonical_value!r}",
        )
    sc_hash = _compute_hash(sc_value)
    can_hash = _compute_hash(canonical_value)
    if sc_hash != can_hash:
        return FieldStaleReport(
            field_name=field_name,
            tier="T1",
            session_context_value=sc_value,
            canonical_value=canonical_value,
            is_stale=True,
            stale_level=StaleLevel.T1_STALE,
            detection_result=DetectionResult.HOLD,
            reason=f"T1 hash mismatch: sc_hash={sc_hash[:16]}... canonical_hash={can_hash[:16]}...",
        )
    return FieldStaleReport(
        field_name=field_name,
        tier="T1",
        session_context_value=sc_value,
        canonical_value=canonical_value,
        is_stale=False,
        stale_level=StaleLevel.CLEAN,
        detection_result=DetectionResult.PASS,
        reason="T1 hash match",
    )


def detect_stale(
    session_context: dict,
    canonical_snapshot: dict,
) -> StaleDetectionReport:
    """
    SESSION_CONTEXT awareness fields와 canonical snapshot을 비교하여
    stale state를 감지한다.

    Args:
        session_context: SESSION_CONTEXT.json 파싱 결과
        canonical_snapshot: VPS canonical state snapshot dict
            {field_name: value} 형식. CORE-T0/T1 필드 포함.

    Returns:
        StaleDetectionReport
    """
    if not isinstance(session_context, dict):
        return StaleDetectionReport(
            overall_result=DetectionResult.DENY,
            stale_level=StaleLevel.UNKNOWN,
            error="session_context must be dict — DENY (unknown input type)",
        )
    if not isinstance(canonical_snapshot, dict):
        return StaleDetectionReport(
            overall_result=DetectionResult.DENY,
            stale_level=StaleLevel.UNKNOWN,
            error="canonical_snapshot must be dict — DENY (unknown input type)",
        )

    t0_violations: list[FieldStaleReport] = []
    t1_violations: list[FieldStaleReport] = []
    clean_fields: list[str] = []

    # T0 검증
    for field_name in CORE_T0_FIELDS:
        sc_val = _extract_nested(session_context, field_name)
        can_val = canonical_snapshot.get(field_name)
        report = _check_t0_field(field_name, sc_val, can_val)
        if report.is_stale:
            t0_violations.append(report)
        else:
            clean_fields.append(field_name)

    # T1 검증
    for field_name in CORE_T1_FIELDS:
        sc_val = _extract_nested(session_context, field_name)
        can_val = canonical_snapshot.get(field_name)
        report = _check_t1_field(field_name, sc_val, can_val)
        if report.is_stale:
            t1_violations.append(report)
        else:
            clean_fields.append(field_name)

    # 종합 판정 — T0 위반 시 전 하위 tier freeze
    if t0_violations:
        return StaleDetectionReport(
            overall_result=DetectionResult.HARD_STOP,
            stale_level=StaleLevel.T0_STALE,
            t0_violations=t0_violations,
            t1_violations=t1_violations,
            clean_fields=clean_fields,
            excluded_fields=EXCLUDED_FIELDS,
        )
    if t1_violations:
        return StaleDetectionReport(
            overall_result=DetectionResult.HOLD,
            stale_level=StaleLevel.T1_STALE,
            t0_violations=[],
            t1_violations=t1_violations,
            clean_fields=clean_fields,
            excluded_fields=EXCLUDED_FIELDS,
        )
    return StaleDetectionReport(
        overall_result=DetectionResult.PASS,
        stale_level=StaleLevel.CLEAN,
        t0_violations=[],
        t1_violations=[],
        clean_fields=clean_fields,
        excluded_fields=EXCLUDED_FIELDS,
    )


def is_narrative_field(field_name: str) -> bool:
    """해당 필드가 narrative(excluded) 필드인지 반환."""
    return any(field_name.startswith(ex) for ex in EXCLUDED_FIELDS)

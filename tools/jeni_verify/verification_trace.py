"""
verification_trace.py
Verification Trace 최소 스키마 (Phase 1)

배경: INC-S342-VERIFICATION-EVIDENCE-MISMATCH-001
목적: 검증 주체(예: 제니)가 인용한 Evidence Artifact 값이 실제 원문과
     대조 가능하도록 최소한의 추적 기록을 구조화한다.

설계: 도미(S344) / IMPLEMENTABLE: 캐디(S344) / TRUST_READY: 제니(S344) /
EAG: EAG-S344-VERIFICATION-TRACE-P1-001 (비오)

범위(Phase 1): 스키마 정의만. 기록 시점/시스템 결합/자동검증 로직은
Phase 2 이후로 분리(도미 SELF-CRITIQUE 반영).

설계 원칙: 1 trace = 1 assertion x 1 evidence x 1 verdict.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict

from .schemas import sha256_hex, utc_now_iso

EVIDENCE_SNIPPET_MAX_LEN = 200


class TraceVerdict:
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    _VALID = (PASS, FAIL, INCONCLUSIVE)


@dataclass
class VerificationTraceRecord:
    """1건의 검증 판정에 대한 최소 추적 레코드."""
    assertion_id: str
    evidence_source: str
    evidence_snippet: str
    verdict: str
    verifier_agent: str
    trace_id: str = field(default_factory=lambda: f"TRACE-{uuid.uuid4()}")
    evidence_hash: str = field(default="")
    generated_at: str = field(default_factory=utc_now_iso)

    def __post_init__(self) -> None:
        if len(self.evidence_snippet) > EVIDENCE_SNIPPET_MAX_LEN:
            raise ValueError(
                f"evidence_snippet exceeds {EVIDENCE_SNIPPET_MAX_LEN} char limit "
                f"(got {len(self.evidence_snippet)})"
            )
        if self.verdict not in TraceVerdict._VALID:
            raise ValueError(f"invalid verdict: {self.verdict!r}")
        if not self.evidence_hash:
            self.evidence_hash = sha256_hex(self.evidence_snippet)

    def to_dict(self) -> dict:
        return asdict(self)


def create_trace_record(
    assertion_id: str,
    evidence_source: str,
    evidence_snippet: str,
    verdict: str,
    verifier_agent: str,
) -> VerificationTraceRecord:
    """VerificationTraceRecord 생성 헬퍼."""
    return VerificationTraceRecord(
        assertion_id=assertion_id,
        evidence_source=evidence_source,
        evidence_snippet=evidence_snippet,
        verdict=verdict,
        verifier_agent=verifier_agent,
    )

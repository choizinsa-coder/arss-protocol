"""
metrics.py
영역 3 — 지표 1 Primary 소스 (도미 설계 승인율)
EAG-S271-JENIVERIFY-001

AIF v1.3 영역 13 매핑:
  지표 1 Primary = 영역 3 (TECHNICAL_MATCH + GOVERNANCE_ALIGN 통과율)
  Secondary = 영역 10 EAG (설계 품질 ≠ 사업 승인 — 본 모듈은 Primary 만)

DualResult 누적 → 통과율 산출. 영역 11 Decision Ledger / 영역 7 학습 원자료.
"""

from __future__ import annotations

from .schemas import DualResult, MetricsSnapshot


class MetricsCollector:
    """Dual Verification 결과 누적 → 지표 1 Primary 산출."""

    def __init__(self):
        self._results: list[DualResult] = []

    def record(self, result: DualResult) -> None:
        self._results.append(result)

    def snapshot(self) -> MetricsSnapshot:
        total = len(self._results)
        tech = sum(1 for r in self._results if r.technical_match)
        gov = sum(1 for r in self._results if r.governance_align)
        combined = sum(1 for r in self._results if r.passed)
        return MetricsSnapshot(
            total_count=total,
            technical_pass=tech,
            governance_pass=gov,
            combined_pass=combined,
        )

    def reset(self) -> None:
        self._results.clear()

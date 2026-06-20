"""
schemas.py
영역 3 Jeni Dual Verification (J2-3) — 데이터 구조
EAG-S271-JENIVERIFY-001 / 1차 스코프 (경로 B, execution_sandbox 제외)

Dual Verification = TECHNICAL_MATCH AND GOVERNANCE_ALIGN
안전성 증명서 = certificate_id + sha256 + test결과
지표 1 Primary = pass_count / total_count
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class JVReason:
    OK = "OK"
    TOKEN_INVALID = "JV_AICS_TOKEN_INVALID"
    SYNTAX_ERROR = "JV_SYNTAX_ERROR"
    FORBIDDEN_PATTERN = "JV_FORBIDDEN_PATTERN"
    PATH_ESCAPE = "JV_SANDBOX_PATH_ESCAPE"
    FORBIDDEN_EXTENSION = "JV_FORBIDDEN_EXTENSION"
    CERTIFICATE_INVALID = "JV_CERTIFICATE_INVALID"
    TECHNICAL_FAIL = "JV_TECHNICAL_MATCH_FAIL"
    GOVERNANCE_FAIL = "JV_GOVERNANCE_ALIGN_FAIL"
    SAFE_PASS_VIOLATION = "JV_SAFE_PASS_VIOLATION"


@dataclass
class ScanResult:
    """static_scan 결과."""
    ok: bool
    reason: str = JVReason.OK
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DualResult:
    """Dual Verification 결과 — TECHNICAL_MATCH + GOVERNANCE_ALIGN."""
    technical_match: bool
    governance_align: bool
    reason: str = JVReason.OK
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.technical_match and self.governance_align

    def to_dict(self) -> dict:
        d = asdict(self)
        d["passed"] = self.passed
        return d


@dataclass
class Certificate:
    """J2-3 안전성 증명서."""
    certificate_id: str
    sha256: str
    technical_match: bool
    governance_align: bool
    test_passed: int = 0
    test_failed: int = 0
    tx_id: str = ""
    domi_signature: str = ""
    jeni_signature: str = ""
    generated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MetricsSnapshot:
    """지표 1 Primary 소스 (도미 설계 승인율)."""
    total_count: int
    technical_pass: int
    governance_pass: int
    combined_pass: int

    @property
    def technical_rate(self) -> float:
        return self.technical_pass / self.total_count if self.total_count else 0.0

    @property
    def governance_rate(self) -> float:
        return self.governance_pass / self.total_count if self.total_count else 0.0

    @property
    def combined_rate(self) -> float:
        return self.combined_pass / self.total_count if self.total_count else 0.0

    def to_dict(self) -> dict:
        return {
            "total_count": self.total_count,
            "technical_pass": self.technical_pass,
            "governance_pass": self.governance_pass,
            "combined_pass": self.combined_pass,
            "technical_rate": round(self.technical_rate, 4),
            "governance_rate": round(self.governance_rate, 4),
            "combined_rate": round(self.combined_rate, 4),
        }

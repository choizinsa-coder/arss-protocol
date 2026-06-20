"""
Jeni Dual Verification (영역 3 / J2-3)
EAG-S271-JENIVERIFY-001 / 1차 스코프 (경로 B)

Dual Verification: TECHNICAL_MATCH + GOVERNANCE_ALIGN
안전성 증명서(J2-3) + 지표 1 Primary 산출.
execution_sandbox(subprocess 실제 실행)는 2차 스코프 — Hermes/별도 EAG.
"""

from .schemas import (
    ScanResult,
    DualResult,
    Certificate,
    MetricsSnapshot,
    JVReason,
    sha256_hex,
)
from .static_scan import static_scan, syntax_check, forbidden_pattern_scan
from .certificate import CertificateAuthority
from .dual_verifier import DualVerifier
from .metrics import MetricsCollector

__all__ = [
    "ScanResult",
    "DualResult",
    "Certificate",
    "MetricsSnapshot",
    "JVReason",
    "sha256_hex",
    "static_scan",
    "syntax_check",
    "forbidden_pattern_scan",
    "CertificateAuthority",
    "DualVerifier",
    "MetricsCollector",
]

__version__ = "1.0.0"

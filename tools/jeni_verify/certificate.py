"""
certificate.py
영역 3 — 안전성 증명서 (J2-3)
EAG-S271-JENIVERIFY-001

제니 TRUST-ADVISORY ② 반영:
  증명서 발급 후 sha256 봉인. 구현 에이전트가 검증 결과를 조작해도
  제니 런타임이 쥔 원본 sha256 과 대조되는 순간 차단(CERTIFICATE_INVALID).

증명서 저장 경로 무결성은 sandbox_validator.validate_write 와 연동(주입식).
"""

from __future__ import annotations

import json
import os
import uuid

from .schemas import Certificate, sha256_hex, JVReason


class CertificateAuthority:
    """증명서 발급·봉인·대조. 발급 권한은 제니 검증 계층에 독점."""

    def __init__(self, persist_dir: str | None = None):
        self._persist_dir = persist_dir

    def issue(self, file_content: str,
              technical_match: bool, governance_align: bool,
              test_passed: int = 0, test_failed: int = 0,
              tx_id: str = "", domi_signature: str = "",
              jeni_signature: str = "") -> Certificate:
        """검증 대상 파일 내용의 sha256 으로 증명서 봉인."""
        cert = Certificate(
            certificate_id=f"CERT-{uuid.uuid4()}",
            sha256=sha256_hex(file_content),
            technical_match=technical_match,
            governance_align=governance_align,
            test_passed=test_passed,
            test_failed=test_failed,
            tx_id=tx_id,
            domi_signature=domi_signature,
            jeni_signature=jeni_signature,
        )
        self._persist(cert)
        return cert

    def verify(self, file_content: str, cert: Certificate) -> bool:
        """
        파일 내용 해시와 증명서 봉인 해시 대조.
        불일치 = 파일 변조 or 증명서 위조 → CERTIFICATE_INVALID.
        """
        return sha256_hex(file_content) == cert.sha256

    def verify_reason(self, file_content: str, cert: Certificate) -> str:
        return JVReason.OK if self.verify(file_content, cert) else JVReason.CERTIFICATE_INVALID

    def _persist(self, cert: Certificate) -> None:
        if not self._persist_dir:
            return
        try:
            os.makedirs(self._persist_dir, exist_ok=True)
            path = os.path.join(self._persist_dir, f"{cert.certificate_id}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cert.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError:
            pass

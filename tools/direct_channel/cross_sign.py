"""
cross_sign.py
영역 8 — Cross-Sign 상호 서명 (HMAC-SHA256)
EAG-S271-DIRECTCH-001

도미·제니 상호 서명으로 캐디 경유 단편화/위변조를 차단한다.
payload_hash 불일치 시 서명 발행 원천 차단 (제니 검증 의견 ①).

1차 스코프: 결정론적 HMAC 서명. actor별 비밀키는 주입식
(실제 배포 시 /etc/aiba/secrets.env 에서 로드).
"""

from __future__ import annotations

import hmac
import hashlib

from .schemas import Transaction


class CrossSigner:
    """actor별 HMAC 서명자. 서명/검증 모두 상수시간 비교."""

    def __init__(self, signer_keys: dict[str, str]):
        # signer_keys: {"domi": secret, "jeni": secret, ...}
        self._keys = dict(signer_keys)

    def has_key(self, actor_id: str) -> bool:
        return actor_id in self._keys and bool(self._keys[actor_id])

    def sign(self, actor_id: str, tx: Transaction) -> str | None:
        """트랜잭션 정규화 문자열에 actor 비밀키로 HMAC 서명."""
        key = self._keys.get(actor_id)
        if not key:
            return None
        return hmac.new(
            key.encode("utf-8"),
            tx.canonical().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def verify(self, actor_id: str, tx: Transaction, signature: str) -> bool:
        """서명 검증. 상수시간 비교로 타이밍 공격 방어."""
        expected = self.sign(actor_id, tx)
        if expected is None or not signature:
            return False
        return hmac.compare_digest(expected, signature)

"""
direct_channel.py
영역 8 — Direct Channel 통합 오케스트레이션
EAG-S271-DIRECTCH-001 / 1차 스코프

파이프라인:
  AICS validate_token → Cross-Sign(domi+jeni) → transport(route_bidir) → WORM
  (B-2/B-3/WORM 은 transport=route_bidir 내부에 이미 존재 — 재구현 금지)

advisory ① : MiniMax 2차 미완료 동안 Constitutional/Governance 급 결정의
             채널 합의 처리를 제한 (minimax_enabled=False → CONSENSUS_RESTRICTED).
advisory ② : tx_id Replay 방지 (TransactionRegistry 실시간 블로킹).

transport_fn 은 주입식 — 기본 None(검증 전용). 실제 통합 시
autoroute_caller.route_bidir 를 주입.
"""

from __future__ import annotations

import uuid
from typing import Callable

from .schemas import (
    Transaction,
    CrossSignResult,
    DCReason,
    HIGH_IMPACT_CLASSES,
    sha256_hex,
)
from .cross_sign import CrossSigner
from .transaction_registry import TransactionRegistry


class DirectChannel:
    """도미-제니 직접 소통 채널 (Trust Layer)."""

    def __init__(self,
                 aics_runtime,
                 signer: CrossSigner,
                 registry: TransactionRegistry,
                 transport_fn: Callable | None = None,
                 minimax_enabled: bool = False):
        self._aics = aics_runtime
        self._signer = signer
        self._registry = registry
        self._transport = transport_fn
        # advisory ① : 1차 스코프는 MiniMax 미연동
        self._minimax_enabled = minimax_enabled

    def send(self,
             token_id: str,
             sender: str,
             receiver: str,
             session: int,
             chain_tip: str,
             payload: str,
             decision_class: str = "Operational") -> CrossSignResult:
        """
        도미→제니 직접 트랜잭션 전송 + Cross-Sign.
        반환: CrossSignResult
        """
        # ── 0. advisory ① : 고영향 결정 제한 (MiniMax 2차 전까지) ──────────
        if decision_class in HIGH_IMPACT_CLASSES and not self._minimax_enabled:
            return CrossSignResult(
                False, DCReason.CONSENSUS_RESTRICTED, stage="precheck")

        # ── 1. AICS Admission (validate_token) ────────────────────────────
        admit = self._aics.admit(
            token_id=token_id, actor_id=sender,
            current_session=session, current_chain_tip=chain_tip)
        if not admit.ok:
            return CrossSignResult(False, DCReason.TOKEN_INVALID, stage="aics")

        # ── 2. Hermes/미등록 발신자 차단 ──────────────────────────────────
        if not self._signer.has_key(sender):
            return CrossSignResult(False, DCReason.UNKNOWN_SIGNER, stage="signer")

        # ── 3. 트랜잭션 생성 (tx_id = 세션 고유 난수) ─────────────────────
        tx_id = str(uuid.uuid4())
        payload_hash = sha256_hex(payload)
        tx = Transaction(
            tx_id=tx_id, sender=sender, receiver=receiver,
            session=session, chain_tip=chain_tip,
            payload_hash=payload_hash, decision_class=decision_class)

        # ── 4. Replay 방지 (advisory ②) — 실시간 블로킹 ──────────────────
        if not self._registry.register(tx_id):
            return CrossSignResult(False, DCReason.REPLAY_DETECTED, tx_id=tx_id,
                                   stage="registry")

        # ── 5. 도미 서명 ──────────────────────────────────────────────────
        domi_sig = self._signer.sign(sender, tx)
        if domi_sig is None:
            return CrossSignResult(False, DCReason.DOMI_SIG_INVALID, tx_id=tx_id,
                                   stage="domi_sign")

        # ── 6. Transport (route_bidir 주입) — 1차는 주입식 ────────────────
        # 실제 통합 시 self._transport(session, prompt, ...) 호출.
        # 1차 검증 스코프에서는 transport 미주입 시 서명 검증까지만 수행.
        if self._transport is not None:
            self._transport(session, payload, chain_tip)

        # ── 7. 제니 응답 서명 (수신측 동일 tx 서명) ───────────────────────
        jeni_sig = self._signer.sign(receiver, tx)
        if jeni_sig is None:
            return CrossSignResult(False, DCReason.JENI_SIG_INVALID, tx_id=tx_id,
                                   stage="jeni_sign")

        # ── 8. Cross-Sign 완료 ────────────────────────────────────────────
        return CrossSignResult(
            True, DCReason.OK, tx_id=tx_id,
            domi_signature=domi_sig, jeni_signature=jeni_sig, stage="complete")

    def verify_cross_sign(self, tx: Transaction,
                          domi_signature: str, jeni_signature: str) -> CrossSignResult:
        """
        수신된 Cross-Sign 트랜잭션 재검증.
        payload_hash 불일치/서명 위조/tx_id 위조를 차단 (제니 의견 ①).
        """
        if not self._signer.verify(tx.sender, tx, domi_signature):
            return CrossSignResult(False, DCReason.DOMI_SIG_INVALID, tx_id=tx.tx_id)
        if not self._signer.verify(tx.receiver, tx, jeni_signature):
            return CrossSignResult(False, DCReason.JENI_SIG_INVALID, tx_id=tx.tx_id)
        return CrossSignResult(True, DCReason.OK, tx_id=tx.tx_id,
                               domi_signature=domi_signature,
                               jeni_signature=jeni_signature, stage="verified")

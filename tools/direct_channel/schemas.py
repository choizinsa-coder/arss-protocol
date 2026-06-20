"""
schemas.py
영역 8 Domi-Jeni Direct Channel (J2-8) — 데이터 구조
EAG-S271-DIRECTCH-001 / 1차 스코프 (Cross-Sign + AICS)

route_bidir() = Transport Layer (미수정)
J2-8         = Trust Layer (본 모듈)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ── 결정 클래스 (영역 11 Decision Class 연동) ────────────────────────────────
HIGH_IMPACT_CLASSES = frozenset({"Constitutional", "Governance"})


@dataclass
class Transaction:
    """Cross-Sign 대상 트랜잭션. tx_id/chain_tip/payload_hash 바인딩."""
    tx_id: str
    sender: str
    receiver: str
    session: int
    chain_tip: str
    payload_hash: str
    decision_class: str = "Operational"
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    def canonical(self) -> str:
        """서명 대상 정규화 문자열. 필드 순서 고정 (재현성)."""
        return "|".join([
            self.tx_id,
            self.sender,
            self.receiver,
            str(self.session),
            self.chain_tip,
            self.payload_hash,
            self.decision_class,
        ])


@dataclass
class CrossSignResult:
    """Cross-Sign 채널 결과."""
    ok: bool
    reason: str
    tx_id: str = ""
    domi_signature: str = ""
    jeni_signature: str = ""
    stage: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class DCReason:
    OK = "OK"
    TOKEN_INVALID = "DC_AICS_TOKEN_INVALID"
    PAYLOAD_HASH_MISMATCH = "DC_PAYLOAD_HASH_MISMATCH"
    DOMI_SIG_INVALID = "DC_DOMI_SIGNATURE_INVALID"
    JENI_SIG_INVALID = "DC_JENI_SIGNATURE_INVALID"
    TX_ID_MISMATCH = "DC_TX_ID_MISMATCH"
    CHAIN_TIP_MISMATCH = "DC_CHAIN_TIP_MISMATCH"
    REPLAY_DETECTED = "DC_REPLAY_DETECTED"
    HERMES_DENIED = "DC_HERMES_DENIED"
    CONSENSUS_RESTRICTED = "DC_CONSENSUS_RESTRICTED"  # advisory ①
    UNKNOWN_SIGNER = "DC_UNKNOWN_SIGNER"

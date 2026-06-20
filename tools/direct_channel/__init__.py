"""
Direct Channel (영역 8 / J2-8 Domi-Jeni Direct Channel)
EAG-S271-DIRECTCH-001 / 1차 스코프

Trust Layer: AICS validate_token → Cross-Sign → transport(route_bidir)
2차 스코프(별도 EAG): MiniMax M3 Consistency Check.
"""

from .schemas import (
    Transaction,
    CrossSignResult,
    DCReason,
    HIGH_IMPACT_CLASSES,
    sha256_hex,
)
from .cross_sign import CrossSigner
from .transaction_registry import TransactionRegistry
from .direct_channel import DirectChannel

__all__ = [
    "Transaction",
    "CrossSignResult",
    "DCReason",
    "HIGH_IMPACT_CLASSES",
    "sha256_hex",
    "CrossSigner",
    "TransactionRegistry",
    "DirectChannel",
]

__version__ = "1.0.0"

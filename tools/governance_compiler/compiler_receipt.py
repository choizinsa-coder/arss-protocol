"""
compiler_receipt.py
Area 12 Compiler Receipt

governance_checker.py 의 R1 Receipt 패턴을 준용한다.
컴파일 결과의 감사 추적용 영수증을 생성한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional


def build_compiler_receipt(
    governance_state: dict,
    projection: dict,
    session: Optional[str] = None,
) -> dict:
    """
    Compiler Receipt 생성.

    Receipt Scope: R1 (Verdict Receipt)
    governance_checker R1 패턴과 정합.
    """
    receipt_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "receipt_id": receipt_id,
        "receipt_scope": "R1",
        "receipt_type": "GOVERNANCE_COMPILER",
        "generated_at": now,
        "session": session or governance_state.get("session"),
        "compiler_verdict": governance_state.get("compiler_verdict"),
        "approval_count": governance_state.get("approval_count", 0),
        "declared_count": governance_state.get("declared_count", 0),
        "chain_complete": governance_state.get("chain_complete", False),
        "projection_id": projection.get("projection_id"),
        "projection_hash": projection.get("projection_hash"),
    }

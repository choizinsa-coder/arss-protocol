# P4-C4 Phase-beta Batch-9 P1: session_transaction_manager RULE-8 assertion 보강
# source: tools/delta_context/session_transaction_manager.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys
from unittest.mock import patch

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.session_transaction_manager import (
    mutate_create_transaction,
    mark_incomplete,
)


class TestSessionTransactionManager:
    """
    Batch-9 P1 — Transaction Safety
    STM-01: mutate_create_transaction / included_deltas=[] → 생성 거부 (BK-5 CASE-C)
    STM-02: mark_incomplete / 존재하지 않는 tx → fail (Missing Transaction Protection)
    """

    def test_stm_01_mutate_create_transaction_rejects_empty_included_deltas(self, tmp_path):
        """STM-01: included_deltas=[] → transaction 생성 거부 (BK-5 CASE-C 방지)

        Rule-T2-1:
          invalid input  = included_deltas = []
          fail-closed    = success=False, TX 파일 생성 금지
          observable     = {"success": False, "reason": "included_deltas가 비어 있음..."}
        """
        tx_dir = tmp_path / "transactions"
        tx_dir.mkdir()

        with patch(
            "tools.delta_context.session_transaction_manager.TX_BASE_PATH",
            str(tx_dir),
        ):
            result = mutate_create_transaction(
                session_number=9999,
                committed_by="caddy",
                included_deltas=[],  # ← 위반: empty list
                generated_at="2026-05-31T00:00:00.000+09:00",
            )

        # FAIL-CLOSED 검증
        assert result["success"] is False, "empty included_deltas 시 success=False"
        assert "reason" in result, "reason 필드 필수"
        assert "included_deltas" in result["reason"], (
            "reason은 included_deltas 관련 사유를 명시해야 함"
        )
        assert "비어 있음" in result["reason"] or "BK-5" in result["reason"], (
            "BK-5 CASE-C 방지 메시지가 포함되어야 함"
        )

        # TX 파일이 실제로 생성되지 않아야 함 (Side-effect 차단)
        tx_files = list(tx_dir.glob("TX-*.json"))
        assert len(tx_files) == 0, (
            "empty included_deltas 거부 시 TX 파일이 생성되어서는 안 됨"
        )

    def test_stm_02_mark_incomplete_rejects_missing_transaction(self, tmp_path):
        """STM-02: 존재하지 않는 TX → fail (Missing Transaction Protection)

        Rule-T2-1:
          invalid input  = 파일이 없는 session_number로 mark_incomplete 호출
          fail-closed    = success=False, 파일 생성 금지
          observable     = {"success": False, "reason": "TX-S{n}.json 미존재"}
        """
        tx_dir = tmp_path / "transactions"
        tx_dir.mkdir()
        # 의도적으로 TX 파일을 생성하지 않음

        nonexistent_session = 99999

        with patch(
            "tools.delta_context.session_transaction_manager.TX_BASE_PATH",
            str(tx_dir),
        ):
            result = mark_incomplete(
                session_number=nonexistent_session,
                reason="test: missing tx protection",
            )

        # FAIL-CLOSED 검증
        assert result["success"] is False, "TX 미존재 시 success=False"
        assert "reason" in result, "reason 필드 필수"
        assert "미존재" in result["reason"], (
            "reason은 TX 미존재를 명시적으로 표시해야 함"
        )
        assert f"TX-S{nonexistent_session}" in result["reason"], (
            "reason에 대상 tx_id가 포함되어야 함"
        )

        # 부수효과 없음 검증: TX 파일이 새로 생성되지 않아야 함
        tx_files = list(tx_dir.glob("TX-*.json"))
        assert len(tx_files) == 0, (
            "미존재 TX에 대한 mark_incomplete는 파일을 새로 만들지 않아야 함"
        )

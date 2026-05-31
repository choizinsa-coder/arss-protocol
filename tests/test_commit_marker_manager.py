# P4-C4 Phase-beta Batch-9 P1: commit_marker_manager RULE-8 assertion 보강
# source: tools/delta_context/commit_marker_manager.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys
import tempfile
import json
from unittest.mock import patch

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.commit_marker_manager import (
    create_commit,
    verify_commit_exists,
)


class TestCommitMarkerManager:
    """
    Batch-9 P1 — Transaction Safety
    CMM-01: verify_commit_exists / TX 존재+COMMIT 미존재 → hard_stop=True
    CMM-02: create_commit / committed_by ≠ caddy → success=False
    """

    def test_cmm_01_verify_commit_exists_missing_commit_with_tx_hard_stops(self, tmp_path):
        """CMM-01: TX 존재 + COMMIT 미존재 → hard_stop=True (Commit Marker 누락 차단)

        Rule-T2-1:
          invalid input  = TX 파일만 존재, COMMIT 파일 부재
          fail-closed    = hard_stop=True 반환
          observable     = {"exists": False, "hard_stop": True, "reason": str}
        """
        session_number = 9999  # 충돌 방지용 고유 session
        tx_dir = tmp_path / "transactions"
        commit_dir = tmp_path / "commits"
        tx_dir.mkdir()
        commit_dir.mkdir()

        # TX 파일만 생성 (COMMIT 파일 부재)
        tx_path = tx_dir / f"TX-S{session_number}.json"
        tx_path.write_text(json.dumps({"tx_id": f"TX-S{session_number}"}))

        # COMMIT_BASE_PATH / TX_BASE_PATH를 임시 경로로 patch
        with patch(
            "tools.delta_context.commit_marker_manager.COMMIT_BASE_PATH",
            str(commit_dir),
        ), patch(
            "tools.delta_context.commit_marker_manager.TX_BASE_PATH",
            str(tx_dir),
        ):
            result = verify_commit_exists(session_number)

        # FAIL-CLOSED 검증
        assert result["exists"] is False, "COMMIT 미존재이므로 exists=False여야 함"
        assert result["hard_stop"] is True, (
            "TX 존재 + COMMIT 미존재 → FIX-2 VIOLATION으로 hard_stop=True여야 함"
        )
        assert "reason" in result, "reason 필드 필수"
        assert "FIX-2 VIOLATION" in result["reason"], (
            "hard_stop 사유는 FIX-2 VIOLATION을 명시해야 함"
        )

    def test_cmm_02_create_commit_rejects_non_caddy_committer(self, tmp_path):
        """CMM-02: committed_by ≠ caddy → success=False (Caller Governance Enforcement)

        Rule-T2-1:
          invalid input  = committed_by = "intruder" (caddy 아님)
          fail-closed    = success=False, COMMIT 파일 생성 금지
          observable     = {"success": False, "reason": "committed_by must be 'caddy'..."}
        """
        commit_dir = tmp_path / "commits"
        commit_dir.mkdir()

        with patch(
            "tools.delta_context.commit_marker_manager.COMMIT_BASE_PATH",
            str(commit_dir),
        ):
            result = create_commit(
                session_number=9999,
                tx_id="TX-S9999",
                transaction_hash="dummy_hash_for_test",
                committed_by="intruder",  # ← 위반: caddy 아님
                generated_at="2026-05-31T00:00:00.000+09:00",
            )

        # FAIL-CLOSED 검증
        assert result["success"] is False, "비-caddy committer 시 success=False"
        assert "reason" in result, "reason 필드 필수"
        assert "committed_by must be 'caddy'" in result["reason"], (
            "reason은 명시적 governance 위반을 표시해야 함"
        )

        # COMMIT 파일이 실제로 생성되지 않아야 함 (Side-effect 차단 검증)
        commit_files = list(commit_dir.glob("COMMIT-*.json"))
        assert len(commit_files) == 0, (
            "비-caddy committer 거부 시 COMMIT 파일이 생성되어서는 안 됨"
        )

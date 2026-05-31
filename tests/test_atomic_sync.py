# P4-C4 Phase-beta Batch-9 P1: atomic_sync RULE-8 assertion 보강
# source: tools/delta_context/atomic_sync.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys
import json
from unittest.mock import patch

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.atomic_sync import verify_index_consistency


class TestAtomicSync:
    """
    Batch-9 P1 — Transaction Safety
    AS-01: verify_index_consistency / partial sync → hard_stop (Partial Synchronization Block)
    AS-02: verify_index_consistency / INDEX_DOMAIN_MISSING → hard_stop (Domain Integrity Protection)
    """

    def test_as_01_verify_index_consistency_blocks_partial_sync(self, tmp_path):
        """AS-01: INDEX는 존재하나 delta가 INDEX와 불일치 → hard_stop (Partial Sync Block)

        Rule-T2-1:
          invalid input  = INDEX에 delta 항목이 없는데 written_deltas에는 존재
          fail-closed    = valid=False, hard_stop=True
          observable     = {"valid": False, "hard_stop": True,
                            "reason": "INDEX delta 불일치: ..."}
        """
        delta_log = tmp_path / "DELTA_LOG"
        delta_log.mkdir()
        divergence_dir = delta_log / "divergence_reports"
        index_path = delta_log / "INDEX.json"

        # INDEX는 존재하나 해당 domain의 sessions가 비어있음 (partial 상태)
        index_data = {
            "schema_version": "1.0",
            "domains": {
                "test_domain": {
                    "latest_delta_id": None,
                    "latest_content_hash": None,
                    "delta_count": 0,
                    "sessions": {"S9999": []},  # ← 비어 있음
                    "latest_summary": {},
                }
            },
        }
        index_path.write_text(json.dumps(index_data))

        # written_deltas는 INDEX에 등록되지 않은 delta를 주장 (partial 불일치)
        written_deltas = [
            {
                "delta_id": "DELTA-S9999-TEST_DOMAIN-0001",
                "domain": "test_domain",
                "session_number": 9999,
                "content_hash": "phantom_hash_not_in_index",
            }
        ]

        with patch(
            "tools.delta_context.atomic_sync.INDEX_PATH",
            str(index_path),
        ), patch(
            "tools.delta_context.atomic_sync.DIVERGENCE_LOG_PATH",
            str(divergence_dir),
        ):
            result = verify_index_consistency(
                session_number=9999,
                written_deltas=written_deltas,
            )

        # FAIL-CLOSED 검증
        assert result["valid"] is False, "INDEX-delta partial 불일치 시 valid=False"
        assert result["hard_stop"] is True, (
            "partial sync 상태에서 hard_stop=True여야 함"
        )
        assert "reason" in result, "reason 필드 필수"
        assert "INDEX delta 불일치" in result["reason"], (
            "reason은 INDEX delta 불일치를 명시해야 함"
        )
        assert "report_path" in result, (
            "divergence report 경로가 반환되어야 함 (audit trail)"
        )

    def test_as_02_verify_index_consistency_blocks_missing_domain(self, tmp_path):
        """AS-02: INDEX에 domain 자체가 없음 → hard_stop (Domain Integrity Protection)

        Rule-T2-1:
          invalid input  = written_deltas의 domain이 INDEX.domains에 부재
          fail-closed    = valid=False, hard_stop=True
          observable     = {"valid": False, "hard_stop": True,
                            "reason": "INDEX domain 미존재: ..."}
        """
        delta_log = tmp_path / "DELTA_LOG"
        delta_log.mkdir()
        divergence_dir = delta_log / "divergence_reports"
        index_path = delta_log / "INDEX.json"

        # INDEX에는 다른 domain만 존재
        index_data = {
            "schema_version": "1.0",
            "domains": {
                "other_domain": {
                    "latest_delta_id": "DELTA-OTHER",
                    "latest_content_hash": "abc",
                    "delta_count": 1,
                    "sessions": {},
                    "latest_summary": {},
                }
            },
        }
        index_path.write_text(json.dumps(index_data))

        # written_deltas의 domain이 INDEX에 등록되지 않음
        written_deltas = [
            {
                "delta_id": "DELTA-S9999-PHANTOM_DOMAIN-0001",
                "domain": "phantom_domain",  # ← INDEX 미등록 domain
                "session_number": 9999,
                "content_hash": "any_hash",
            }
        ]

        with patch(
            "tools.delta_context.atomic_sync.INDEX_PATH",
            str(index_path),
        ), patch(
            "tools.delta_context.atomic_sync.DIVERGENCE_LOG_PATH",
            str(divergence_dir),
        ):
            result = verify_index_consistency(
                session_number=9999,
                written_deltas=written_deltas,
            )

        # FAIL-CLOSED 검증
        assert result["valid"] is False, "domain 미등록 시 valid=False"
        assert result["hard_stop"] is True, (
            "INDEX domain 미존재 시 hard_stop=True여야 함"
        )
        assert "reason" in result, "reason 필드 필수"
        assert "INDEX domain 미존재" in result["reason"], (
            "reason은 INDEX domain 미존재를 명시해야 함"
        )
        assert "phantom_domain" in result["reason"], (
            "reason에 대상 domain이 포함되어야 함"
        )
        assert "report_path" in result, (
            "divergence report 경로가 반환되어야 함 (audit trail)"
        )

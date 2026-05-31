# P4-C4 Phase-beta Batch-9 P2: index_validator RULE-8 assertion 보강
# source: tools/delta_context/index_validator.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.index_validator import (
    _validate_index_fields,
    _validate_delta_sequence,
)


class TestIndexValidator:
    """
    Batch-9 P2 — Delta/Index Integrity
    IV-01: _validate_index_fields / required field 누락 → FAIL (Structure Integrity)
    IV-02: _validate_delta_sequence / delta_count mismatch → FAIL (Sequence Integrity)
    """

    def test_iv_01_validate_index_fields_rejects_missing_required_field(self):
        """IV-01: required field 누락 → FAIL (Structure Integrity)

        Rule-T2-1:
          invalid input  = domain_entry에 'delta_count' 필드 누락
          fail-closed    = result="FAIL", hard_stop=True
          observable     = (_fail("[G4-구조] domain='...' INDEX 필수 필드 누락: '...'"),
                            "", "", 0)

        근거: _validate_index_fields는 latest_delta_id / latest_content_hash /
              delta_count 3개 필드를 필수로 요구. 하나라도 누락 시 즉시 FAIL.
        """
        # 'delta_count' 필드 의도적 누락
        invalid_domain_entry = {
            "latest_delta_id": "DELTA-S100-TEST-0001",
            "latest_content_hash": "abc123def456",
            # "delta_count": ...  ← 누락
        }

        err, delta_id, content_hash, delta_count = _validate_index_fields(
            domain="test_domain",
            domain_entry=invalid_domain_entry,
        )

        # FAIL-CLOSED 검증
        assert err is not None, "필수 필드 누락 시 err가 반환되어야 함"
        assert err["result"] == "FAIL", "result는 FAIL이어야 함"
        assert err["hard_stop"] is True, "hard_stop=True (FAIL-CLOSED 정책)"
        assert "reason" in err, "reason 필드 필수"
        assert "INDEX 필수 필드 누락" in err["reason"], (
            "reason은 필수 필드 누락 사유를 명시해야 함"
        )
        assert "delta_count" in err["reason"], (
            "reason에 누락된 필드명(delta_count)이 포함되어야 함"
        )
        # 변수 추출은 빈 값으로 반환되어야 함 (side-effect 차단)
        assert delta_id == ""
        assert content_hash == ""
        assert delta_count == 0

    def test_iv_02_validate_delta_sequence_rejects_count_mismatch(self):
        """IV-02: delta_count mismatch → FAIL (Sequence Integrity)

        Rule-T2-1:
          invalid input  = INDEX delta_count=5, 실제 deltas=3
          fail-closed    = result="FAIL", hard_stop=True
          observable     = _fail("[G4] domain='...' delta_count 불일치: INDEX=5, 실제=3")

        근거: _validate_delta_sequence는 INDEX 기록 count와 실제 delta 파일 수
              일치를 검증. 불일치 시 [G4] FAIL.
        """
        # 실제 deltas는 3건, INDEX는 5건 주장 (mismatch)
        deltas = [
            {"sequence_number": 1, "delta_id": "DELTA-S100-TEST-0001", "content_hash": "h1"},
            {"sequence_number": 2, "delta_id": "DELTA-S100-TEST-0002", "content_hash": "h2"},
            {"sequence_number": 3, "delta_id": "DELTA-S100-TEST-0003", "content_hash": "h3"},
        ]
        index_delta_count = 5  # ← 위반: 실제 3건과 불일치

        err = _validate_delta_sequence(
            domain="test_domain",
            deltas=deltas,
            index_delta_count=index_delta_count,
        )

        # FAIL-CLOSED 검증
        assert err is not None, "count mismatch 시 err가 반환되어야 함"
        assert err["result"] == "FAIL", "result는 FAIL이어야 함"
        assert err["hard_stop"] is True, "hard_stop=True (FAIL-CLOSED 정책)"
        assert "reason" in err, "reason 필드 필수"
        assert "delta_count 불일치" in err["reason"], (
            "reason은 delta_count 불일치를 명시해야 함"
        )
        assert "INDEX=5" in err["reason"] and "실제=3" in err["reason"], (
            "reason에 기대값과 실제값이 모두 포함되어야 함"
        )

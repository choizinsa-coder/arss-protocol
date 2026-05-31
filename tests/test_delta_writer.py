# P4-C4 Phase-beta Batch-9 P2: delta_writer RULE-8 assertion 보강
# source: tools/delta_context/delta_writer.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.delta_writer import (
    _gate_2_dq003,
    _gate_6_approved_by,
)


class TestDeltaWriter:
    """
    Batch-9 P2 — Delta/Index Integrity
    DW-01: _gate_2_dq003 / invalid event_type × target_key → reject (Schema Mapping Protection)
    DW-02: _gate_6_approved_by / approved_by ≠ 비오(Joshua) → reject (Governance Enforcement)
    """

    def test_dw_01_gate_2_dq003_rejects_invalid_event_type(self):
        """DW-01: 미등록 event_type → reject (Schema Mapping Protection)

        Rule-T2-1:
          invalid input  = event_type = "UNDEFINED_EVENT"
          fail-closed    = pass=False, gate="G2"
          observable     = {"pass": False, "gate": "G2", "reason": "UNKNOWN_EVENT_TYPE: ..."}

        근거: event_type_target_validator.validate()는 EVENT_TARGET_MAP에
              등록되지 않은 event_type을 HARD STOP으로 거부함.
        """
        invalid_delta = {
            "event_type": "UNDEFINED_EVENT",  # ← 위반: EVENT_TARGET_MAP 미등록
            "target_key": "status",
            "new_value": "ACTIVE",
        }

        result = _gate_2_dq003(invalid_delta)

        # FAIL-CLOSED 검증
        assert result["pass"] is False, "미등록 event_type 시 pass=False"
        assert result["gate"] == "G2", "차단 gate는 G2(dq003)여야 함"
        assert "reason" in result, "reason 필드 필수"
        assert "UNKNOWN_EVENT_TYPE" in result["reason"], (
            "reason은 UNKNOWN_EVENT_TYPE을 명시해야 함"
        )

    def test_dw_02_gate_6_approved_by_rejects_non_beo_approver(self):
        """DW-02: approved_by ≠ '비오(Joshua)' → reject (Governance Enforcement)

        Rule-T2-1:
          invalid input  = approved_by = "intruder"
          fail-closed    = pass=False, gate="G6"
          observable     = {"pass": False, "gate": "G6",
                            "reason": "approved_by must be '비오(Joshua)'..."}

        근거: G6 gate는 approved_by 단일값 '비오(Joshua)' 고정.
              다른 값은 모두 governance 위반으로 차단.
        """
        invalid_delta = {
            "approved_by": "intruder",  # ← 위반: '비오(Joshua)' 아님
            "event_type": "task_status_update",
            "target_key": "status",
            "new_value": "ACTIVE",
        }

        result = _gate_6_approved_by(invalid_delta)

        # FAIL-CLOSED 검증
        assert result["pass"] is False, "비-비오(Joshua) approver 시 pass=False"
        assert result["gate"] == "G6", "차단 gate는 G6(approved_by)여야 함"
        assert "reason" in result, "reason 필드 필수"
        assert "approved_by must be '비오(Joshua)'" in result["reason"], (
            "reason은 명시적 governance 위반(approved_by 기준)을 표시해야 함"
        )

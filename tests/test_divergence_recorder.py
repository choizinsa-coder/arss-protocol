# P4-C4 Phase-beta Batch-9 P3: divergence_recorder RULE-8 assertion 보강
# source: tools/delta_context/divergence_recorder.py
# session: S179
# governance: 도미 FINAL DESIGN v2 / 제니 TRUST_READY PASS / 비오 EAG-1
# Rule-T2-1: invalid input → fail-closed/result denial → observable verdict

import os
import sys
from unittest.mock import patch

import pytest

# 상위 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.delta_context.divergence_recorder import (
    record_divergence,
    _determine_severity,
    PHASE3_BLOCKING_SEVERITIES,
    SEVERITY_HIGH,
)


class TestDivergenceRecorder:
    """
    Batch-9 P3 — Divergence Audit
    DR-01: record_divergence / REQUIRED_FIELDS 누락 → reject (Divergence Entry Integrity)
    DR-02: _determine_severity / BLOCKED_VALIDATION → HIGH + phase3_blocked=True
           (Unresolved Divergence Blocking)
    """

    def test_dr_01_record_divergence_rejects_pass_contract(self, tmp_path):
        """DR-01: contract='PASS'인 경우 → record 거부 (Divergence Entry Integrity)

        Rule-T2-1:
          invalid input  = contract={"contract": "PASS", ...} (divergence 아님)
          fail-closed    = success=False, divergence 로그에 기록 금지
          observable     = {"success": False, "reason": "contract PASS — divergence 기록 불필요"}

        근거: record_divergence는 contract='PASS' 시 즉시 거부.
              divergence 로그 무결성 보장 — 정상 contract는 entry로 기재 금지.
        """
        log_path = tmp_path / "divergence_log.json"

        # contract='PASS' (divergence 기록 대상 아님)
        invalid_pass_contract = {
            "contract": "PASS",
            "candidate_hash": "abc",
            "ssot_hash": "abc",
            "reasons": [],
        }

        with patch(
            "tools.delta_context.divergence_recorder.DIVERGENCE_LOG_PATH",
            str(log_path),
        ):
            result = record_divergence(
                session_number=9999,
                contract=invalid_pass_contract,
                sequence=1,
            )

        # FAIL-CLOSED 검증
        assert result["success"] is False, "PASS contract 시 success=False"
        assert "reason" in result, "reason 필드 필수"
        assert "PASS" in result["reason"], (
            "reason은 contract PASS 거부 사유를 명시해야 함"
        )

        # divergence 로그 파일이 생성되지 않아야 함 (side-effect 차단)
        assert not log_path.exists(), (
            "PASS contract 거부 시 divergence 로그 파일이 생성되어서는 안 됨"
        )

    def test_dr_02_determine_severity_blocks_unresolved_validation(self):
        """DR-02: BLOCKED_VALIDATION contract → severity=HIGH + phase3_blocked=True
                 (Unresolved Divergence Blocking)

        Rule-T2-1:
          invalid input  = contract={"contract": "BLOCKED_VALIDATION", ...}
          fail-closed    = severity=HIGH 자동 부여, phase3_blocked=True
          observable     = severity == "HIGH" AND phase3_blocked == True

        근거: BLOCKED_VALIDATION은 검증 자체가 차단된 상태로, 미해소
              divergence가 정상 통과되어서는 안 됨. _determine_severity는
              이를 HIGH로 자동 부여하여 phase3_blocked 처리.
        """
        # BLOCKED_VALIDATION contract (검증 차단 상태)
        blocked_contract = {
            "contract": "BLOCKED_VALIDATION",
            "candidate_hash": "blocked_hash",
            "ssot_hash": "ssot_hash",
            "reasons": ["validation blocked by upstream gate"],
        }

        severity = _determine_severity(blocked_contract)

        # SEVERITY 판정 검증
        assert severity == SEVERITY_HIGH, (
            "BLOCKED_VALIDATION 시 severity는 HIGH로 자동 부여되어야 함"
        )
        assert severity == "HIGH", "severity 문자열 정확성 검증"

        # phase3_blocked 계산 검증 (production 로직과 동일)
        phase3_blocked = severity in PHASE3_BLOCKING_SEVERITIES
        assert phase3_blocked is True, (
            "HIGH severity는 PHASE3_BLOCKING_SEVERITIES 멤버이므로 "
            "phase3_blocked=True여야 함 (Unresolved Divergence Blocking)"
        )

        # PHASE3_BLOCKING_SEVERITIES 집합 정합성 검증
        assert SEVERITY_HIGH in PHASE3_BLOCKING_SEVERITIES, (
            "HIGH severity가 phase3 차단 집합에 포함되어 있어야 함 "
            "(거버넌스 정합성)"
        )

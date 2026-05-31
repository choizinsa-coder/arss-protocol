# P4-C4 Phase-beta Batch-9 P2: index_updater RULE-8 assertion 보강
# source: tools/delta_context/index_updater.py
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

from tools.delta_context.index_updater import (
    update_index,
    _quarantine_delta,
)


class TestIndexUpdater:
    """
    Batch-9 P2 — Delta/Index Integrity (재정의됨 — Quarantine 책임 영역)
    IU-01: update_index / 예외 발생 → delta QUARANTINED (Quarantine Activation)
    IU-02: _quarantine_delta / invalid delta → quarantine handler 호출 (Isolation Guarantee)

    설계 근거: contract confirmation 결과 update_index의 실제 책임은
              hash mismatch 차단이나 domain whitelist가 아니라 FIX-1 quarantine.
              따라서 도미 v2에서 전면 재정의.
    """

    def test_iu_01_update_index_quarantines_delta_on_exception(self, tmp_path):
        """IU-01: 예외 발생 시 delta → QUARANTINED (Quarantine Activation)

        Rule-T2-1:
          invalid input  = _save_index가 예외를 발생시킴 (실패 조건 강제)
          fail-closed    = success=False, hard_stop=True, delta가 quarantine 경로로 이동
          observable     = {"success": False, "hard_stop": True,
                            "reason": "index_updater 실패: ...",
                            "quarantine": {"quarantined": True, "dest": ...}}

        근거: FIX-1 정책. index_updater 실패 시 half-valid state 금지를 위해
              delta를 즉시 quarantine으로 격리.
        """
        delta_log = tmp_path / "DELTA_LOG"
        delta_log.mkdir()
        quarantine_dir = delta_log / "quarantine"

        # 정상 delta 파일 준비 (quarantine 이동 가능한 상태)
        delta_id = "DELTA-S9999-TEST_DOMAIN-0001"
        delta = {
            "delta_id": delta_id,
            "domain": "test_domain",
            "session_number": 9999,
            "sequence_number": 1,
            "content_hash": "abc123",
            "event_type": "task_status_update",
            "target_key": "status",
            "generated_at": "2026-05-31T00:00:00.000+09:00",
        }
        delta_path = tmp_path / f"{delta_id}.json"
        delta_path.write_text(json.dumps(delta))

        # _save_index를 강제 예외 유발하도록 patch
        # (update_index 내부에서 예외 발생 → quarantine 분기 진입)
        with patch(
            "tools.delta_context.index_updater.QUARANTINE_BASE",
            str(quarantine_dir),
        ), patch(
            "tools.delta_context.index_updater._save_index",
            side_effect=RuntimeError("forced failure for IU-01 quarantine test"),
        ), patch(
            "tools.delta_context.index_updater.INDEX_PATH",
            str(tmp_path / "nonexistent_INDEX.json"),
        ):
            result = update_index(delta, str(delta_path))

        # FAIL-CLOSED + QUARANTINE 검증
        assert result["success"] is False, "예외 발생 시 success=False"
        assert result["hard_stop"] is True, "FIX-1: hard_stop=True"
        assert "reason" in result, "reason 필드 필수"
        assert "index_updater 실패" in result["reason"], (
            "reason은 index_updater 실패를 명시해야 함"
        )
        assert "quarantine" in result, "quarantine 결과 필수 (FIX-1 정책)"
        assert result["quarantine"]["quarantined"] is True, (
            "delta가 실제로 quarantine으로 이동되어야 함"
        )
        # 원본 경로 삭제 + quarantine 경로 생성 검증
        assert not delta_path.exists(), (
            "원본 delta 파일은 quarantine 이동 후 삭제되어야 함"
        )
        quarantine_files = list(quarantine_dir.glob("*.json"))
        assert len(quarantine_files) == 1, (
            "quarantine 디렉토리에 정확히 1개 delta가 존재해야 함"
        )

    def test_iu_02_quarantine_delta_activates_handler_for_invalid_delta(self, tmp_path):
        """IU-02: invalid delta → quarantine handler 호출 (Isolation Guarantee)

        Rule-T2-1:
          invalid input  = invalid delta (구조적으로 처리 대상)
          fail-closed    = quarantine handler가 호출되어 격리
          observable     = {"quarantined": True, "dest": str}

        근거: _quarantine_delta는 delta를 QUARANTINED 상태로 마킹하고
              quarantine 디렉토리로 이동. status 필드와 quarantine_reason
              필드가 추가되어야 함.
        """
        quarantine_dir = tmp_path / "quarantine"

        # invalid delta 준비 (격리 대상)
        delta_id = "DELTA-S9999-INVALID-0099"
        invalid_delta = {
            "delta_id": delta_id,
            "domain": "invalid_test_domain",
            "session_number": 9999,
            "content_hash": "malformed_hash",
        }
        delta_path = tmp_path / f"{delta_id}.json"
        delta_path.write_text(json.dumps(invalid_delta))

        reason = "test: isolation guarantee verification"

        with patch(
            "tools.delta_context.index_updater.QUARANTINE_BASE",
            str(quarantine_dir),
        ):
            result = _quarantine_delta(
                delta_path=str(delta_path),
                delta_id=delta_id,
                reason=reason,
            )

        # QUARANTINE HANDLER 호출 검증
        assert result["quarantined"] is True, "quarantine handler가 활성화되어야 함"
        assert "dest" in result, "dest 경로가 반환되어야 함"
        assert os.path.exists(result["dest"]), (
            "quarantine 목적지에 실제 파일이 존재해야 함"
        )
        # 원본 삭제 검증 (격리 = 원본 active 경로에서 제거)
        assert not delta_path.exists(), (
            "격리 후 원본 delta 파일은 active 경로에서 제거되어야 함"
        )

        # 격리된 delta의 메타데이터 검증 (QUARANTINED 마킹)
        with open(result["dest"], "r", encoding="utf-8") as f:
            quarantined_delta = json.load(f)
        assert quarantined_delta["status"] == "QUARANTINED", (
            "격리된 delta는 status='QUARANTINED'로 마킹되어야 함"
        )
        assert quarantined_delta["quarantine_reason"] == reason, (
            "quarantine_reason 필드에 사유가 기록되어야 함"
        )

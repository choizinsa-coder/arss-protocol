# RULE-8_TEST_READY
# source: tools/delta_context/tx_recovery.py
# tag: RULE-8_TEST_READY
# updated: S180 Batch-10
# note: TX-S69 전용 one-shot recovery script failure-path assertions (TR-01~TR-04)
# governance: 도미 [DESIGN] S180 + 제니 TRUST_READY PASS + 비오(Joshua) EAG-1

import json
import pytest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tx(path: Path, status: str = "INCOMPLETE") -> None:
    """최소 TX JSON 파일 생성"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"tx_id": "TX-S69", "status": status}))


def _make_index(path: Path) -> None:
    """최소 INDEX JSON 파일 생성"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"transactions": []}))


# ---------------------------------------------------------------------------
# TR-01: step1_void_tx() — TX-S69.json 미존재 → FileNotFoundError
# ---------------------------------------------------------------------------

class TestTR01Step1TxMissing:
    """TR-01: TX 파일 없으면 VOID 전환을 시작하지 않는다"""

    def test_tx_file_not_found_raises(self, tmp_path):
        missing_tx = tmp_path / "DELTA_LOG" / "transactions" / "TX-S69.json"
        # TX 파일을 생성하지 않음

        import tools.delta_context.tx_recovery as mod
        with patch.object(mod, "TX_PATH", missing_tx):
            with pytest.raises(FileNotFoundError):
                mod.step1_void_tx()

        # 파일이 생성되지 않았음을 확인 (상태 보존)
        assert not missing_tx.exists()


# ---------------------------------------------------------------------------
# TR-02: step1_void_tx() — TX status가 INCOMPLETE 아님 → ValueError
# ---------------------------------------------------------------------------

class TestTR02Step1WrongStatus:
    """TR-02: 잘못된 상태의 TX는 VOID 처리하지 않는다"""

    def test_wrong_tx_status_raises(self, tmp_path):
        tx_path = tmp_path / "DELTA_LOG" / "transactions" / "TX-S69.json"
        _make_tx(tx_path, status="VOID")  # 이미 VOID 상태

        import tools.delta_context.tx_recovery as mod
        with patch.object(mod, "TX_PATH", tx_path):
            with pytest.raises(ValueError):
                mod.step1_void_tx()

        # 원본 status가 변경되지 않았음을 확인 (상태 보존)
        data = json.loads(tx_path.read_text())
        assert data["status"] == "VOID"
        assert "voided_at" not in data


# ---------------------------------------------------------------------------
# TR-03: step3_quarantine_agent_focus() — quarantine 목적지 이미 존재 → FileExistsError
# ---------------------------------------------------------------------------

class TestTR03QuarantineDstExists:
    """TR-03: 기존 quarantine 산출물을 덮어쓰지 않는다"""

    def test_quarantine_dst_exists_raises(self, tmp_path):
        src = tmp_path / "DELTA_LOG" / "agent_focus" / "S69"
        src.mkdir(parents=True)
        (src / "dummy.json").write_text("{}")

        dst = tmp_path / "SNAPSHOT_LOG" / "quarantine" / "agent_focus_S69"
        dst.mkdir(parents=True)  # 목적지 이미 존재
        (dst / "existing.json").write_text("{}")

        import tools.delta_context.tx_recovery as mod
        with patch.object(mod, "AGENT_FOCUS_SRC", src), \
             patch.object(mod, "QUARANTINE_DST", dst):
            with pytest.raises(FileExistsError):
                mod.step3_quarantine_agent_focus()

        # 소스가 그대로 남아 있음을 확인 (상태 보존)
        assert src.exists()
        # 목적지 기존 파일 보존 확인
        assert (dst / "existing.json").exists()


# ---------------------------------------------------------------------------
# TR-04: step4_validate() — TX status VOID 아님 → RuntimeError
# ---------------------------------------------------------------------------

class TestTR04ValidateFailClosed:
    """TR-04: 최종 검증 실패 시 recovery 완료로 간주하지 않는다"""

    def test_validate_fails_when_tx_not_void(self, tmp_path):
        # TX status가 INCOMPLETE(VOID 아님)인 상태
        tx_path = tmp_path / "DELTA_LOG" / "transactions" / "TX-S69.json"
        _make_tx(tx_path, status="INCOMPLETE")

        index_path = tmp_path / "DELTA_LOG" / "INDEX.json"
        _make_index(index_path)

        # agent_focus/S69 소스는 존재 (quarantine 미완료 상태)
        src = tmp_path / "DELTA_LOG" / "agent_focus" / "S69"
        src.mkdir(parents=True)

        # quarantine 목적지 미존재
        dst = tmp_path / "SNAPSHOT_LOG" / "quarantine" / "agent_focus_S69"

        import tools.delta_context.tx_recovery as mod
        with patch.object(mod, "TX_PATH", tx_path), \
             patch.object(mod, "INDEX_PATH", index_path), \
             patch.object(mod, "AGENT_FOCUS_SRC", src), \
             patch.object(mod, "QUARANTINE_DST", dst):
            with pytest.raises(RuntimeError):
                mod.step4_validate()

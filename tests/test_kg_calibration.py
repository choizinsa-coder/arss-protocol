"""test_kg_calibration.py -- KG Phase 2-B Confidence Calibration tests (EAG-S333-KG-PHASE2-001)"""
import sys
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.knowledge_graph import outcome_log, calibration


class TestOutcomeLog:
    def test_record_valid_outcome(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        monkeypatch.setattr(outcome_log, "KG_DIR", tmp_path)
        result = outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        assert result["recorded"] is True
        assert result["entry"]["schema"] == "decision_outcome_v1"
        assert result["entry"]["outcome"] == "success"

    def test_record_invalid_outcome(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        monkeypatch.setattr(outcome_log, "KG_DIR", tmp_path)
        result = outcome_log.record_outcome("DL-1", "maybe")
        assert result["recorded"] is False
        assert "error" in result

    def test_load_all_outcomes(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        monkeypatch.setattr(outcome_log, "KG_DIR", tmp_path)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        outcome_log.record_outcome("DL-2", "failure", predicted_confidence=0.5)
        assert len(outcome_log.load_all_outcomes()) == 2

    def test_load_empty(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        assert outcome_log.load_all_outcomes() == []

    def test_predicted_confidence_persisted(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        monkeypatch.setattr(outcome_log, "KG_DIR", tmp_path)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.85)
        entries = outcome_log.load_all_outcomes()
        assert entries[0]["predicted_confidence"] == 0.85


class TestCalibration:
    def _setup(self, tmp_path, monkeypatch):
        log = tmp_path / "decision_outcome.jsonl"
        monkeypatch.setattr(outcome_log, "OUTCOME_LOG_PATH", log)
        monkeypatch.setattr(outcome_log, "KG_DIR", tmp_path)

    def test_empty_returns_none(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        assert calibration.compute_calibration_error() is None

    def test_below_min_samples_none(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        outcome_log.record_outcome("DL-2", "success", predicted_confidence=0.8)
        assert calibration.compute_calibration_error(min_samples=3) is None

    def test_calibration_error_value(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        outcome_log.record_outcome("DL-2", "success", predicted_confidence=0.8)
        outcome_log.record_outcome("DL-3", "failure", predicted_confidence=0.7)
        err = calibration.compute_calibration_error(min_samples=3)
        assert err is not None
        assert abs(err - 0.1333) < 0.001

    def test_none_predicted_excluded(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        outcome_log.record_outcome("DL-2", "success", predicted_confidence=0.8)
        outcome_log.record_outcome("DL-3", "failure", predicted_confidence=0.7)
        outcome_log.record_outcome("DL-4", "success", predicted_confidence=None)
        snap = calibration.get_calibration_snapshot()
        assert snap["total_samples"] == 3

    def test_snapshot_sufficient_flag(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        for i in range(3):
            outcome_log.record_outcome(f"DL-{i}", "success", predicted_confidence=0.9)
        snap = calibration.get_calibration_snapshot()
        assert snap["sufficient"] is True
        assert snap["actual_success_rate"] == 1.0

    def test_snapshot_insufficient(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        snap = calibration.get_calibration_snapshot()
        assert snap["sufficient"] is False
        assert snap["calibration_error"] is None

    def test_out_of_range_confidence_excluded(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        outcome_log.record_outcome("DL-1", "success", predicted_confidence=0.9)
        outcome_log.record_outcome("DL-2", "success", predicted_confidence=0.8)
        outcome_log.record_outcome("DL-3", "failure", predicted_confidence=1.5)
        snap = calibration.get_calibration_snapshot()
        assert snap["total_samples"] == 2

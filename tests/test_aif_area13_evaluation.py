import json
import sys
import pytest
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
sys.path.insert(0, str(ROOT / "tools/governance"))

import area_13_evaluation as ev
from area_13_evaluation import MetricValidationError


class TestArea13Evaluation:
    """AIF Area 13: Evaluation & Benchmark"""

    def test_module_version(self):
        assert ev.VERSION == "1.0.0"
        assert ev.EAG_ID == "EAG-S321-AIF-AREA11-13-001"

    def test_metrics_7_defined(self):
        assert len(ev.METRICS_7) == 7
        for mid in ["M01", "M02", "M03", "M04", "M05", "M06", "M07"]:
            assert mid in ev.METRICS_7

    def test_metrics_have_required_fields(self):
        for mid, meta in ev.METRICS_7.items():
            assert "id" in meta
            assert "name" in meta
            assert "unit" in meta
            assert "source" in meta

    def test_validate_metric_id_valid(self):
        assert ev.validate_metric_id("M01") is True
        assert ev.validate_metric_id("m07") is True

    def test_validate_metric_id_case_insensitive(self):
        assert ev.validate_metric_id("m01") is True

    def test_validate_metric_id_invalid(self):
        with pytest.raises(MetricValidationError):
            ev.validate_metric_id("M08")

    def test_validate_metric_id_empty(self):
        with pytest.raises(MetricValidationError):
            ev.validate_metric_id("")

    def test_record_metric_success(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            entry = ev.record_metric("M01", 1784, context={"session": "S321"})
            assert entry["metric_id"] == "M01"
            assert entry["value"] == 1784.0
            assert entry["schema"] == "evaluation_metric_v1"
            assert entry["metric_name"] == "pytest_passed"
            assert entry["context"]["session"] == "S321"
        finally:
            ev.LOG_PATH = original

    def test_record_metric_lowercase_id(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            entry = ev.record_metric("m02", 0)
            assert entry["metric_id"] == "M02"
        finally:
            ev.LOG_PATH = original

    def test_record_metric_invalid_id_raises(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            with pytest.raises(MetricValidationError):
                ev.record_metric("M99", 100)
        finally:
            ev.LOG_PATH = original

    def test_record_metric_non_numeric_raises(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            with pytest.raises(MetricValidationError):
                ev.record_metric("M01", "not_a_number")
        finally:
            ev.LOG_PATH = original

    def test_get_metric_history(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            for i in range(5):
                ev.record_metric("M01", 1769 + i)
            history = ev.get_metric_history("M01", 3)
            assert len(history) == 3
            assert history[0]["value"] == 1773.0
        finally:
            ev.LOG_PATH = original

    def test_get_metric_history_empty(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            result = ev.get_metric_history("M01")
            assert result == []
        finally:
            ev.LOG_PATH = original

    def test_get_all_metrics_latest(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            ev.record_metric("M01", 1784)
            ev.record_metric("M07", 0.005)
            latest = ev.get_all_metrics_latest()
            assert latest["M01"]["value"] == 1784.0
            assert latest["M07"]["value"] == 0.005
            assert latest["M03"] is None
        finally:
            ev.LOG_PATH = original

    def test_get_current_snapshot_structure(self):
        snapshot = ev.get_current_snapshot()
        for mid in ["M01", "M02", "M03", "M04", "M05", "M06", "M07"]:
            assert mid in snapshot
        assert "snapshot_at" in snapshot

    def test_get_current_snapshot_m01_populated(self):
        snapshot = ev.get_current_snapshot()
        assert snapshot["M01"] is not None
        assert isinstance(snapshot["M01"], int)

    def test_get_current_snapshot_m07_populated(self):
        snapshot = ev.get_current_snapshot()
        assert snapshot["M07"] is not None
        assert isinstance(snapshot["M07"], float)

    def test_get_current_snapshot_manual_metrics_none(self):
        snapshot = ev.get_current_snapshot()
        for mid in ["M03", "M04", "M05", "M06"]:
            assert snapshot[mid] is None

    def test_get_evaluation_summary_empty(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            summary = ev.get_evaluation_summary()
            assert summary["schema"] == "evaluation_summary_v1"
            assert summary["total_records"] == 0
            assert len(summary["metrics_defined"]) == 7
        finally:
            ev.LOG_PATH = original

    def test_get_evaluation_summary_with_records(self, tmp_path):
        original = ev.LOG_PATH
        ev.LOG_PATH = tmp_path / "evaluation_log.jsonl"
        try:
            ev.record_metric("M01", 1784)
            ev.record_metric("M02", 0)
            summary = ev.get_evaluation_summary()
            assert summary["total_records"] == 2
            assert summary["metrics_latest"]["M01"]["value"] == 1784.0
        finally:
            ev.LOG_PATH = original

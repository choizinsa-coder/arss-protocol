#!/usr/bin/env python3
"""test_aiba_monitor.py v1.0.0 -- EAG-S323-AIBA-MONITOR-001 (16 cases)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.monitor.aiba_monitor import GovernanceMonitor
import tools.monitor.aiba_monitor as mon_mod


class TestGHS(unittest.TestCase):
    def _mon(self):
        m = GovernanceMonitor.__new__(GovernanceMonitor)
        m.run_id = "MON-T"
        m.timestamp_iso = "2026-07-03T00:00:00+00:00"
        return m

    def test_ghs_normal(self):
        m = self._mon()
        with (patch.object(m, "_get_calibration_error_rate", return_value=0.0),
              patch.object(m, "_get_failure_repeat_rate",    return_value=0.0),
              patch.object(m, "_get_opportunity_decay_rate", return_value=0.0),
              patch.object(m, "_get_process_compliance_rate",    return_value=1.0),
              patch.object(m, "_get_constitution_adherence_rate", return_value=1.0)):
            ghs = m.calculate_ghs()
        self.assertGreaterEqual(ghs["score"], 0.6)
        self.assertEqual(ghs["status"], "NORMAL")

    def test_ghs_warning(self):
        m = self._mon()
        with (patch.object(m, "_get_calibration_error_rate", return_value=0.5),
              patch.object(m, "_get_failure_repeat_rate",    return_value=0.5),
              patch.object(m, "_get_opportunity_decay_rate", return_value=0.5),
              patch.object(m, "_get_process_compliance_rate",    return_value=0.5),
              patch.object(m, "_get_constitution_adherence_rate", return_value=0.5)):
            ghs = m.calculate_ghs()
        self.assertGreaterEqual(ghs["score"], 0.3)
        self.assertLess(ghs["score"], 0.6)
        self.assertEqual(ghs["status"], "WARNING")

    def test_ghs_fail_closed(self):
        m = self._mon()
        with (patch.object(m, "_get_calibration_error_rate", return_value=1.0),
              patch.object(m, "_get_failure_repeat_rate",    return_value=1.0),
              patch.object(m, "_get_opportunity_decay_rate", return_value=1.0),
              patch.object(m, "_get_process_compliance_rate",    return_value=0.0),
              patch.object(m, "_get_constitution_adherence_rate", return_value=0.0)):
            ghs = m.calculate_ghs()
        self.assertLess(ghs["score"], 0.3)
        self.assertEqual(ghs["status"], "FAIL_CLOSED")

    def test_ghs_weights_sum(self):
        m = self._mon()
        self.assertAlmostEqual(sum(m.WEIGHTS.values()), 1.0, places=10)


class TestTriggers(unittest.TestCase):
    def _mon(self):
        m = GovernanceMonitor.__new__(GovernanceMonitor)
        m.run_id = m.timestamp_iso = ""
        m.FAILURE_REPEAT_THRESHOLD    = 3
        m.MISSION_DRIFT_CONSECUTIVE   = 3
        m.CALIBRATION_DRIFT_THRESHOLD = 0.20
        m.GHS_NORMAL  = 0.6
        m.GHS_WARNING = 0.3
        return m

    def test_failure_trigger_fires(self):
        m = self._mon()
        pats = {"has_alert": True, "consecutive_repeat": [{"component": "caddy", "error_code": "E"}]}
        with patch("tools.governance.area_15_failure_memory.get_failure_patterns", return_value=pats):
            r = m._check_failure_trigger()
        self.assertTrue(r["fired"])

    def test_failure_trigger_no_fire(self):
        m = self._mon()
        pats = {"has_alert": False, "consecutive_repeat": []}
        with patch("tools.governance.area_15_failure_memory.get_failure_patterns", return_value=pats):
            r = m._check_failure_trigger()
        self.assertFalse(r["fired"])

    def test_calibration_drift_fires(self):
        m = self._mon()
        r = m._check_calibration_drift_trigger(0.25)
        self.assertTrue(r["fired"])
        self.assertTrue(r["fail_closed_flag"])

    def test_calibration_drift_no_fire(self):
        m = self._mon()
        r = m._check_calibration_drift_trigger(0.10)
        self.assertFalse(r["fired"])

    def test_mission_drift_fires(self):
        m = self._mon()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"recent_scores": [0.5, 0.4]}, f)
            hp = Path(f.name)
        orig = mon_mod.GHS_HISTORY_PATH
        mon_mod.GHS_HISTORY_PATH = hp
        try:
            r = m._check_mission_drift_trigger(0.45)
        finally:
            mon_mod.GHS_HISTORY_PATH = orig
            hp.unlink(missing_ok=True)
        self.assertTrue(r["fired"])

    def test_mission_drift_not_enough(self):
        m = self._mon()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({"recent_scores": [0.45]}, f)
            hp = Path(f.name)
        orig = mon_mod.GHS_HISTORY_PATH
        mon_mod.GHS_HISTORY_PATH = hp
        try:
            r = m._check_mission_drift_trigger(0.8)
        finally:
            mon_mod.GHS_HISTORY_PATH = orig
            hp.unlink(missing_ok=True)
        self.assertFalse(r["fired"])

    def test_placeholders_never_fire(self):
        m = self._mon()
        self.assertFalse(m._check_opportunity_decay_trigger()["fired"])
        self.assertFalse(m._check_external_change_trigger()["fired"])


class TestOutput(unittest.TestCase):
    def test_create_alert_workitem_schema(self):
        with tempfile.TemporaryDirectory() as td:
            orig = mon_mod.ALERTS_PATH
            mon_mod.ALERTS_PATH = Path(td) / "a.json"
            try:
                m = GovernanceMonitor.__new__(GovernanceMonitor)
                m.run_id = "MON-S"
                m.timestamp_iso = "2026-07-03T00:00:00+00:00"
                item = m.create_alert_workitem("Failure", "test")
            finally:
                mon_mod.ALERTS_PATH = orig
        required = {"type", "work_type", "actor", "status", "trigger", "detail", "created_at", "source", "run_id"}
        self.assertTrue(required.issubset(set(item.keys())))

    def test_pending_alerts_append(self):
        with tempfile.TemporaryDirectory() as td:
            orig = mon_mod.ALERTS_PATH
            mon_mod.ALERTS_PATH = Path(td) / "a.json"
            try:
                m = GovernanceMonitor.__new__(GovernanceMonitor)
                m.run_id = "MON-A"
                m.timestamp_iso = "2026-07-03T00:00:00+00:00"
                m.create_alert_workitem("Failure", "first")
                m.create_alert_workitem("Calibration_Drift", "second")
                with open(mon_mod.ALERTS_PATH) as f:
                    saved = json.load(f)
            finally:
                mon_mod.ALERTS_PATH = orig
        self.assertEqual(len(saved), 2)

    def test_journal_append(self):
        with tempfile.TemporaryDirectory() as td:
            orig = mon_mod.JOURNAL_PATH
            mon_mod.JOURNAL_PATH = Path(td) / "j.jsonl"
            try:
                m = GovernanceMonitor.__new__(GovernanceMonitor)
                m.run_id = "MON-J"
                m.timestamp_iso = "2026-07-03T00:00:00+00:00"
                m._write_journal({"score": 0.8, "status": "NORMAL"}, [], 0, [])
                with open(mon_mod.JOURNAL_PATH) as f:
                    lines = [l for l in f if l.strip()]
            finally:
                mon_mod.JOURNAL_PATH = orig
        self.assertEqual(len(lines), 1)
        self.assertIn("ghs", json.loads(lines[0]))

    def test_boot_briefing_generated(self):
        with tempfile.TemporaryDirectory() as td:
            orig = mon_mod.BRIEFING_PATH
            mon_mod.BRIEFING_PATH = Path(td) / "b.json"
            try:
                m = GovernanceMonitor.__new__(GovernanceMonitor)
                m.run_id = "MON-B"
                m.timestamp_iso = "2026-07-03T00:00:00+00:00"
                m._update_boot_briefing({"score": 0.82, "status": "NORMAL"}, [], 0, [])
                with open(mon_mod.BRIEFING_PATH) as f:
                    brief = json.load(f)
            finally:
                mon_mod.BRIEFING_PATH = orig
        self.assertIn("ghs", brief)
        self.assertIn("score", brief["ghs"])

    def test_run_returns_summary(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            mon_mod.JOURNAL_PATH     = tmp / "j.jsonl"
            mon_mod.BRIEFING_PATH    = tmp / "b.json"
            mon_mod.ALERTS_PATH      = tmp / "a.json"
            mon_mod.GHS_HISTORY_PATH = tmp / "h.json"
            try:
                m = GovernanceMonitor()
                with (patch.object(m, "_get_calibration_error_rate", return_value=0.0),
                      patch.object(m, "_get_failure_repeat_rate",    return_value=0.0),
                      patch.object(m, "_get_opportunity_decay_rate", return_value=0.0),
                      patch.object(m, "_get_process_compliance_rate",    return_value=1.0),
                      patch.object(m, "_get_constitution_adherence_rate", return_value=1.0)):
                    result = m.run()
            finally:
                mon_mod.JOURNAL_PATH     = ROOT / "tools/monitor/monitor_journal.jsonl"
                mon_mod.BRIEFING_PATH    = ROOT / "tools/monitor/boot_briefing.json"
                mon_mod.ALERTS_PATH      = ROOT / "tools/monitor/pending_alerts.json"
                mon_mod.GHS_HISTORY_PATH = ROOT / "tools/monitor/ghs_history.json"
        self.assertTrue({"run_id", "ghs", "triggers_fired", "alerts_created"}.issubset(set(result.keys())))




class TestOverdueReviews(unittest.TestCase):
    def _mon(self):
        m = GovernanceMonitor.__new__(GovernanceMonitor)
        m.run_id = "MON-OD"
        m.timestamp_iso = "2026-07-04T00:00:00+00:00"
        return m

    def test_overdue_detected(self):
        import tempfile
        m = self._mon()
        sc = {
            "review_schedule": {
                "weekly_failure_audit": {"last_run": None, "next_due": "2026-01-01"},
            }
        }
        pointer = {"current_session": 9901}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "SESSION_CONTEXT_POINTER.json").write_text(json.dumps(pointer))
            (tmp / "SESSION_CONTEXT_S9901_FINAL.json").write_text(json.dumps(sc))
            orig = mon_mod.ROOT
            mon_mod.ROOT = tmp
            try:
                result = m._check_overdue_reviews()
            finally:
                mon_mod.ROOT = orig
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "weekly_failure_audit")

    def test_no_overdue_future_date(self):
        import tempfile
        m = self._mon()
        sc = {
            "review_schedule": {
                "weekly_failure_audit": {"last_run": None, "next_due": "2099-12-31"},
            }
        }
        pointer = {"current_session": 9902}
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "SESSION_CONTEXT_POINTER.json").write_text(json.dumps(pointer))
            (tmp / "SESSION_CONTEXT_S9902_FINAL.json").write_text(json.dumps(sc))
            orig = mon_mod.ROOT
            mon_mod.ROOT = tmp
            try:
                result = m._check_overdue_reviews()
            finally:
                mon_mod.ROOT = orig
        self.assertEqual(len(result), 0)

    def test_missing_files_returns_empty(self):
        import tempfile
        m = self._mon()
        with tempfile.TemporaryDirectory() as td:
            orig = mon_mod.ROOT
            mon_mod.ROOT = Path(td)
            try:
                result = m._check_overdue_reviews()
            finally:
                mon_mod.ROOT = orig
        self.assertEqual(result, [])

if __name__ == "__main__":
    unittest.main()

import json
import sys
import pytest
from pathlib import Path

ROOT = Path("/opt/arss/engine/arss-protocol")
sys.path.insert(0, str(ROOT / "tools/governance"))

import area_11_decision_ledger as al
from area_11_decision_ledger import DecisionClass, DecisionLedgerError


class TestDecisionClass:
    """DecisionClass Enum"""

    def test_dc1_value(self):
        assert DecisionClass.DC1.value == "DC-1"

    def test_dc4_value(self):
        assert DecisionClass.DC4.value == "DC-4"

    def test_dc3_requires_eag(self):
        assert DecisionClass.DC3.requires_eag is True

    def test_dc4_requires_eag(self):
        assert DecisionClass.DC4.requires_eag is True

    def test_dc1_not_requires_eag(self):
        assert DecisionClass.DC1.requires_eag is False

    def test_dc2_not_requires_eag(self):
        assert DecisionClass.DC2.requires_eag is False


class TestArea11DecisionLedger:
    """AIF Area 11: Decision Ledger"""

    def test_module_version(self):
        assert al.VERSION == "1.0.0"
        assert al.EAG_ID == "EAG-S321-AIF-AREA11-13-001"

    def test_record_dc1_success(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            entry = al.record_decision(
                dc=DecisionClass.DC1,
                subject="routine decision",
                rationale="daily operational",
                actor="caddy",
            )
            assert entry["dc"] == "DC-1"
            assert entry["schema"] == "decision_ledger_v1"
            assert entry["actor"] == "caddy"
            assert entry["eag"] is None
            assert al.LOG_PATH.exists()
        finally:
            al.LOG_PATH = original

    def test_record_dc3_with_eag(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            entry = al.record_decision(
                dc=DecisionClass.DC3,
                subject="critical decision",
                rationale="critical rationale",
                eag="EAG-TEST-003",
                actor="beo",
            )
            assert entry["dc"] == "DC-3"
            assert entry["eag"] == "EAG-TEST-003"
        finally:
            al.LOG_PATH = original

    def test_record_dc3_without_eag_raises(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            with pytest.raises(DecisionLedgerError):
                al.record_decision(
                    dc=DecisionClass.DC3,
                    subject="critical",
                    rationale="rationale",
                )
        finally:
            al.LOG_PATH = original

    def test_record_dc4_without_eag_raises(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            with pytest.raises(DecisionLedgerError):
                al.record_decision(
                    dc=DecisionClass.DC4,
                    subject="constitutional",
                    rationale="rationale",
                )
        finally:
            al.LOG_PATH = original

    def test_record_empty_subject_raises(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            with pytest.raises(DecisionLedgerError):
                al.record_decision(
                    dc=DecisionClass.DC1,
                    subject="",
                    rationale="rationale",
                )
        finally:
            al.LOG_PATH = original

    def test_get_decisions_by_class(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            al.record_decision(DecisionClass.DC1, "A", "r1", actor="beo")
            al.record_decision(DecisionClass.DC2, "B", "r2", actor="beo")
            al.record_decision(DecisionClass.DC1, "C", "r3", actor="caddy")
            dc1_list = al.get_decisions_by_class(DecisionClass.DC1)
            assert len(dc1_list) == 2
            dc2_list = al.get_decisions_by_class(DecisionClass.DC2)
            assert len(dc2_list) == 1
        finally:
            al.LOG_PATH = original

    def test_get_recent_decisions(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            for i in range(5):
                al.record_decision(DecisionClass.DC1, f"sub{i}", "r", actor="beo")
            recent = al.get_recent_decisions(3)
            assert len(recent) == 3
            assert recent[0]["subject"] == "sub4"
        finally:
            al.LOG_PATH = original

    def test_get_recent_decisions_empty(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            result = al.get_recent_decisions()
            assert result == []
        finally:
            al.LOG_PATH = original

    def test_get_decision_summary_empty(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            summary = al.get_decision_summary()
            assert summary["total_count"] == 0
            assert summary["schema"] == "decision_ledger_summary_v1"
            assert summary["version"] == "1.0.0"
        finally:
            al.LOG_PATH = original

    def test_get_decision_summary_with_entries(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            al.record_decision(DecisionClass.DC1, "A", "r", actor="beo")
            al.record_decision(DecisionClass.DC1, "B", "r", actor="beo")
            al.record_decision(DecisionClass.DC2, "C", "r", actor="caddy")
            summary = al.get_decision_summary()
            assert summary["total_count"] == 3
            assert summary["class_counts"].get("DC-1") == 2
            assert summary["class_counts"].get("DC-2") == 1
        finally:
            al.LOG_PATH = original

    def test_dc2_with_optional_eag(self, tmp_path):
        original = al.LOG_PATH
        al.LOG_PATH = tmp_path / "decision_ledger.jsonl"
        try:
            entry = al.record_decision(
                dc=DecisionClass.DC2,
                subject="significant",
                rationale="rationale",
                eag="EAG-OPTIONAL",
            )
            assert entry["eag"] == "EAG-OPTIONAL"
        finally:
            al.LOG_PATH = original

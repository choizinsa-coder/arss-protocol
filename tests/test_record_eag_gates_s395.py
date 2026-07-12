"""
tests/test_record_eag_gates_s395.py
EAG-S395-DECISION-LEDGER-WIRING-IMPL-001

Isolation contract: EVERY test monkeypatches dl.LOG_PATH to tmp.
The production decision_ledger.jsonl must never be touched by the suite
(S372/S374 contamination class).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools" / "close") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "close"))

from tools.governance import area_11_decision_ledger as dl
from tools.close.record_eag_gates import record_eag_gates
import session_close_generator as scg

VALIDATOR = scg._validate_approval_id
PROD_LEDGER = ROOT / "tools" / "governance" / "decision_ledger.jsonl"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    p = tmp_path / "decision_ledger.jsonl"
    monkeypatch.setattr(dl, "LOG_PATH", p)
    return p


def _entries(p):
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_normal_record(ledger, capsys):
    gates = ["EAG-S395-ALPHA-001 (impl)", "EAG-S395-BETA-002 (close)"]
    r = record_eag_gates(395, gates, VALIDATOR)
    assert r["recorded"] == 2
    assert r["skipped"] == 0
    assert r["errors"] == 0
    rows = _entries(ledger)
    assert len(rows) == 2
    assert all(e["dc"] == "DC-3" for e in rows)
    assert {e["eag"] for e in rows} == {"EAG-S395-ALPHA-001", "EAG-S395-BETA-002"}
    assert "[EAG-LEDGER]" in capsys.readouterr().out


def test_duplicate_skipped(ledger):
    gates = ["EAG-S395-ALPHA-001 (impl)"]
    record_eag_gates(395, gates, VALIDATOR)
    r = record_eag_gates(395, gates, VALIDATOR)
    assert r["recorded"] == 0
    assert r["skipped"] == 1
    assert len(_entries(ledger)) == 1


def test_invalid_id_is_error_not_record(ledger):
    r = record_eag_gates(395, ["not-an-eag (x)"], VALIDATOR)
    assert r["recorded"] == 0
    assert r["errors"] == 1
    assert _entries(ledger) == []


def test_missing_or_empty_warns(ledger, capsys):
    r1 = record_eag_gates(395, None, VALIDATOR)
    r2 = record_eag_gates(395, [], VALIDATOR)
    assert r1["warn"] and r2["warn"]
    assert r1["recorded"] == 0 and r1["errors"] == 0
    assert not ledger.exists()
    assert "[EAG-LEDGER]" in capsys.readouterr().out


def test_ledger_path_isolated(ledger):
    record_eag_gates(395, ["EAG-S395-ALPHA-001 (x)"], VALIDATOR)
    assert Path(dl.LOG_PATH) == ledger
    assert Path(dl.LOG_PATH) != PROD_LEDGER
    assert ledger.exists()

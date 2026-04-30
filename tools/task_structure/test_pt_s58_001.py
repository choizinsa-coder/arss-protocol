"""
PT-S58-001 — test_pt_s58_001.py
TASK STRUCTURE REFACTOR v1.0
pytest test suite.
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from migration_validator import validate, STATUS_STANDARD

SSOT_PATH = "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"


@pytest.fixture
def live_data():
    with open(SSOT_PATH) as f:
        return json.load(f)


# ── T1: STATUS_STANDARD closed set ──────────────────────────────
def test_status_standard_count():
    assert len(STATUS_STANDARD) == 12


def test_status_standard_contains_required():
    required = {
        "DESIGN_PENDING", "EAG_1_PENDING", "EAG_2_PENDING",
        "EAG_3_PENDING", "READY_FOR_DEPLOY", "IN_PROGRESS",
        "BLOCKED", "HOLD", "COMPLETED", "CANCELED",
        "SUPERSEDED", "ARCHIVED"
    }
    assert required == STATUS_STANDARD


# ── T2: 4-bucket structure exists ───────────────────────────────
def test_four_buckets_exist(live_data):
    assert "active_tasks" in live_data
    assert "blocked_tasks" in live_data
    assert "hold_tasks" in live_data
    assert "archived_tasks" in live_data


# ── T3: total count match ────────────────────────────────────────
def test_total_count_match(live_data):
    original = len(live_data.get("pending_tasks", []))
    total = (len(live_data["active_tasks"]) +
             len(live_data["blocked_tasks"]) +
             len(live_data["hold_tasks"]) +
             len(live_data["archived_tasks"]))
    assert total == original


# ── T4: validator PASS on live data ─────────────────────────────
def test_validator_pass_live(live_data):
    result = validate(live_data)
    assert result["verdict"] == "PASS"
    assert result["error_count"] == 0


# ── T5: no archived status in active_tasks ──────────────────────
def test_active_tasks_no_archived(live_data):
    archived_statuses = {"COMPLETED", "CANCELED", "SUPERSEDED", "ARCHIVED"}
    for t in live_data["active_tasks"]:
        assert t["status"] not in archived_statuses,             f"active_tasks contains archived status: {t.get('id')}"


# ── T6: no active status in archived_tasks ──────────────────────
def test_archived_tasks_no_active(live_data):
    active_statuses = {
        "DESIGN_PENDING", "EAG_1_PENDING", "EAG_2_PENDING",
        "EAG_3_PENDING", "READY_FOR_DEPLOY", "IN_PROGRESS"
    }
    for t in live_data["archived_tasks"]:
        assert t["status"] not in active_statuses,             f"archived_tasks contains active status: {t.get('id')}"


# ── T7: hold_tasks.executable=false ─────────────────────────────
def test_hold_tasks_executable_false(live_data):
    for t in live_data["hold_tasks"]:
        assert "executable" in t,             f"hold_tasks missing executable: {t.get('id')}"
        assert t["executable"] is False,             f"hold_tasks executable not False: {t.get('id')}"


# ── T8: blocked_tasks.block_reason ──────────────────────────────
def test_blocked_tasks_block_reason(live_data):
    for t in live_data["blocked_tasks"]:
        assert "block_reason" in t,             f"blocked_tasks missing block_reason: {t.get('id')}"
        assert isinstance(t["block_reason"], str),             f"block_reason not string: {t.get('id')}"
        assert t["block_reason"].strip() != "",             f"block_reason empty: {t.get('id')}"


# ── T9: all task ids unique ──────────────────────────────────────
def test_all_ids_unique(live_data):
    all_tasks = (live_data["active_tasks"] +
                 live_data["blocked_tasks"] +
                 live_data["hold_tasks"] +
                 live_data["archived_tasks"])
    ids = [t.get("id") for t in all_tasks if t.get("id")]
    assert len(ids) == len(set(ids)), "Duplicate IDs found"


# ── T10: shim is_canonical=False ────────────────────────────────
def test_shim_not_canonical(live_data):
    shim = live_data.get("pending_tasks_legacy_shim", {})
    assert shim.get("is_canonical") is False
    assert shim.get("mutation_forbidden") is True


# ── T11: chain tip unchanged ────────────────────────────────────
def test_chain_tip_unchanged(live_data):
    expected = "eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd"
    actual = live_data.get("chain", {}).get("tip", "")
    assert actual == expected, f"chain tip changed: {actual}"


# ── T12: validator fail-closed — invalid status ──────────────────
def test_validator_fail_invalid_status():
    data = {
        "active_tasks": [{"id": "TEST-001", "status": "INVALID_XYZ"}],
        "blocked_tasks": [], "hold_tasks": [], "archived_tasks": []
    }
    result = validate(data)
    assert result["verdict"] == "FAIL"


# ── T13: validator fail-closed — missing id ──────────────────────
def test_validator_fail_missing_id():
    data = {
        "active_tasks": [{"task": "no id", "status": "IN_PROGRESS"}],
        "blocked_tasks": [], "hold_tasks": [], "archived_tasks": []
    }
    result = validate(data)
    assert result["verdict"] == "FAIL"


# ── T14: validator fail-closed — hold missing executable ─────────
def test_validator_fail_hold_no_executable():
    data = {
        "active_tasks": [], "blocked_tasks": [],
        "hold_tasks": [{"id": "TEST-002", "status": "HOLD"}],
        "archived_tasks": []
    }
    result = validate(data)
    assert result["verdict"] == "FAIL"


# ── T15: validator fail-closed — blocked missing block_reason ────
def test_validator_fail_blocked_no_reason():
    data = {
        "active_tasks": [], "hold_tasks": [],
        "blocked_tasks": [{"id": "TEST-003", "status": "BLOCKED"}],
        "archived_tasks": []
    }
    result = validate(data)
    assert result["verdict"] == "FAIL"

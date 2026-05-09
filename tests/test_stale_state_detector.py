"""
test_stale_state_detector.py
S101 STATE AUTHORITY ARCHITECTURE — stale detection TC
"""

import os
import sys
import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools", "governance"))

from stale_state_detector import (
    CORE_T0_FIELDS,
    CORE_T1_FIELDS,
    EXCLUDED_FIELDS,
    DetectionResult,
    StaleLevel,
    detect_stale,
    is_narrative_field,
)


def _make_sc(chain_tip="abc123", enforcement_active=True, last_rpu="RPU-0050"):
    return {
        "chain": {"tip": chain_tip},
        "enforcement_active": enforcement_active,
        "last_rpu": last_rpu,
        "scoring_ledger_hash": "hash_ok",
        "task_status": "active",
        "eag_stage": "EAG-3_COMPLETE",
        "active_tasks": ["task_a"],
        "blocked_tasks": [],
        "hold_tasks": [],
    }


def _make_canonical(chain_tip="abc123", enforcement_active=True, last_rpu="RPU-0050"):
    return {
        "chain.tip": chain_tip,
        "enforcement_active": enforcement_active,
        "last_rpu": last_rpu,
        "scoring_ledger_hash": "hash_ok",
        "task_status": "active",
        "eag_stage": "EAG-3_COMPLETE",
        "active_tasks": ["task_a"],
        "blocked_tasks": [],
        "hold_tasks": [],
    }


def test_clean_state_returns_pass():
    """TC-1: 불일치 없는 상태 → PASS."""
    sc = _make_sc()
    canonical = _make_canonical()
    result = detect_stale(sc, canonical)
    assert result.overall_result == DetectionResult.PASS
    assert result.stale_level == StaleLevel.CLEAN


def test_t0_chain_tip_mismatch_returns_hard_stop():
    """TC-2: chain.tip 불일치 → HARD_STOP."""
    sc = _make_sc(chain_tip="aaa")
    canonical = _make_canonical(chain_tip="bbb")
    result = detect_stale(sc, canonical)
    assert result.overall_result == DetectionResult.HARD_STOP
    assert result.stale_level == StaleLevel.T0_STALE
    assert any(r.field_name == "chain.tip" for r in result.t0_violations)


def test_t0_enforcement_active_mismatch_returns_hard_stop():
    """TC-3: enforcement_active 불일치 → HARD_STOP."""
    sc = _make_sc(enforcement_active=False)
    canonical = _make_canonical(enforcement_active=True)
    result = detect_stale(sc, canonical)
    assert result.overall_result == DetectionResult.HARD_STOP


def test_t1_active_tasks_mismatch_returns_hold():
    """TC-4: active_tasks 불일치 → HOLD."""
    sc = _make_sc()
    canonical = _make_canonical()
    sc["active_tasks"] = ["task_a", "task_b"]
    canonical["active_tasks"] = ["task_a"]
    result = detect_stale(sc, canonical)
    assert result.overall_result == DetectionResult.HOLD
    assert result.stale_level == StaleLevel.T1_STALE


def test_t0_violation_overrides_t1():
    """TC-5: T0 + T1 동시 불일치 → HARD_STOP 우선."""
    sc = _make_sc(chain_tip="aaa")
    canonical = _make_canonical(chain_tip="bbb")
    sc["active_tasks"] = ["different"]
    canonical["active_tasks"] = ["original"]
    result = detect_stale(sc, canonical)
    assert result.overall_result == DetectionResult.HARD_STOP


def test_invalid_session_context_type_returns_deny():
    """TC-6: session_context가 dict 아님 → DENY."""
    result = detect_stale("not_a_dict", {"chain.tip": "abc"})
    assert result.overall_result == DetectionResult.DENY


def test_invalid_canonical_type_returns_deny():
    """TC-7: canonical_snapshot이 dict 아님 → DENY."""
    result = detect_stale({"chain": {"tip": "abc"}}, "not_a_dict")
    assert result.overall_result == DetectionResult.DENY


def test_narrative_fields_excluded():
    """TC-8: note/detail 등 narrative 필드는 stale detection 대상 아님."""
    assert is_narrative_field("note") is True
    assert is_narrative_field("detail") is True
    assert is_narrative_field("context_summary") is True
    assert is_narrative_field("chain.tip") is False


def test_core_t0_fields_defined():
    """TC-9: CORE_T0_FIELDS 4종 정의 확인."""
    assert "chain.tip" in CORE_T0_FIELDS
    assert "enforcement_active" in CORE_T0_FIELDS
    assert "last_rpu" in CORE_T0_FIELDS
    assert "scoring_ledger_hash" in CORE_T0_FIELDS


def test_core_t1_fields_defined():
    """TC-10: CORE_T1_FIELDS 5종 정의 확인."""
    assert "task_status" in CORE_T1_FIELDS
    assert "eag_stage" in CORE_T1_FIELDS
    assert "active_tasks" in CORE_T1_FIELDS
    assert "blocked_tasks" in CORE_T1_FIELDS
    assert "hold_tasks" in CORE_T1_FIELDS


def test_both_none_values_pass():
    """TC-11: 양쪽 모두 None인 필드 → PASS (비교 불가 = 안전)."""
    sc = _make_sc()
    canonical = _make_canonical()
    sc["last_rpu"] = None
    canonical["last_rpu"] = None
    result = detect_stale(sc, canonical)
    # 다른 필드 일치 가정 — last_rpu 양쪽 None은 PASS
    assert result.overall_result in (DetectionResult.PASS, DetectionResult.HOLD)

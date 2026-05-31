# RULE-8 ASSERTION — S181 Batch-11A
# Module: boot_vnext_contract
# Task: P4-C4 Phase-beta Batch-11A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.session_context_gen.boot_vnext_contract import (
    AuthorityMode,
    AVCode,
    SufficiencyLevel,
    evaluate_sufficiency,
    HARD_STOP_CONDITIONS,
    CONTAMINATION_RULES,
)


def _make_clean_validator_result():
    return {"result": "PASS", "violations": [], "reviews": [], "hard_stop_reason": None}


def _make_minimal_boot(runtime_pair_hash="abc123"):
    return {
        "boot_meta": {"runtime_pair_hash": runtime_pair_hash},
        "canonical_governance": {
            "governance_mode": "DEP_V1_2",
            "approved_authority_layers": ["L1"],
        },
        "dependency_visibility": {"retrieval_mode": "v1.1"},
        "historical_reference": {"historical_anchor_hash": "deadbeef"},
    }


def test_contract_rejects_invalid_authority_mode():
    """AuthorityMode enum에 없는 값은 ValueError를 발생시켜야 한다."""
    with pytest.raises(ValueError):
        AuthorityMode("INVALID_MODE")


def test_contract_sufficiency_fails_on_missing_criteria():
    """runtime_pair_hash 누락 시 sufficiency level이 FAIL이어야 한다."""
    boot = _make_minimal_boot(runtime_pair_hash="")
    vr = _make_clean_validator_result()
    # runtime_pair_hash 제거
    boot["boot_meta"]["runtime_pair_hash"] = ""
    result = evaluate_sufficiency(boot, vr)
    assert result["level"] == SufficiencyLevel.FAIL
    assert "runtime_pair_reference" in result["missing"]


def test_contract_hard_stop_conditions_nonempty():
    """HARD_STOP_CONDITIONS 리스트는 비어있지 않아야 한다 (계약 불변성)."""
    assert isinstance(HARD_STOP_CONDITIONS, list)
    assert len(HARD_STOP_CONDITIONS) > 0


def test_contract_sufficiency_hard_stop_on_validator_hard_stop():
    """validator_result.result == HARD_STOP 시 sufficiency level도 HARD_STOP이어야 한다."""
    boot = _make_minimal_boot()
    vr = {
        "result": "HARD_STOP",
        "violations": [],
        "reviews": [],
        "hard_stop_reason": "unresolved_authority_crossing",
    }
    result = evaluate_sufficiency(boot, vr)
    assert result["level"] == SufficiencyLevel.HARD_STOP

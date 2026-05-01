"""
tests/test_phase2_validator.py
==============================
PT-S66-001 Shadow Mode Phase 2 — phase2_validator 테스트 7케이스
EAG-2 APPROVED by 비오(Joshua) — S66
"""

import pytest
from tools.delta_context.phase2_validator import (
    check_preconditions,
    check_timestamp_window,
    check_mutation_prohibition,
    run_comparison_contract,
    validate_phase2,
    compute_normalized_payload_hash,
    COMPARISON_CONTRACT_PASS,
    COMPARISON_CONTRACT_FAIL,
    COMPARISON_CONTRACT_BLOCKED,
)


def _base_payload(generated_at="2026-05-01T10:00:00.000+09:00"):
    return {
        "schema_version": "3.1",
        "generated_at": generated_at,
        "chain": {"tip": "abc123", "last_rpu": "RPU-0020"},
        "sync_meta": {"evolution_score": 77},
        "data": "test_value",
    }


def _base_ctx(candidate=None, ssot=None):
    c = candidate or _base_payload()
    s = ssot or _base_payload()
    return {
        "shadow_mode": True,
        "index_loaded": True,
        "delta_count": 3,
        "session_number": 66,
        "candidate_payload": c,
        "ssot_payload": s,
        "phase1_complete": True,
    }


# TC-1: precondition 7개 모두 PASS
def test_tc1_preconditions_all_pass():
    result = check_preconditions(_base_ctx())
    assert result["passed"] is True
    assert result["failed_conditions"] == []


# TC-2: shadow_mode=False → PC-1 실패
def test_tc2_shadow_mode_false():
    ctx = _base_ctx()
    ctx["shadow_mode"] = False
    result = check_preconditions(ctx)
    assert result["passed"] is False
    assert any("PC-1" in f for f in result["failed_conditions"])


# TC-3: 동일 payload → hash match → contract PASS
def test_tc3_hash_match_contract_pass():
    payload = _base_payload()
    result = run_comparison_contract(payload, payload, payload["generated_at"], payload["generated_at"])
    assert result["contract"] == COMPARISON_CONTRACT_PASS
    assert result["normalized_payload_hash_match"] is True
    assert result["reasons"] == []


# TC-4: candidate payload 다름 → hash mismatch → contract FAIL
def test_tc4_hash_mismatch_contract_fail():
    candidate = _base_payload()
    candidate["data"] = "modified"
    ssot = _base_payload()
    ts = "2026-05-01T10:00:00.000+09:00"
    result = run_comparison_contract(candidate, ssot, ts, ts)
    assert result["contract"] == COMPARISON_CONTRACT_FAIL
    assert result["normalized_payload_hash_match"] is False
    assert any("hash" in r for r in result["reasons"])


# TC-5: timestamp window 초과 → contract FAIL
def test_tc5_timestamp_window_exceeded():
    payload = _base_payload()
    candidate_ts = "2026-05-01T10:00:00.000+09:00"
    ssot_ts = "2026-05-01T10:10:00.000+09:00"  # 600초 차이
    result = run_comparison_contract(payload, payload, candidate_ts, ssot_ts)
    assert result["contract"] == COMPARISON_CONTRACT_FAIL
    assert result["timestamp_window"]["within_window"] is False


# TC-6: mutation prohibition 위반 (chain 변경) → contract FAIL
def test_tc6_mutation_prohibition_violated():
    candidate = _base_payload()
    ssot = _base_payload()
    candidate["chain"] = {"tip": "TAMPERED", "last_rpu": "RPU-9999"}
    ts = "2026-05-01T10:00:00.000+09:00"
    result = run_comparison_contract(candidate, ssot, ts, ts)
    assert result["contract"] == COMPARISON_CONTRACT_FAIL
    assert "chain" in result["mutation_prohibition"]["violations"]


# TC-7: validate_phase2 통합 — precondition FAIL 시 contract None
def test_tc7_validate_phase2_precondition_fail():
    ctx = _base_ctx()
    ctx["phase1_complete"] = False
    ctx["delta_count"] = 0
    result = validate_phase2(ctx)
    assert result["phase2_valid"] is False
    assert result["contract"] is None
    assert not result["preconditions"]["passed"]

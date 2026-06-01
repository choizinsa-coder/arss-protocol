# tests/test_contract_validator.py
# RULE-8 Batch-13B — S182
# 설계: 도미 BRIEFING-CADDY-S182-BATCH13-DOMI-DESIGN-1 (D-3: compute_hash 실 구현 / Mock 금지)
# EAG: EAG-S182-BATCH13B (비오 승인)
# 제니 TRUST-ADVISORY: 테스트 상단 compute_hash 실측 해시 대조 선언 배치
# 대상: tools/session_context_gen/contract_validator.py
#
# Assertion 우선순위: Guard Condition → Contract Integrity → State Result → Happy Path
# FORBIDDEN: Mock, patch, monkeypatch on compute_hash

import pytest

from tools.session_context_gen.contract_validator import (
    validate_boot_contract,
    validate_runtime_contract,
    validate_pair_contract,
    validate_all,
    BOOT_REQUIRED_FIELDS,
    RUNTIME_FORBIDDEN_FIELDS,
    EXPECTED_RUNTIME_PAIR_RULE,
)
from tools.session_context_gen.hash_utils import compute_hash


# ── [제니 TRUST-ADVISORY] compute_hash 실측 해시 대조 선언 ────────────────
# Mock 금지 통제: 실 구현이 결정론적으로 동작함을 테스트 진입 전 수학적으로 검증
_ANCHOR_DICT = {"session_count": 182, "chain": {"tip": "abc1234"}}
_EXPECTED_ANCHOR_HASH = "ef7063a20b5101addf88c25878b5f9712bb2b19821c25e0c72b058eec2c2dfcf"
assert compute_hash(_ANCHOR_DICT) == _EXPECTED_ANCHOR_HASH, (
    "GOVERNANCE_CHAIN_LOCK_VIOLATION: compute_hash 실측 결과가 Batch-13A 기준 해시와 불일치. "
    "Mock 또는 hash_utils 변조 의심."
)
# ─────────────────────────────────────────────────────────────────────────


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def valid_runtime():
    return {
        "session_count": 182,
        "chain": {"tip": "abc1234"},
    }


@pytest.fixture
def valid_boot(valid_runtime):
    runtime_hash = compute_hash(valid_runtime)
    return {
        "session_count": 182,
        "chain": {"tip": "abc1234"},
        "boot_meta": {
            "boot_is_ssot": False,
            "ssot_ref": "SESSION_CONTEXT.json",
            "conflict_resolution": "BOOT_WINS",
            "generated_from_sha256": "a" * 64,
            "boot_generated_at": "2026-06-01T12:00:00+09:00",
            "runtime_pair_hash": runtime_hash,
            "runtime_pair_rule": EXPECTED_RUNTIME_PAIR_RULE,
        },
        "canonical_rules": {},
        "lessons": [],
        "pending_tasks": [],
        "state_events": [],
        "decisions": [],
    }


# ── P1: Guard Condition — validate_boot_contract ──────────────────────────

def test_boot_contract_required_field_missing(valid_boot):
    """BOOT_REQUIRED_FIELDS 누락 → pass=False, errors 포함"""
    boot = dict(valid_boot)
    del boot["canonical_rules"]
    result = validate_boot_contract(boot)
    assert result["pass"] is False
    assert any("canonical_rules" in e for e in result["errors"])


def test_boot_contract_boot_is_ssot_true_fails(valid_boot):
    """boot_is_ssot=True → pass=False"""
    boot = dict(valid_boot)
    boot["boot_meta"] = dict(boot["boot_meta"])
    boot["boot_meta"]["boot_is_ssot"] = True
    result = validate_boot_contract(boot)
    assert result["pass"] is False
    assert any("boot_is_ssot" in e for e in result["errors"])


def test_boot_contract_runtime_pair_rule_invalid_fails(valid_boot):
    """runtime_pair_rule 오값 → pass=False"""
    boot = dict(valid_boot)
    boot["boot_meta"] = dict(boot["boot_meta"])
    boot["boot_meta"]["runtime_pair_rule"] = "WRONG_RULE"
    result = validate_boot_contract(boot)
    assert result["pass"] is False
    assert any("runtime_pair_rule" in e for e in result["errors"])


def test_boot_contract_forbidden_field_fails(valid_boot):
    """BOOT_FORBIDDEN_FIELDS 포함 → pass=False"""
    boot = dict(valid_boot)
    boot["boot_hash"] = "should_not_exist"
    result = validate_boot_contract(boot)
    assert result["pass"] is False
    assert any("boot_hash" in e for e in result["errors"])


# ── P2: Guard Condition — validate_runtime_contract ──────────────────────

def test_runtime_contract_required_field_missing():
    """session_count 누락 → pass=False"""
    runtime = {"chain": {"tip": "abc1234"}}
    result = validate_runtime_contract(runtime)
    assert result["pass"] is False
    assert any("session_count" in e for e in result["errors"])


def test_runtime_contract_forbidden_field_fails(valid_runtime):
    """RUNTIME_FORBIDDEN_FIELDS 포함 → pass=False"""
    runtime = dict(valid_runtime)
    runtime["runtime_pair_hash"] = "forbidden_value"
    result = validate_runtime_contract(runtime)
    assert result["pass"] is False
    assert any("runtime_pair_hash" in e for e in result["errors"])


# ── P3: Contract Integrity — validate_pair_contract ──────────────────────

def test_pair_contract_session_count_mismatch_fails(valid_boot):
    """session_count 불일치 → pass=False"""
    runtime = {"session_count": 999, "chain": {"tip": "abc1234"}}
    result = validate_pair_contract(valid_boot, runtime)
    assert result["pass"] is False
    assert any("session_count" in e for e in result["errors"])


def test_pair_contract_chain_tip_mismatch_fails(valid_boot):
    """chain.tip 불일치 → pass=False"""
    runtime = {"session_count": 182, "chain": {"tip": "DIFFERENT_TIP"}}
    result = validate_pair_contract(valid_boot, runtime)
    assert result["pass"] is False
    assert any("chain.tip" in e for e in result["errors"])


def test_pair_contract_runtime_pair_hash_mismatch_fails(valid_runtime):
    """runtime_pair_hash 불일치 → pass=False (실 compute_hash 사용)"""
    boot = {
        "session_count": 182,
        "chain": {"tip": "abc1234"},
        "boot_meta": {
            "boot_is_ssot": False,
            "ssot_ref": "SESSION_CONTEXT.json",
            "conflict_resolution": "BOOT_WINS",
            "generated_from_sha256": "a" * 64,
            "boot_generated_at": "2026-06-01T12:00:00+09:00",
            "runtime_pair_hash": "wrong_hash_value_not_matching_runtime",
            "runtime_pair_rule": EXPECTED_RUNTIME_PAIR_RULE,
        },
        "canonical_rules": {},
        "lessons": [],
        "pending_tasks": [],
        "state_events": [],
        "decisions": [],
    }
    result = validate_pair_contract(boot, valid_runtime)
    assert result["pass"] is False
    assert any("runtime_pair_hash" in e for e in result["errors"])


# ── P4: Happy Path ────────────────────────────────────────────────────────

def test_boot_contract_valid_passes(valid_boot):
    """유효한 BOOT → pass=True"""
    result = validate_boot_contract(valid_boot)
    assert result["pass"] is True
    assert result["errors"] == []


def test_runtime_contract_valid_passes(valid_runtime):
    """유효한 RUNTIME → pass=True"""
    result = validate_runtime_contract(valid_runtime)
    assert result["pass"] is True
    assert result["errors"] == []


def test_pair_contract_valid_passes(valid_boot, valid_runtime):
    """유효한 BOOT+RUNTIME 쌍 → pass=True (실 compute_hash 검증)"""
    result = validate_pair_contract(valid_boot, valid_runtime)
    assert result["pass"] is True
    assert result["errors"] == []
    # 실측 hash 값 검증 (Mock 금지 확인)
    assert result["runtime_hash"] == compute_hash(valid_runtime)


def test_validate_all_valid_passes(valid_boot, valid_runtime):
    """validate_all 전체 통과 → pass=True, 3개 계약 모두 True"""
    result = validate_all(valid_boot, valid_runtime)
    assert result["pass"] is True
    assert result["summary"]["BOOT_CONTRACT_V1"] is True
    assert result["summary"]["RUNTIME_CONTRACT_V1"] is True
    assert result["summary"]["PAIR_CONTRACT_V1"] is True

"""
test_phase3a_contract.py — Sub-Phase 3A Contract Validation Tests
Authority: 도미 설계 / 캐디 구현 / 제니 검증 / 비오 EAG
SSOT Ref: Sub-Phase 3A 재구성 설계 — S101

TC 구성 (9개):
  TC-1: BOOT contract PASS — 정상 입력
  TC-2: BOOT contract FAIL — required field 누락
  TC-3: BOOT contract FAIL — boot_meta required field 누락
  TC-4: BOOT contract FAIL — forbidden field 존재
  TC-5: RUNTIME contract PASS — 정상 입력
  TC-6: RUNTIME contract FAIL — forbidden reverse-reference field
  TC-7: PAIR contract PASS — 정상 BOOT/RUNTIME 쌍
  TC-8: PAIR contract FAIL — session_count mismatch
  TC-9: PAIR contract FAIL — runtime_pair_hash mismatch

Principle:
  formalization_ready != pytest pass
  These tests verify governance contract integrity,
  NOT execution convenience.
"""

import json
import pytest

from tools.session_context_gen.contract_validator import (
    validate_boot_contract,
    validate_runtime_contract,
    validate_pair_contract,
    validate_all,
)
from tools.session_context_gen.hash_utils import compute_hash


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_runtime(session_count: int = 101, chain_tip: str = "abc123") -> dict:
    return {
        "session_count": session_count,
        "chain": {"tip": chain_tip},
    }


def _make_boot(runtime: dict) -> dict:
    runtime_hash = compute_hash(runtime)
    return {
        "session_count": runtime["session_count"],
        "chain": runtime["chain"].copy(),
        "boot_meta": {
            "boot_is_ssot": False,
            "ssot_ref": "SESSION_CONTEXT_S101_FINAL.json",
            "conflict_resolution": "FULL wins. BOOT invalid if conflict.",
            "generated_from_sha256": "deadbeef" * 8,
            "boot_generated_at": "2026-05-08T00:00:00+09:00",
            "runtime_pair_hash": runtime_hash,
            "runtime_pair_rule": "BOOT_REFERENCES_RUNTIME_ONLY",
        },
        "canonical_rules": {},
        "lessons": [],
        "pending_tasks": [],
        "state_events": [],
        "decisions": [],
    }


# ── TC-1: BOOT contract PASS ──────────────────────────────────────────────────

def test_tc1_boot_contract_pass():
    """TC-1: 정상 BOOT 입력 → BOOT_CONTRACT_V1 PASS"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)

    result = validate_boot_contract(boot)

    assert result["pass"] is True, f"TC-1 FAIL: {result['errors']}"
    assert result["contract"] == "BOOT_CONTRACT_V1"
    assert result["errors"] == []


# ── TC-2: BOOT contract FAIL — required field 누락 ────────────────────────────

def test_tc2_boot_contract_fail_missing_required_field():
    """TC-2: BOOT required field 누락 → BOOT_CONTRACT_V1 FAIL"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)
    del boot["session_count"]  # required field 제거

    result = validate_boot_contract(boot)

    assert result["pass"] is False, "TC-2 FAIL: expected FAIL but got PASS"
    assert any("session_count" in e for e in result["errors"]), (
        f"TC-2: expected session_count error, got: {result['errors']}"
    )


# ── TC-3: BOOT contract FAIL — boot_meta required field 누락 ─────────────────

def test_tc3_boot_contract_fail_missing_boot_meta_field():
    """TC-3: boot_meta 필수 필드 누락 → BOOT_CONTRACT_V1 FAIL"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)
    del boot["boot_meta"]["runtime_pair_hash"]  # boot_meta 필수 필드 제거

    result = validate_boot_contract(boot)

    assert result["pass"] is False, "TC-3 FAIL: expected FAIL but got PASS"
    assert any("runtime_pair_hash" in e for e in result["errors"]), (
        f"TC-3: expected runtime_pair_hash error, got: {result['errors']}"
    )


# ── TC-4: BOOT contract FAIL — forbidden field 존재 ──────────────────────────

def test_tc4_boot_contract_fail_forbidden_field():
    """TC-4: BOOT에 forbidden field 존재 → BOOT_CONTRACT_V1 FAIL"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)
    boot["boot_hash"] = "should_not_be_here"  # forbidden field 주입

    result = validate_boot_contract(boot)

    assert result["pass"] is False, "TC-4 FAIL: expected FAIL but got PASS"
    assert any("boot_hash" in e for e in result["errors"]), (
        f"TC-4: expected boot_hash forbidden error, got: {result['errors']}"
    )


# ── TC-5: RUNTIME contract PASS ───────────────────────────────────────────────

def test_tc5_runtime_contract_pass():
    """TC-5: 정상 RUNTIME 입력 → RUNTIME_CONTRACT_V1 PASS"""
    runtime = _make_runtime()

    result = validate_runtime_contract(runtime)

    assert result["pass"] is True, f"TC-5 FAIL: {result['errors']}"
    assert result["contract"] == "RUNTIME_CONTRACT_V1"
    assert result["errors"] == []


# ── TC-6: RUNTIME contract FAIL — forbidden reverse-reference field ───────────

def test_tc6_runtime_contract_fail_forbidden_reverse_reference():
    """TC-6: RUNTIME에 reverse-reference forbidden field → RUNTIME_CONTRACT_V1 FAIL"""
    runtime = _make_runtime()
    runtime["runtime_pair_hash"] = "circular_reference_risk"  # forbidden field

    result = validate_runtime_contract(runtime)

    assert result["pass"] is False, "TC-6 FAIL: expected FAIL but got PASS"
    assert any("runtime_pair_hash" in e for e in result["errors"]), (
        f"TC-6: expected runtime_pair_hash forbidden error, got: {result['errors']}"
    )


# ── TC-7: PAIR contract PASS ──────────────────────────────────────────────────

def test_tc7_pair_contract_pass():
    """TC-7: 정상 BOOT/RUNTIME 쌍 → PAIR_CONTRACT_V1 PASS"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)

    result = validate_pair_contract(boot, runtime)

    assert result["pass"] is True, f"TC-7 FAIL: {result['errors']}"
    assert result["contract"] == "PAIR_CONTRACT_V1"
    assert result["errors"] == []
    assert result["runtime_hash"] == compute_hash(runtime)


# ── TC-8: PAIR contract FAIL — session_count mismatch ────────────────────────

def test_tc8_pair_contract_fail_session_count_mismatch():
    """TC-8: session_count 불일치 → PAIR_CONTRACT_V1 FAIL"""
    runtime = _make_runtime(session_count=101)
    boot = _make_boot(runtime)
    boot["session_count"] = 999  # mismatch 주입

    result = validate_pair_contract(boot, runtime)

    assert result["pass"] is False, "TC-8 FAIL: expected FAIL but got PASS"
    assert any("session_count mismatch" in e for e in result["errors"]), (
        f"TC-8: expected session_count mismatch error, got: {result['errors']}"
    )


# ── TC-9: PAIR contract FAIL — runtime_pair_hash mismatch ────────────────────

def test_tc9_pair_contract_fail_runtime_pair_hash_mismatch():
    """TC-9: runtime_pair_hash 불일치 → PAIR_CONTRACT_V1 FAIL"""
    runtime = _make_runtime()
    boot = _make_boot(runtime)
    boot["boot_meta"]["runtime_pair_hash"] = "wrong_hash_value"  # 오염 주입

    result = validate_pair_contract(boot, runtime)

    assert result["pass"] is False, "TC-9 FAIL: expected FAIL but got PASS"
    assert any("runtime_pair_hash mismatch" in e for e in result["errors"]), (
        f"TC-9: expected runtime_pair_hash mismatch error, got: {result['errors']}"
    )

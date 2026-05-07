"""
test_pair_validator.py
PT-S81-ARCH-001 Phase 2 — pair_validator 테스트
pair_validator.py v1.1.0 실제 계약 기준 fixture 정합화
PT-S93-003 fixture 재작성 (S94)
"""
import hashlib
import json
import sys
import os

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.pair_validator import validate_boot_runtime_pair
from tools.session_context_gen.hash_utils import compute_hash


# ── 공통 픽스처 ──────────────────────────────────────────────────────────────

def _make_runtime(
    session_count=93,
    chain_tip="eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd",
):
    return {
        "session_count": session_count,
        "chain": {
            "tip": chain_tip,
        },
    }


def _make_boot(
    session_count=93,
    chain_tip="eeffbe715b4877158529339fc7b6487af6a384adc0a261ba58f2413e13be9ecd",
    runtime_pair_hash=None,
    runtime_pair_rule="BOOT_REFERENCES_RUNTIME_ONLY",
):
    rt = _make_runtime(session_count, chain_tip)
    rh = compute_hash(rt) if runtime_pair_hash is None else runtime_pair_hash
    return {
        "session_count": session_count,
        "chain": {
            "tip": chain_tip,
        },
        "boot_meta": {
            "runtime_pair_hash": rh,
            "runtime_pair_rule": runtime_pair_rule,
        },
    }


# ── TC-1: 정상 PASS ───────────────────────────────────────────────────────────

def test_tc1_valid_pair_pass():
    runtime = _make_runtime()
    boot = _make_boot()
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is True, f"TC-1 FAIL: {result['errors']}"
    assert result["validator"] == "pair_validator"
    assert result["errors"] == []
    assert result["runtime_hash"] == compute_hash(runtime)
    assert result["boot_hash"] == compute_hash(boot)


# ── TC-2: session_count 불일치 ────────────────────────────────────────────────

def test_tc2_session_count_mismatch():
    runtime = _make_runtime()
    boot = _make_boot()
    boot["session_count"] = 99
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("session_count mismatch" in e for e in result["errors"])


# ── TC-3: schema_version — pair_validator.py 미검증 필드, TC 제거 ─────────────
# pair_validator.py v1.1.0은 schema_version을 검증하지 않음 (PT-S93-003 확정)
# 해당 TC 제거 처리


# ── TC-4: chain.tip 불일치 ────────────────────────────────────────────────────

def test_tc4_chain_tip_mismatch():
    runtime = _make_runtime()
    boot = _make_boot()
    boot["chain"]["tip"] = "deadbeef"
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("chain.tip mismatch" in e for e in result["errors"])


# ── TC-5: boot_meta.runtime_pair_hash 누락 ───────────────────────────────────

def test_tc5_runtime_pair_hash_missing():
    runtime = _make_runtime()
    boot = _make_boot()
    del boot["boot_meta"]["runtime_pair_hash"]
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("runtime_pair_hash missing in boot_meta" in e for e in result["errors"])


# ── TC-6: boot_meta.runtime_pair_hash 값 불일치 ──────────────────────────────

def test_tc6_runtime_pair_hash_mismatch():
    runtime = _make_runtime()
    boot = _make_boot()
    boot["boot_meta"]["runtime_pair_hash"] = "0" * 64  # 위조값
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("runtime_pair_hash mismatch" in e for e in result["errors"])


# ── TC-7: boot_meta.runtime_pair_rule 누락 ───────────────────────────────────

def test_tc7_runtime_pair_rule_missing():
    runtime = _make_runtime()
    boot = _make_boot()
    del boot["boot_meta"]["runtime_pair_rule"]
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("runtime_pair_rule missing in boot_meta" in e for e in result["errors"])


# ── TC-8: boot_meta.runtime_pair_rule 값 오류 ────────────────────────────────

def test_tc8_runtime_pair_rule_invalid():
    runtime = _make_runtime()
    boot = _make_boot()
    boot["boot_meta"]["runtime_pair_rule"] = "INVALID_RULE"
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("runtime_pair_rule invalid" in e for e in result["errors"])


# ── TC-9: RUNTIME에 boot_hash 포함 (역방향 참조) ─────────────────────────────

def test_tc9_runtime_contains_boot_hash():
    runtime = _make_runtime()
    runtime["boot_hash"] = "abcd1234"
    boot = _make_boot()
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("boot_hash" in e for e in result["errors"])


# ── TC-10: RUNTIME에 runtime_pair_hash 포함 ──────────────────────────────────

def test_tc10_runtime_contains_runtime_pair_hash():
    runtime = _make_runtime()
    runtime["runtime_pair_hash"] = "abcd1234"
    boot = _make_boot()
    result = validate_boot_runtime_pair(boot, runtime)
    assert result["pass"] is False
    assert any("runtime_pair_hash" in e for e in result["errors"])

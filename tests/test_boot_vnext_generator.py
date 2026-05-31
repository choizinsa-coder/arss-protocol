# RULE-8 ASSERTION — S181 Batch-11A
# Module: boot_vnext_generator
# Task: P4-C4 Phase-beta Batch-11A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from tools.session_context_gen.boot_vnext_generator import generate
from tools.session_context_gen.boot_vnext_contract import AuthorityMode


def _make_valid_ctx():
    return {
        "chain": {"tip": "9bacbe4", "session": 140},
        "session_count": 181,
    }


def test_generator_rejects_missing_required_keys():
    """session_context에 chain/session_count 누락 시 status=FAIL, admission stage."""
    ctx = {"session_count": 181}  # chain 누락
    result = generate(ctx)
    assert result["status"] == "FAIL"
    assert result["details"]["stage"] == "admission"


def test_generator_rejects_non_dict_input():
    """session_context가 dict가 아닌 경우 status=FAIL."""
    result = generate("not_a_dict")  # type: ignore
    assert result["status"] == "FAIL"


def test_generator_pass_returns_boot_with_minimum_structure():
    """유효 입력 시 status=PASS/REVIEW + boot 키에 BOOT_SECTIONS 포함."""
    from tools.session_context_gen.boot_vnext_schema import BOOT_SECTIONS
    ctx = _make_valid_ctx()
    result = generate(ctx, runtime_pair_hash="hash_abc")
    assert result["status"] in ("PASS", "REVIEW")
    assert "boot" in result
    for section in BOOT_SECTIONS:
        assert section in result["boot"], f"boot missing section: {section}"


def test_generator_rejects_invalid_authority_mode_type():
    """authority_mode에 잘못된 타입 전달 시 FAIL (AttributeError/TypeError 포함)."""
    ctx = _make_valid_ctx()
    try:
        result = generate(ctx, authority_mode="INVALID_MODE", runtime_pair_hash="x")  # type: ignore
        # 반환되었다면 FAIL이어야 함
        assert result["status"] == "FAIL"
    except (AttributeError, TypeError, ValueError):
        pass  # 예외 발생도 허용 — fail-closed

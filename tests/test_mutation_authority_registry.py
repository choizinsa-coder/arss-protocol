"""
test_mutation_authority_registry.py
S101 STATE AUTHORITY ARCHITECTURE — Registry validation TC
"""

import json
import os
import sys
import pytest

# pytest --import-mode=importlib 환경: tools/governance 명시적 경로 주입
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "tools", "governance"))

REGISTRY_PATH = os.path.join(
    _REPO_ROOT,
    "tools", "governance",
    "mutation_authority_registry_v1.0.json",
)


@pytest.fixture
def registry():
    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def test_registry_loads(registry):
    """TC-1: Registry 파일 로드 가능."""
    assert registry is not None
    assert "tiers" in registry
    assert "_meta" in registry


def test_default_behavior_is_deny(registry):
    """TC-2: default_behavior = DENY."""
    assert registry["_meta"]["default_behavior"] == "DENY"


def test_all_four_tiers_present(registry):
    """TC-3: T0/T1/T2/T3 전항목 존재."""
    for tier in ("T0", "T1", "T2", "T3"):
        assert tier in registry["tiers"], f"Tier {tier} missing"


def test_t0_requires_eag(registry):
    """TC-4: T0 requires_eag = true."""
    assert registry["tiers"]["T0"]["requires_eag"] is True


def test_t0_requires_hash_match(registry):
    """TC-5: T0 requires_hash_match = true."""
    assert registry["tiers"]["T0"]["requires_hash_match"] is True


def test_t0_fallback_is_hard_stop(registry):
    """TC-6: T0 fallback_behavior = HARD_STOP."""
    assert registry["tiers"]["T0"]["fallback_behavior"] == "HARD_STOP"


def test_t1_fallback_is_hold(registry):
    """TC-7: T1 fallback_behavior = HOLD."""
    assert registry["tiers"]["T1"]["fallback_behavior"] == "HOLD"


def test_t2_fallback_is_warn(registry):
    """TC-8: T2 fallback_behavior = WARN."""
    assert registry["tiers"]["T2"]["fallback_behavior"] == "WARN"


def test_t3_fallback_is_log(registry):
    """TC-9: T3 fallback_behavior = LOG."""
    assert registry["tiers"]["T3"]["fallback_behavior"] == "LOG"


def test_unknown_handling_all_deny(registry):
    """TC-10: unknown_handling 전항목 DENY/HOLD."""
    uh = registry["unknown_handling"]
    assert uh["unknown_tier"] == "DENY"
    assert uh["unknown_path"] == "DENY"
    assert uh["unknown_tool"] == "DENY"
    assert uh["missing_gate"] == "DENY"
    assert uh["ambiguous_authority"] == "HOLD"


def test_t0_cascade_freezes_all_lower(registry):
    """TC-11: T0 violation cascade = ALL_LOWER_TIERS_FREEZE."""
    rule = registry["cascade_rules"]["T0_violation"]
    assert rule["effect"] == "ALL_LOWER_TIERS_FREEZE"
    assert "T1" in rule["scope"]
    assert "T2" in rule["scope"]
    assert "T3" in rule["scope"]


def test_t2_cascade_no_upward_to_t0(registry):
    """TC-12: T2 cascade upward_to_T0 = false."""
    rule = registry["cascade_rules"]["T2_violation"]
    assert rule["upward_to_T0"] is False


def test_t2_timeout_policy_present(registry):
    """TC-13: T2 timeout_policy 필드 존재."""
    t2 = registry["tiers"]["T2"]
    assert "timeout_policy" in t2
    tp = t2["timeout_policy"]
    assert tp["max_unresolved_sessions"] == 2
    assert tp["min_validation_cycles"] == 1
    assert tp["escalation_target"] == "T1"


def test_t2_timeout_validation_cycle_types(registry):
    """TC-14: T2 validation_cycle_types 4종 존재."""
    tp = registry["tiers"]["T2"]["timeout_policy"]
    vct = tp["validation_cycle_types"]
    assert "governance_checker_execution" in vct
    assert "stale_state_detector_execution" in vct
    assert "sync_reconciliation_pass" in vct
    assert "eag_review_pass" in vct


def test_mutation_authority_registry_self_in_t0_paths(registry):
    """TC-15: mutation_authority_registry 자체가 T0 경로에 포함 (자기 보호)."""
    t0_paths = registry["tiers"]["T0"]["allowed_paths"]
    assert any("mutation_authority_registry" in p for p in t0_paths)

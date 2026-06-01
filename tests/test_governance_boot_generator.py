# tests/test_governance_boot_generator.py
# RULE-8 Batch-13A — S182
# 설계: 도미 BRIEFING-CADDY-S182-BATCH13-DOMI-DESIGN-1
# EAG: EAG-S182-BATCH13A (비오 승인)
# 대상: tools/session_context_gen/governance_boot_generator.py
#
# Assertion 우선순위: Guard Condition → Contract Integrity → State Result → Happy Path

import pytest

from tools.session_context_gen.governance_boot_generator import (
    generate_governance_boot,
    validate_governance_boot_for_consumption,
    get_severity_tier,
    GovernanceBootGeneratorError,
    SEVERITY_TIER_MAP,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

VALID_HASH = "a" * 64  # 유효 SHA256 형식 (소문자 hex 64자)
VALID_HASH_2 = "b" * 64

@pytest.fixture
def valid_registry_digest():
    return [{"registry_id": "REG-001", "latest_hash": VALID_HASH}]


@pytest.fixture
def valid_trust_digest():
    return {
        "trust_state": "TRUST_FULL",
        "oracle_candidate": False,
        "degraded_source_count": 0,
    }


@pytest.fixture
def valid_stale_digest():
    return {
        "stale_state": "FRESH",
        "stale_policy_status": "LOCKED",
    }


@pytest.fixture
def valid_alert_digest():
    return []


@pytest.fixture
def valid_artifact(valid_registry_digest, valid_trust_digest, valid_stale_digest, valid_alert_digest):
    return generate_governance_boot(
        generated_session=182,
        registry_digest=valid_registry_digest,
        trust_digest=valid_trust_digest,
        stale_digest=valid_stale_digest,
        alert_digest=valid_alert_digest,
        canonical_hash=VALID_HASH,
    )


# ── P1: Guard Condition — generate_governance_boot ────────────────────────

def test_generate_registry_digest_empty_raises(valid_trust_digest, valid_stale_digest):
    """registry_digest=[] → HARD_STOP: registry_digest_missing"""
    with pytest.raises(GovernanceBootGeneratorError, match="registry_digest_missing"):
        generate_governance_boot(
            generated_session=182,
            registry_digest=[],
            trust_digest=valid_trust_digest,
            stale_digest=valid_stale_digest,
            alert_digest=[],
            canonical_hash=VALID_HASH,
        )


def test_generate_registry_digest_invalid_hash_raises(valid_trust_digest, valid_stale_digest):
    """latest_hash 비SHA256 → HARD_STOP: digest_hash_invalid"""
    bad_registry = [{"registry_id": "REG-001", "latest_hash": "not_a_sha256"}]
    with pytest.raises(GovernanceBootGeneratorError, match="digest_hash_invalid"):
        generate_governance_boot(
            generated_session=182,
            registry_digest=bad_registry,
            trust_digest=valid_trust_digest,
            stale_digest=valid_stale_digest,
            alert_digest=[],
            canonical_hash=VALID_HASH,
        )


def test_generate_oracle_candidate_unresolved_raises(valid_registry_digest, valid_stale_digest):
    """oracle_candidate=True + trust_state != TRUST_ORACLE_OVERRIDE → HARD_STOP: oracle_candidate_unresolved"""
    bad_trust = {
        "trust_state": "TRUST_FULL",
        "oracle_candidate": True,
        "degraded_source_count": 0,
    }
    with pytest.raises(GovernanceBootGeneratorError, match="oracle_candidate_unresolved"):
        generate_governance_boot(
            generated_session=182,
            registry_digest=valid_registry_digest,
            trust_digest=bad_trust,
            stale_digest=valid_stale_digest,
            alert_digest=[],
            canonical_hash=VALID_HASH,
        )


def test_generate_stale_policy_status_invalid_raises(valid_registry_digest, valid_trust_digest):
    """stale_policy_status 비유효값 → HARD_STOP: stale_policy_status_invalid"""
    bad_stale = {
        "stale_state": "FRESH",
        "stale_policy_status": "UNKNOWN_VALUE",
    }
    with pytest.raises(GovernanceBootGeneratorError, match="stale_policy_status_invalid"):
        generate_governance_boot(
            generated_session=182,
            registry_digest=valid_registry_digest,
            trust_digest=valid_trust_digest,
            stale_digest=bad_stale,
            alert_digest=[],
            canonical_hash=VALID_HASH,
        )


def test_generate_canonical_hash_invalid_raises(valid_registry_digest, valid_trust_digest, valid_stale_digest):
    """canonical_hash 비SHA256 → HARD_STOP: digest_hash_invalid / sync_anchor_unknown"""
    with pytest.raises(GovernanceBootGeneratorError):
        generate_governance_boot(
            generated_session=182,
            registry_digest=valid_registry_digest,
            trust_digest=valid_trust_digest,
            stale_digest=valid_stale_digest,
            alert_digest=[],
            canonical_hash="",
        )


# ── P2: Contract Integrity — validate_governance_boot_for_consumption ─────

def test_consume_sync_anchor_missing_raises(valid_artifact):
    """sync_anchor 누락 → HARD_STOP: sync_anchor_unknown"""
    artifact = dict(valid_artifact)
    del artifact["sync_anchor"]
    with pytest.raises(GovernanceBootGeneratorError, match="sync_anchor_unknown"):
        validate_governance_boot_for_consumption(artifact)


def test_consume_registry_digest_missing_raises(valid_artifact):
    """registry_digest 빈 리스트 → HARD_STOP: registry_digest_missing"""
    artifact = dict(valid_artifact)
    artifact["registry_digest"] = []
    with pytest.raises(GovernanceBootGeneratorError, match="registry_digest_missing"):
        validate_governance_boot_for_consumption(artifact)


def test_consume_oracle_candidate_unresolved_raises(valid_artifact):
    """oracle_candidate=True + trust_state 불일치 → HARD_STOP: oracle_candidate_unresolved"""
    artifact = dict(valid_artifact)
    artifact["trust_digest"] = {
        "trust_state": "TRUST_FULL",
        "oracle_candidate": True,
        "degraded_source_count": 0,
    }
    with pytest.raises(GovernanceBootGeneratorError, match="oracle_candidate_unresolved"):
        validate_governance_boot_for_consumption(artifact)


# ── P3: State Result ───────────────────────────────────────────────────────

def test_generate_returns_required_keys(valid_artifact):
    """정상 생성 artifact → 필수 키 존재"""
    required = {
        "boot_id", "schema_version", "generated_session",
        "generated_at", "digest_scope", "governance_state",
        "registry_digest", "trust_digest", "stale_digest",
        "alert_digest", "sync_anchor",
    }
    assert required.issubset(valid_artifact.keys())


def test_generate_governance_state_observable(valid_registry_digest, valid_trust_digest, valid_stale_digest):
    """TRUST_FULL + FRESH → governance_state=OBSERVABLE"""
    artifact = generate_governance_boot(
        generated_session=182,
        registry_digest=valid_registry_digest,
        trust_digest=valid_trust_digest,
        stale_digest=valid_stale_digest,
        alert_digest=[],
        canonical_hash=VALID_HASH,
    )
    assert artifact["governance_state"] == "OBSERVABLE"


def test_generate_governance_state_degraded(valid_registry_digest, valid_stale_digest):
    """TRUST_DEGRADED → governance_state=DEGRADED"""
    degraded_trust = {
        "trust_state": "TRUST_DEGRADED",
        "oracle_candidate": False,
        "degraded_source_count": 2,
    }
    artifact = generate_governance_boot(
        generated_session=182,
        registry_digest=valid_registry_digest,
        trust_digest=degraded_trust,
        stale_digest=valid_stale_digest,
        alert_digest=[],
        canonical_hash=VALID_HASH,
    )
    assert artifact["governance_state"] == "DEGRADED"


def test_generate_mismatch_flag_true_when_hashes_differ(valid_registry_digest, valid_trust_digest, valid_stale_digest):
    """canonical_hash ≠ 계산된 digest_hash → mismatch_flag=True"""
    artifact = generate_governance_boot(
        generated_session=182,
        registry_digest=valid_registry_digest,
        trust_digest=valid_trust_digest,
        stale_digest=valid_stale_digest,
        alert_digest=[],
        canonical_hash=VALID_HASH_2,  # 다른 해시
    )
    assert artifact["sync_anchor"]["mismatch_flag"] is True


# ── P4: get_severity_tier ─────────────────────────────────────────────────

def test_severity_tier_warning():
    """WARNING → T0"""
    assert get_severity_tier("WARNING") == "T0"


def test_severity_tier_review():
    """REVIEW → T1"""
    assert get_severity_tier("REVIEW") == "T1"


def test_severity_tier_fail():
    """FAIL → T2_T3"""
    assert get_severity_tier("FAIL") == "T2_T3"


def test_severity_tier_unknown_raises():
    """미등록 severity → ValueError"""
    with pytest.raises(ValueError, match="Unknown severity"):
        get_severity_tier("INVALID")

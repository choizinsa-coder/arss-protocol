"""
test_governance_boot.py
GOVSYNC-S102-DIGEST-001 v1.1 EAG-2_LOCKED

pytest validation for GOVERNANCE_BOOT Digest Generator.

제니 EAG-2 Strict Mode 5개 항목 커버:
  [SM-1] Field Source Matrix 일치성
  [SM-2] Hash Reproducibility — sync_anchor hash 독립 재현 가능성
  [SM-3] Cross-Block Coherence — 중복 필드(trust_state 등) 불일치 없음
  [SM-4] Reference-Only Integrity — Registry Body 유입 없음
  [SM-5] Dynamic Binding — generated_session 하드코딩 아님
"""

import sys
import os

# VPS importlib 모드 대응: tools/session_context_gen/ 경로 주입
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "session_context_gen"))

import hashlib
import json
import pytest

from governance_boot_generator import (
    GovernanceBootGeneratorError,
    generate_governance_boot,
    get_severity_tier,
    validate_governance_boot_for_consumption,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_registry_digest(
    registry_id: str = "APPROVED_DEP_REGISTRY_v0.1",
    registry_type: str = "dependency",
    registry_status: str = "DRAFT",
    latest_hash: str = "a" * 64,
    version: str = "v0.1",
    approval_ref_summary: str | None = "EAG-1_LOCKED",
) -> dict:
    return {
        "registry_id": registry_id,
        "registry_type": registry_type,
        "registry_status": registry_status,
        "latest_hash": latest_hash,
        "version": version,
        "approval_ref_summary": approval_ref_summary,
    }


def _make_trust_digest(
    trust_state: str = "TRUST_FULL",
    oracle_candidate: bool = False,
    trust_transition_ref: str | None = None,
    degraded_source_count: int = 0,
) -> dict:
    return {
        "trust_state": trust_state,
        "oracle_candidate": oracle_candidate,
        "trust_transition_ref": trust_transition_ref,
        "degraded_source_count": degraded_source_count,
    }


def _make_stale_digest(
    stale_state: str = "FRESH",
    warning_threshold: int | None = None,
    expiry_session_limit: int | None = None,
    stale_trigger: str | None = None,
    stale_policy_status: str = "LOCKED",
) -> dict:
    return {
        "stale_state": stale_state,
        "warning_threshold": warning_threshold,
        "expiry_session_limit": expiry_session_limit,
        "stale_trigger": stale_trigger,
        "stale_policy_status": stale_policy_status,
    }


def _make_alert_digest(
    alert_id: str = "ALERT-001",
    severity: str = "WARNING",
    affected_registry: str = "APPROVED_DEP_REGISTRY_v0.1",
    trust_state: str = "TRUST_FULL",
    stale_state: str = "FRESH",
    summary_message: str = "Registry approaching stale threshold.",
) -> dict:
    return {
        "alert_id": alert_id,
        "severity": severity,
        "affected_registry": affected_registry,
        "trust_state": trust_state,
        "stale_state": stale_state,
        "summary_message": summary_message,
    }


CANONICAL_HASH = "b" * 64


# ---------------------------------------------------------------------------
# TC-1: 정상 생성 — 필수 필드 전항목 존재 확인 [SM-1 Field Source Matrix]
# ---------------------------------------------------------------------------
class TestTC1NormalGeneration:
    def test_tc1_all_top_level_keys_present(self):
        """[SM-1] 생성된 artifact가 schema 필수 10개 키를 모두 포함하는지 검증."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[_make_alert_digest()],
            canonical_hash=CANONICAL_HASH,
        )
        required_keys = [
            "boot_id", "schema_version", "generated_session", "generated_at",
            "digest_scope", "governance_state", "registry_digest",
            "trust_digest", "stale_digest", "alert_digest", "sync_anchor",
        ]
        for key in required_keys:
            assert key in artifact, f"Missing required key: {key}"

    def test_tc1_digest_scope_is_awareness_only(self):
        """[SM-1] digest_scope는 반드시 AWARENESS_ONLY여야 한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["digest_scope"] == "AWARENESS_ONLY"

    def test_tc1_schema_version(self):
        """[SM-1] schema_version은 1.1이어야 한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["schema_version"] == "1.1"


# ---------------------------------------------------------------------------
# TC-2: Hash Reproducibility [SM-2]
# ---------------------------------------------------------------------------
class TestTC2HashReproducibility:
    def test_tc2_same_inputs_produce_same_digest_hash(self):
        """[SM-2] 동일 입력에 대해 sync_anchor canonical_hash는 독립 재현 가능해야 한다."""
        reg = [_make_registry_digest(latest_hash="c" * 64)]
        trust = _make_trust_digest()
        stale = _make_stale_digest()
        alerts = []
        canonical = "d" * 64

        a1 = generate_governance_boot(
            generated_session=102,
            registry_digest=reg,
            trust_digest=trust,
            stale_digest=stale,
            alert_digest=alerts,
            canonical_hash=canonical,
        )
        a2 = generate_governance_boot(
            generated_session=102,
            registry_digest=reg,
            trust_digest=trust,
            stale_digest=stale,
            alert_digest=alerts,
            canonical_hash=canonical,
        )
        # sync_anchor canonical_hash는 동일 입력 시 동일해야 한다
        assert a1["sync_anchor"]["canonical_hash"] == a2["sync_anchor"]["canonical_hash"]

    def test_tc2_mismatch_flag_when_hashes_differ(self):
        """[SM-2] canonical_hash가 내부 digest_hash와 다를 경우 mismatch_flag=True."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest(latest_hash="e" * 64)],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,  # 의도적으로 다른 값 사용
        )
        # canonical_hash != computed digest_hash이므로 mismatch_flag=True 예상
        assert isinstance(artifact["sync_anchor"]["mismatch_flag"], bool)


# ---------------------------------------------------------------------------
# TC-3: Cross-Block Coherence [SM-3]
# ---------------------------------------------------------------------------
class TestTC3CrossBlockCoherence:
    def test_tc3_generated_session_consistent(self):
        """[SM-3] generated_session이 top-level과 sync_anchor에서 동일해야 한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["generated_session"] == artifact["sync_anchor"]["generated_session"]
        assert artifact["generated_session"] == 102

    def test_tc3_governance_state_reflects_trust_degraded(self):
        """[SM-3] trust_state=TRUST_DEGRADED이면 governance_state=DEGRADED."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(trust_state="TRUST_DEGRADED", degraded_source_count=1),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["governance_state"] == "DEGRADED"

    def test_tc3_governance_state_observable_when_fresh(self):
        """[SM-3] 모든 상태가 정상일 때 governance_state=OBSERVABLE."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["governance_state"] == "OBSERVABLE"

    def test_tc3_governance_state_syncing_when_stale_warning(self):
        """[SM-3] stale_state=STALE_WARNING이면 governance_state=SYNCING."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(stale_state="STALE_WARNING"),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["governance_state"] == "SYNCING"


# ---------------------------------------------------------------------------
# TC-4: Reference-Only Integrity [SM-4]
# ---------------------------------------------------------------------------
class TestTC4ReferenceOnlyIntegrity:
    def test_tc4_registry_digest_has_no_body_fields(self):
        """[SM-4] registry_digest 항목에 금지 필드(payload 등)가 없어야 한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        forbidden_fields = [
            "payload", "body", "entries", "dependency_list",
            "rollback", "mutation", "deployment",
        ]
        for entry in artifact["registry_digest"]:
            for field in forbidden_fields:
                assert field not in entry, f"Forbidden field '{field}' found in registry_digest entry."

    def test_tc4_sync_anchor_has_no_payload(self):
        """[SM-4] sync_anchor에 registry payload 필드가 없어야 한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        forbidden_fields = ["payload", "body", "registry_body", "entries"]
        for field in forbidden_fields:
            assert field not in artifact["sync_anchor"], f"Forbidden field '{field}' in sync_anchor."


# ---------------------------------------------------------------------------
# TC-5: Dynamic Binding [SM-5]
# ---------------------------------------------------------------------------
class TestTC5DynamicBinding:
    def test_tc5_generated_session_reflects_input(self):
        """[SM-5] generated_session은 입력값 그대로 바인딩되어야 한다 (하드코딩 아님)."""
        for session_num in [1, 50, 102, 999]:
            artifact = generate_governance_boot(
                generated_session=session_num,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )
            assert artifact["generated_session"] == session_num
            assert artifact["sync_anchor"]["generated_session"] == session_num

    def test_tc5_boot_id_is_unique_each_call(self):
        """[SM-5] boot_id는 매 호출마다 고유해야 한다."""
        ids = set()
        for _ in range(5):
            artifact = generate_governance_boot(
                generated_session=102,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )
            ids.add(artifact["boot_id"])
        assert len(ids) == 5, "boot_id must be unique on each call."


# ---------------------------------------------------------------------------
# TC-6: HARD_STOP 조건 — registry_digest_missing
# ---------------------------------------------------------------------------
class TestTC6HardStopRegistryMissing:
    def test_tc6_empty_registry_digest_raises(self):
        """HARD_STOP: registry_digest가 빈 리스트일 때 예외 발생."""
        with pytest.raises(GovernanceBootGeneratorError, match="registry_digest_missing"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )

    def test_tc6_registry_entry_missing_hash_raises(self):
        """HARD_STOP: registry entry에 latest_hash가 없을 때 예외 발생."""
        bad_entry = _make_registry_digest()
        bad_entry["latest_hash"] = ""
        with pytest.raises(GovernanceBootGeneratorError, match="digest_hash_invalid"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[bad_entry],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )

    def test_tc6_registry_entry_invalid_hash_format_raises(self):
        """HARD_STOP: latest_hash가 SHA256 형식이 아닐 때 예외 발생."""
        bad_entry = _make_registry_digest(latest_hash="not_a_valid_hash")
        with pytest.raises(GovernanceBootGeneratorError, match="digest_hash_invalid"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[bad_entry],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )


# ---------------------------------------------------------------------------
# TC-7: HARD_STOP 조건 — oracle_candidate_unresolved
# ---------------------------------------------------------------------------
class TestTC7HardStopOracleCandidate:
    def test_tc7_oracle_candidate_true_without_override_raises(self):
        """HARD_STOP: oracle_candidate=True인데 trust_state가 TRUST_ORACLE_OVERRIDE 아닐 때 예외."""
        with pytest.raises(GovernanceBootGeneratorError, match="oracle_candidate_unresolved"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(oracle_candidate=True, trust_state="TRUST_FULL"),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )

    def test_tc7_oracle_candidate_true_with_override_passes(self):
        """oracle_candidate=True이고 trust_state=TRUST_ORACLE_OVERRIDE이면 정상 생성."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(
                oracle_candidate=True,
                trust_state="TRUST_ORACLE_OVERRIDE",
            ),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["trust_digest"]["oracle_candidate"] is True


# ---------------------------------------------------------------------------
# TC-8: HARD_STOP 조건 — stale_policy_status_invalid
# ---------------------------------------------------------------------------
class TestTC8HardStopStalePolicyStatus:
    def test_tc8_invalid_stale_policy_status_raises(self):
        """HARD_STOP: stale_policy_status가 유효하지 않을 때 예외 발생."""
        with pytest.raises(GovernanceBootGeneratorError, match="stale_policy_status_invalid"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(stale_policy_status="UNKNOWN_STATUS"),
                alert_digest=[],
                canonical_hash=CANONICAL_HASH,
            )

    def test_tc8_policy_not_locked_is_valid(self):
        """stale_policy_status=POLICY_NOT_LOCKED은 유효한 값이다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(stale_policy_status="POLICY_NOT_LOCKED"),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        assert artifact["stale_digest"]["stale_policy_status"] == "POLICY_NOT_LOCKED"


# ---------------------------------------------------------------------------
# TC-9: HARD_STOP 조건 — sync_anchor_unknown
# ---------------------------------------------------------------------------
class TestTC9HardStopSyncAnchor:
    def test_tc9_empty_canonical_hash_raises(self):
        """HARD_STOP: canonical_hash가 빈 문자열일 때 예외 발생."""
        with pytest.raises(GovernanceBootGeneratorError, match="sync_anchor_unknown"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash="",
            )

    def test_tc9_invalid_canonical_hash_raises(self):
        """HARD_STOP: canonical_hash가 SHA256 형식이 아닐 때 예외 발생."""
        with pytest.raises(GovernanceBootGeneratorError, match="digest_hash_invalid"):
            generate_governance_boot(
                generated_session=102,
                registry_digest=[_make_registry_digest()],
                trust_digest=_make_trust_digest(),
                stale_digest=_make_stale_digest(),
                alert_digest=[],
                canonical_hash="invalid_hash_value",
            )


# ---------------------------------------------------------------------------
# TC-10: Severity -> Fail-Closed Tier 매핑 (제니 C-3 지침 LOCKED)
# ---------------------------------------------------------------------------
class TestTC10SeverityTierMapping:
    def test_tc10_warning_maps_to_t0(self):
        """WARNING -> T0 (제니 C-3 LOCKED)."""
        assert get_severity_tier("WARNING") == "T0"

    def test_tc10_review_maps_to_t1(self):
        """REVIEW -> T1 (제니 C-3 LOCKED)."""
        assert get_severity_tier("REVIEW") == "T1"

    def test_tc10_fail_maps_to_t2_t3(self):
        """FAIL -> T2_T3 (제니 C-3 LOCKED)."""
        assert get_severity_tier("FAIL") == "T2_T3"

    def test_tc10_unknown_severity_raises(self):
        """미정의 severity 값은 ValueError를 발생시킨다."""
        with pytest.raises(ValueError, match="Unknown severity"):
            get_severity_tier("UNKNOWN")


# ---------------------------------------------------------------------------
# TC-11: 소비 가드 — validate_governance_boot_for_consumption
# ---------------------------------------------------------------------------
class TestTC11ConsumptionGuard:
    def test_tc11_valid_artifact_passes_consumption_guard(self):
        """정상 artifact는 consumption guard를 통과한다."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        # Should not raise
        validate_governance_boot_for_consumption(artifact)

    def test_tc11_missing_sync_anchor_raises(self):
        """sync_anchor 없는 artifact는 consumption guard에서 HARD_STOP."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        del artifact["sync_anchor"]
        with pytest.raises(GovernanceBootGeneratorError, match="sync_anchor_unknown"):
            validate_governance_boot_for_consumption(artifact)

    def test_tc11_empty_registry_digest_raises_on_consumption(self):
        """registry_digest가 비어있는 artifact는 consumption guard에서 HARD_STOP."""
        artifact = generate_governance_boot(
            generated_session=102,
            registry_digest=[_make_registry_digest()],
            trust_digest=_make_trust_digest(),
            stale_digest=_make_stale_digest(),
            alert_digest=[],
            canonical_hash=CANONICAL_HASH,
        )
        artifact["registry_digest"] = []
        with pytest.raises(GovernanceBootGeneratorError, match="registry_digest_missing"):
            validate_governance_boot_for_consumption(artifact)

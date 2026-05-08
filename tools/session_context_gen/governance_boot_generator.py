"""
governance_boot_generator.py
GOVSYNC-S102-DIGEST-001 v1.1 EAG-2_LOCKED

GOVERNANCE_BOOT Digest Generator.
Produces awareness-only digest. NOT a registry replication mechanism.

Fail-Closed Tier Mapping (GOVSYNC-S101-FORMAL v1.1):
  WARNING -> T0 (Informational/Warning Only)
  REVIEW  -> T1 (Awareness Drift/Review Required)
  FAIL    -> T2/T3 (Trust Ambiguity/Canonical Corruption)

HARD_STOP conditions (consume guard):
  - sync_anchor unknown
  - digest hash invalid
  - registry_digest missing
  - ORACLE_CANDIDATE unresolved
  - stale_policy_status invalid
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Severity -> Fail-Closed Tier mapping (제니 C-3 지침 LOCKED)
# ---------------------------------------------------------------------------
SEVERITY_TIER_MAP: dict[str, str] = {
    "WARNING": "T0",
    "REVIEW": "T1",
    "FAIL": "T2_T3",
}

# ---------------------------------------------------------------------------
# HARD_STOP guard constants
# ---------------------------------------------------------------------------
HARD_STOP_CONDITIONS = [
    "sync_anchor_unknown",
    "digest_hash_invalid",
    "registry_digest_missing",
    "oracle_candidate_unresolved",
    "stale_policy_status_invalid",
]


class GovernanceBootGeneratorError(Exception):
    """Raised on HARD_STOP condition during digest generation or consumption."""


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _compute_digest_hash(
    registry_digest: list[dict],
    trust_digest: dict,
    stale_digest: dict,
    alert_digest: list[dict],
) -> str:
    """
    Compute summary digest hash.
    Hash inputs: registry latest_hash list + trust_state + stale_state + alert severity list.
    FORBIDDEN inputs: registry body / runtime payload / deployment data / executable code.
    """
    components = []

    # registry latest_hash references only (not body)
    for entry in registry_digest:
        components.append(entry.get("latest_hash", ""))

    # trust awareness
    components.append(trust_digest.get("trust_state", ""))
    components.append(str(trust_digest.get("oracle_candidate", False)))
    components.append(str(trust_digest.get("degraded_source_count", 0)))

    # stale awareness
    components.append(stale_digest.get("stale_state", ""))
    components.append(stale_digest.get("stale_policy_status", ""))

    # alert severity list
    for alert in alert_digest:
        components.append(alert.get("severity", ""))
        components.append(alert.get("alert_id", ""))

    return _sha256("|".join(components))


def _determine_governance_state(
    trust_digest: dict,
    stale_digest: dict,
) -> str:
    """
    Derive governance_state from trust and stale awareness.
    OBSERVABLE / SYNCING / DEGRADED
    """
    trust_state = trust_digest.get("trust_state", "TRUST_FULL")
    stale_state = stale_digest.get("stale_state", "FRESH")

    if trust_state == "TRUST_DEGRADED" or stale_state == "STALE_DEGRADED":
        return "DEGRADED"
    if trust_state == "TRUST_ORACLE_OVERRIDE" or stale_state in (
        "STALE_WARNING",
        "STALE_REVIEW",
    ):
        return "SYNCING"
    return "OBSERVABLE"


def _validate_registry_digest_input(registry_digest: list[dict]) -> None:
    """Guard: registry_digest must be non-empty list."""
    if not registry_digest:
        raise GovernanceBootGeneratorError(
            "HARD_STOP: registry_digest_missing — "
            "registry_digest must contain at least one entry."
        )
    for entry in registry_digest:
        if not entry.get("latest_hash"):
            raise GovernanceBootGeneratorError(
                f"HARD_STOP: digest_hash_invalid — "
                f"registry entry '{entry.get('registry_id')}' missing latest_hash."
            )
        h = entry["latest_hash"]
        if len(h) != 64 or not all(c in "0123456789abcdef" for c in h):
            raise GovernanceBootGeneratorError(
                f"HARD_STOP: digest_hash_invalid — "
                f"registry entry '{entry.get('registry_id')}' has invalid SHA256 format."
            )


def _validate_trust_digest_input(trust_digest: dict) -> None:
    """Guard: oracle_candidate unresolved check."""
    if trust_digest.get("oracle_candidate") is True:
        trust_state = trust_digest.get("trust_state", "")
        if trust_state != "TRUST_ORACLE_OVERRIDE":
            raise GovernanceBootGeneratorError(
                "HARD_STOP: oracle_candidate_unresolved — "
                "oracle_candidate=True but trust_state is not TRUST_ORACLE_OVERRIDE."
            )


def _validate_stale_digest_input(stale_digest: dict) -> None:
    """Guard: stale_policy_status must be LOCKED or POLICY_NOT_LOCKED."""
    valid_statuses = {"LOCKED", "POLICY_NOT_LOCKED"}
    status = stale_digest.get("stale_policy_status", "")
    if status not in valid_statuses:
        raise GovernanceBootGeneratorError(
            f"HARD_STOP: stale_policy_status_invalid — "
            f"received '{status}', expected one of {valid_statuses}."
        )


def _validate_sync_anchor_input(canonical_hash: str) -> None:
    """Guard: canonical_hash must be valid SHA256."""
    if not canonical_hash:
        raise GovernanceBootGeneratorError(
            "HARD_STOP: sync_anchor_unknown — canonical_hash is empty."
        )
    if len(canonical_hash) != 64 or not all(
        c in "0123456789abcdef" for c in canonical_hash
    ):
        raise GovernanceBootGeneratorError(
            "HARD_STOP: digest_hash_invalid — "
            f"canonical_hash '{canonical_hash}' is not a valid SHA256."
        )


def generate_governance_boot(
    *,
    generated_session: int,
    registry_digest: list[dict],
    trust_digest: dict,
    stale_digest: dict,
    alert_digest: list[dict],
    canonical_hash: str,
    sync_basis: str = "REGISTRY_HASH",
) -> dict[str, Any]:
    """
    Generate a GOVERNANCE_BOOT digest artifact.

    All inputs are awareness metadata ONLY.
    FORBIDDEN: registry body / executable payload / deployment instruction.

    Returns:
        dict: Complete GOVERNANCE_BOOT artifact conforming to governance_boot_schema.json v1.1

    Raises:
        GovernanceBootGeneratorError: On any HARD_STOP condition.
    """
    # --- Input validation (HARD_STOP guards) ---
    _validate_registry_digest_input(registry_digest)
    _validate_trust_digest_input(trust_digest)
    _validate_stale_digest_input(stale_digest)
    _validate_sync_anchor_input(canonical_hash)

    valid_sync_basis = {"REGISTRY_HASH", "TRUST_HASH", "STALE_HASH", "DIGEST_HASH"}
    if sync_basis not in valid_sync_basis:
        raise GovernanceBootGeneratorError(
            f"HARD_STOP: sync_anchor_unknown — "
            f"sync_basis '{sync_basis}' not in {valid_sync_basis}."
        )

    # --- Compute digest hash ---
    digest_hash = _compute_digest_hash(
        registry_digest, trust_digest, stale_digest, alert_digest
    )

    # --- Determine mismatch ---
    mismatch_flag = canonical_hash != digest_hash

    # --- Determine governance_state ---
    governance_state = _determine_governance_state(trust_digest, stale_digest)

    # --- Assemble artifact ---
    artifact: dict[str, Any] = {
        "boot_id": str(uuid.uuid4()),
        "schema_version": "1.1",
        "generated_session": generated_session,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "digest_scope": "AWARENESS_ONLY",
        "governance_state": governance_state,
        "registry_digest": registry_digest,
        "trust_digest": trust_digest,
        "stale_digest": stale_digest,
        "alert_digest": alert_digest,
        "sync_anchor": {
            "canonical_hash": canonical_hash,
            "sync_basis": sync_basis,
            "mismatch_flag": mismatch_flag,
            "generated_session": generated_session,
        },
    }

    return artifact


def validate_governance_boot_for_consumption(artifact: dict[str, Any]) -> None:
    """
    HARD_STOP consumption guard.
    Must be called before any agent consumes a GOVERNANCE_BOOT artifact.

    Raises:
        GovernanceBootGeneratorError: On any HARD_STOP condition.
    """
    # sync_anchor unknown
    sync_anchor = artifact.get("sync_anchor")
    if not sync_anchor or not sync_anchor.get("canonical_hash"):
        raise GovernanceBootGeneratorError(
            "HARD_STOP: sync_anchor_unknown — sync_anchor or canonical_hash missing."
        )

    # digest hash invalid
    canonical_hash = sync_anchor.get("canonical_hash", "")
    if len(canonical_hash) != 64 or not all(
        c in "0123456789abcdef" for c in canonical_hash
    ):
        raise GovernanceBootGeneratorError(
            "HARD_STOP: digest_hash_invalid — canonical_hash format invalid."
        )

    # registry_digest missing
    if not artifact.get("registry_digest"):
        raise GovernanceBootGeneratorError(
            "HARD_STOP: registry_digest_missing — registry_digest is empty."
        )

    # oracle_candidate unresolved
    trust_digest = artifact.get("trust_digest", {})
    if trust_digest.get("oracle_candidate") is True:
        if trust_digest.get("trust_state") != "TRUST_ORACLE_OVERRIDE":
            raise GovernanceBootGeneratorError(
                "HARD_STOP: oracle_candidate_unresolved — "
                "oracle_candidate=True but trust_state is not TRUST_ORACLE_OVERRIDE."
            )

    # stale_policy_status invalid
    stale_digest = artifact.get("stale_digest", {})
    valid_statuses = {"LOCKED", "POLICY_NOT_LOCKED"}
    if stale_digest.get("stale_policy_status") not in valid_statuses:
        raise GovernanceBootGeneratorError(
            f"HARD_STOP: stale_policy_status_invalid — "
            f"value '{stale_digest.get('stale_policy_status')}' is not valid."
        )


def get_severity_tier(severity: str) -> str:
    """
    Map alert severity to Fail-Closed Tier.
    WARNING->T0 / REVIEW->T1 / FAIL->T2_T3
    (제니 C-3 지침 LOCKED)
    """
    if severity not in SEVERITY_TIER_MAP:
        raise ValueError(f"Unknown severity '{severity}'. Must be WARNING/REVIEW/FAIL.")
    return SEVERITY_TIER_MAP[severity]

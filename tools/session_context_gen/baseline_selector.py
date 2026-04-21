import json
import os
from pathlib import Path


class BaselineSelectorError(Exception):
    pass


_PLACEHOLDER_HASHES = frozenset({"", "samplehash123", "prevartifacthash123", "prevhash123"})
_PLACEHOLDER_PATHS = frozenset({"", None})


def _validate_schema(receipt: dict, src: str) -> None:
    for f in ("status", "candidate_rpu", "persistence_allowed"):
        if f not in receipt:
            raise BaselineSelectorError(
                f"Schema mismatch: missing canonical field '{f}' in {src}"
            )
    rpu = receipt["candidate_rpu"]
    if not isinstance(rpu, dict):
        raise BaselineSelectorError(f"candidate_rpu is not a dict in {src}")
    for f in ("schema_version", "rpu_id", "timestamp", "actor_id",
              "payload", "chain", "governance_context"):
        if f not in rpu:
            raise BaselineSelectorError(
                f"Schema mismatch: missing RPU field '{f}' in {src}"
            )
    chain = rpu["chain"]
    if not isinstance(chain, dict):
        raise BaselineSelectorError(f"chain is not a dict in {src}")
    for f in ("payload_hash", "prev_chain_hash", "chain_hash"):
        if f not in chain:
            raise BaselineSelectorError(
                f"Schema mismatch: missing chain field '{f}' in {src}"
            )


def _is_placeholder(receipt: dict) -> bool:
    ext = receipt.get("extension", {})
    artifact_hash = ext.get("artifact_hash")
    artifact_path = ext.get("artifact_path")
    if artifact_hash in _PLACEHOLDER_HASHES:
        return True
    if artifact_path in _PLACEHOLDER_PATHS:
        return True
    return False


def select_baseline(receipts_dir: str) -> dict:
    """
    Select most recent valid baseline receipt. FAIL-CLOSED on any condition failure.

    Raises BaselineSelectorError on:
    - dir not found / no receipts
    - schema mismatch
    - placeholder detected (COMPLETELY FORBIDDEN)
    - no PASS receipts
    - artifact path missing / hash absent / artifact file not found
    - chain broken
    """
    path = Path(receipts_dir)
    if not path.is_dir():
        raise BaselineSelectorError(f"receipts_dir not found: {receipts_dir}")

    receipts = []
    for f in sorted(path.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            raise BaselineSelectorError(f"Failed to load receipt {f.name}: {e}")
        data["_src"] = str(f)
        receipts.append(data)

    if not receipts:
        raise BaselineSelectorError("No receipts found in receipts_dir — FAIL-CLOSED")

    for r in receipts:
        _validate_schema(r, r.get("_src", "unknown"))

    for r in receipts:
        if _is_placeholder(r):
            raise BaselineSelectorError(
                f"Placeholder receipt detected (COMPLETELY FORBIDDEN): {r.get('_src')}"
            )

    pass_receipts = [r for r in receipts if r.get("status") == "PASS"]
    if not pass_receipts:
        raise BaselineSelectorError("No receipts with status=PASS — FAIL-CLOSED")

    for r in pass_receipts:
        ext = r.get("extension", {})
        artifact_path = ext.get("artifact_path", "")
        artifact_hash = ext.get("artifact_hash", "")
        if not artifact_hash:
            raise BaselineSelectorError(
                f"artifact_hash missing or empty in receipt: {r.get('_src')}"
            )
        if not os.path.exists(artifact_path):
            raise BaselineSelectorError(
                f"Artifact not found at path '{artifact_path}' in receipt: {r.get('_src')}"
            )

    pass_receipts.sort(key=lambda r: r["candidate_rpu"]["timestamp"])

    if len(pass_receipts) > 1:
        for i in range(1, len(pass_receipts)):
            expected = pass_receipts[i - 1]["candidate_rpu"]["chain"]["chain_hash"]
            actual = pass_receipts[i]["candidate_rpu"]["chain"]["prev_chain_hash"]
            if actual != expected:
                raise BaselineSelectorError(
                    f"Chain broken at receipt index {i}: "
                    f"expected prev_chain_hash={expected[:16]}..., "
                    f"got {actual[:16]}..."
                )

    result = pass_receipts[-1]
    result.pop("_src", None)
    return result

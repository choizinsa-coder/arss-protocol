import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

DUMMY_PREV_IDS = {"VR-PREV-001", "VR-PREV"}
DUMMY_HASHES = {"prevhash123", "prevartifacthash123", "", None}


class BaselineAmbiguousError(Exception):
    pass


def _is_placeholder(receipt: dict) -> bool:
    baseline = receipt.get("baseline", {})
    prev_id = baseline.get("prev_receipt_id") or ""
    prev_hash = baseline.get("prev_artifact_hash", "")
    prev_line_count = baseline.get("prev_line_count", 0)

    if any(prev_id.startswith(p) for p in DUMMY_PREV_IDS):
        return True
    if prev_line_count == 0 and (prev_hash in DUMMY_HASHES):
        return True
    return False


def _matches_artifact(receipt: dict, current_artifact_hash: str) -> bool:
    baseline = receipt.get("baseline", {})
    target = receipt.get("target_artifact", {})
    return (
        baseline.get("prev_artifact_hash") == current_artifact_hash
        or target.get("artifact_hash_sha256") == current_artifact_hash
    )


def select_last_known_good_receipt(
    candidates: list,
    current_artifact_hash: str = "",
    artifact_type: str = "",
) -> dict:
    valid = []
    for r in candidates:
        if r.get("verdict") != "PASS":
            continue
        if not r.get("checks", {}).get("receipt_integrity_ok"):
            continue
        if _is_placeholder(r):
            continue
        if artifact_type and r.get("target_artifact", {}).get("artifact_type") != artifact_type:
            continue
        if current_artifact_hash and not _matches_artifact(r, current_artifact_hash):
            continue
        valid.append(r)

    if len(valid) == 0:
        return {
            "found": False,
            "prev_receipt_id": None,
            "prev_receipt_hash": None,
            "prev_artifact_hash": None,
            "prev_line_count": 0,
        }

    if len(valid) > 1:
        raise BaselineAmbiguousError(
            "BASELINE_AMBIGUOUS: " + str(len(valid)) + " valid candidates — chain integrity cannot be resolved"
        )

    best = valid[0]
    chain = best.get("receipt_chain", {})

    return {
        "found": True,
        "prev_receipt_id": best.get("receipt_id"),
        "prev_receipt_hash": chain.get("current_receipt_hash"),
        "prev_artifact_hash": best.get("target_artifact", {}).get("artifact_hash_sha256"),
        "prev_line_count": best.get("delta_validation", {}).get("line_count_current", 0),
    }


if __name__ == "__main__":
    result = select_last_known_good_receipt([], current_artifact_hash="", artifact_type="")
    print(json.dumps(result, ensure_ascii=False, indent=2))

select_baseline = select_last_known_good_receipt

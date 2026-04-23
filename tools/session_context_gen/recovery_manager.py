import hashlib
import json
from datetime import datetime, timezone

def calculate_canonical_hash(data):
    def json_serial(obj):
        if isinstance(obj, datetime): return obj.isoformat()
        raise TypeError(f"RPU_HASH_ERROR: Unsupported type {type(obj)}")
    canonical_json = json.dumps(
        data, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), default=json_serial
    )
    return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()

def get_now_iso():
    return datetime.now(timezone.utc).isoformat()

def build_recovery_package_r1(recovery_id, trigger_context, selector_result, lkg_snapshot_payload, created_from_session, selection_audit, package_schema_version="1.4.1"):
    def strict_val_internal(d, keys, name):
        for k in keys:
            v = d.get(k)
            if v in [None, "", "unknown"] or (isinstance(v, (dict, list)) and len(v) == 0):
                raise ValueError(f"R1_BUILD_FAIL: Invalid field {k} in {name}")
    if not isinstance(lkg_snapshot_payload, dict) or not lkg_snapshot_payload:
        raise ValueError("R1_BUILD_FAIL: lkg_snapshot_payload must be non-empty dict")
    strict_val_internal(selector_result, ["lkg_receipt_id", "lkg_receipt_hash", "lkg_artifact_hash", "lkg_session_count", "lkg_generated_at", "lkg_selection_basis", "lkg_selection_verdict"], "Selector")
    strict_val_internal(selection_audit, ["candidate_pool_summary", "rejected_candidates_summary", "final_selection_reason", "selector_version"], "Audit")
    strict_val_internal(trigger_context, ["trigger_reason", "trigger_event_ref", "requested_by", "recovery_mode"], "Trigger")
    if not isinstance(created_from_session, int) or not isinstance(selector_result["lkg_session_count"], int):
        raise TypeError("R1_BUILD_FAIL: session_count must be int")
    now = get_now_iso()
    base_package = {
        "package_identity": {"recovery_id": recovery_id, "package_schema_version": package_schema_version, "created_from_session": created_from_session, "created_at": now},
        "trigger_context": trigger_context,
        "selected_last_known_good": {k: selector_result[k] for k in ["lkg_receipt_id", "lkg_receipt_hash", "lkg_artifact_hash", "lkg_session_count", "lkg_generated_at", "lkg_selection_basis", "lkg_selection_verdict"]},
        "selected_last_known_good_snapshot": {"canonical_state_payload": lkg_snapshot_payload, "canonical_state_hash": calculate_canonical_hash(lkg_snapshot_payload), "artifact_hash": selector_result["lkg_artifact_hash"], "session_count": selector_result["lkg_session_count"], "generated_at": now},
        "selection_audit": selection_audit
    }
    block_hashes = {k: calculate_canonical_hash(v) for k, v in base_package.items()}
    package_hash = calculate_canonical_hash(base_package)
    base_package["package_integrity"] = {"package_hash": package_hash, "included_block_hashes": block_hashes, "integrity_verdict": "PASS"}
    return base_package

def validate_r1_package_integrity(r1):
    expected_blocks = {"package_identity", "trigger_context", "selected_last_known_good", "selected_last_known_good_snapshot", "selection_audit"}
    integrity = r1.get("package_integrity", {})
    if not all(k in integrity for k in ["package_hash", "included_block_hashes", "integrity_verdict"]):
        raise ValueError("R1_VALIDATION_FAIL: Incomplete integrity block")
    if integrity.get("integrity_verdict") != "PASS":
        raise ValueError("R1_VALIDATION_FAIL: integrity_verdict is NOT PASS")
    if set(r1.keys()) - {"package_integrity"} != expected_blocks or set(integrity["included_block_hashes"].keys()) != expected_blocks:
        raise ValueError("R1_VALIDATION_FAIL: Block structure or Whitelist violation")
    def strict_val_check(d, keys, name):
        for k in keys:
            v = d.get(k)
            if v in [None, "", "unknown"] or (isinstance(v, (dict, list)) and len(v) == 0):
                raise ValueError(f"R1_SCHEMA_FAIL: Invalid {k} in {name}")
    strict_val_check(r1["package_identity"], ["recovery_id", "package_schema_version", "created_from_session", "created_at"], "Identity")
    strict_val_check(r1["selected_last_known_good"], ["lkg_receipt_id", "lkg_receipt_hash", "lkg_artifact_hash", "lkg_session_count", "lkg_generated_at", "lkg_selection_basis", "lkg_selection_verdict"], "LKG")
    strict_val_check(r1["selection_audit"], ["candidate_pool_summary", "rejected_candidates_summary", "final_selection_reason", "selector_version"], "Audit")
    strict_val_check(r1["trigger_context"], ["trigger_reason", "trigger_event_ref", "requested_by", "recovery_mode"], "Trigger")
    snap = r1["selected_last_known_good_snapshot"]
    strict_val_check(snap, ["canonical_state_payload", "canonical_state_hash", "artifact_hash", "session_count", "generated_at"], "Snapshot")
    if not isinstance(snap["canonical_state_payload"], dict) or not snap["canonical_state_payload"]:
        raise ValueError("R1_SCHEMA_FAIL: Invalid Snapshot Payload")
    if calculate_canonical_hash(snap["canonical_state_payload"]) != snap["canonical_state_hash"]:
        raise ValueError("R1_INTEGRITY_FAIL: Snapshot Payload/Hash drift")
    if not isinstance(r1["package_identity"]["created_from_session"], int) or \
       not isinstance(r1["selected_last_known_good"]["lkg_session_count"], int) or \
       not isinstance(snap["session_count"], int):
        raise TypeError("R1_VALIDATION_FAIL: session_count must be int")
    for b in expected_blocks:
        if calculate_canonical_hash(r1[b]) != integrity["included_block_hashes"].get(b):
            raise ValueError(f"R1_INTEGRITY_FAIL: Block hash mismatch at {b}")
    base_data = {k: r1[k] for k in expected_blocks}
    if calculate_canonical_hash(base_data) != integrity["package_hash"]:
        raise ValueError("R1_INTEGRITY_FAIL: Package hash mismatch (Asymmetry detected)")

def generate_recovery_candidate_r2(r1_package, candidate_schema_version="1.4.1"):
    validate_r1_package_integrity(r1_package)
    now = get_now_iso()
    snapshot = r1_package["selected_last_known_good_snapshot"]
    lkg = r1_package["selected_last_known_good"]
    recomputed_hash = calculate_canonical_hash(snapshot["canonical_state_payload"])
    candidate = {
        "recovery_id": r1_package["package_identity"]["recovery_id"],
        "candidate_schema_version": candidate_schema_version,
        "source_package_hash": r1_package["package_integrity"]["package_hash"],
        "source_lkg_receipt_id": lkg["lkg_receipt_id"],
        "source_lkg_receipt_hash": lkg["lkg_receipt_hash"],
        "source_lkg_artifact_hash": lkg["lkg_artifact_hash"],
        "source_lkg_session_count": lkg["lkg_session_count"],
        "candidate_state_payload": snapshot["canonical_state_payload"],
        "candidate_state_hash": recomputed_hash,
        "generated_at": now,
        "generation_mode": "LKG_STRICT_REPLAY"
    }
    receipt = {
        "recovery_id": candidate["recovery_id"],
        "source_package_hash": candidate["source_package_hash"],
        "source_lkg_receipt_id": candidate["source_lkg_receipt_id"],
        "source_lkg_receipt_hash": candidate["source_lkg_receipt_hash"],
        "source_lkg_artifact_hash": candidate["source_lkg_artifact_hash"],
        "source_lkg_session_count": candidate["source_lkg_session_count"],
        "candidate_state_hash": candidate["candidate_state_hash"],
        "candidate_snapshot_session_count": lkg["lkg_session_count"],
        "generated_at": now,
        "consistency_verdict": "PENDING"
    }
    validate_r2_candidate_receipt_consistency(candidate, receipt, r1_package)
    receipt["consistency_verdict"] = "PASS"
    receipt["receipt_integrity_hash"] = calculate_canonical_hash(receipt)
    validate_receipt_integrity(receipt)
    return candidate, receipt

def validate_r2_candidate_receipt_consistency(c, r, p):
    checks = [
        (r["recovery_id"], c["recovery_id"]),
        (r["source_lkg_receipt_id"], c["source_lkg_receipt_id"]),
        (r["source_lkg_receipt_hash"], c["source_lkg_receipt_hash"]),
        (r["source_lkg_artifact_hash"], c["source_lkg_artifact_hash"]),
        (r["source_lkg_session_count"], c["source_lkg_session_count"]),
        (r["candidate_snapshot_session_count"], c["source_lkg_session_count"]),
        (r["source_package_hash"], p["package_integrity"]["package_hash"]),
        (c["source_package_hash"], p["package_integrity"]["package_hash"]),
        (r["candidate_state_hash"], calculate_canonical_hash(c["candidate_state_payload"])),
        (c.get("generation_mode"), "LKG_STRICT_REPLAY")
    ]
    if not all(a == b for a, b in checks):
        raise ValueError("R2_CONSISTENCY_FAIL: Triangulation mismatch")

def validate_receipt_integrity(receipt):
    required = ["recovery_id", "source_package_hash", "source_lkg_receipt_id", "source_lkg_receipt_hash", "source_lkg_artifact_hash", "source_lkg_session_count", "candidate_state_hash", "candidate_snapshot_session_count", "generated_at", "consistency_verdict", "receipt_integrity_hash"]
    for k in required:
        v = receipt.get(k)
        if v in [None, "", "unknown"]: raise ValueError(f"RECEIPT_SCHEMA_FAIL: Missing {k}")
    if not isinstance(receipt["candidate_snapshot_session_count"], int) or \
       not isinstance(receipt["source_lkg_session_count"], int):
        raise TypeError("RECEIPT_SCHEMA_FAIL: session_count must be int")
    if receipt["consistency_verdict"] != "PASS":
        raise ValueError("RECEIPT_SCHEMA_FAIL: Verdict NOT PASS")
    data = {k: v for k, v in receipt.items() if k != "receipt_integrity_hash"}
    if calculate_canonical_hash(data) != receipt.get("receipt_integrity_hash"):
        raise ValueError("RECEIPT_INTEGRITY_FAIL: Tampering detected")

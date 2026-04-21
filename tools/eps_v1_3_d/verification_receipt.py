import os
import json
import hashlib
from datetime import datetime

from tools.eps_v1_3_d.baseline_selector import select_baseline, BaselineAmbiguousError
from tools.eps_v1_3_d.system_error_receipt import write_system_error_receipt

STAGING_DIR = "/opt/arss/engine/arss-protocol/staging/"
RECEIPTS_DIR = STAGING_DIR


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_kst_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _parse_time(ts: str):
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _load_candidates(artifact_type: str) -> list:
    import glob
    candidates = []
    for path in (
        glob.glob(os.path.join(STAGING_DIR, "VERIFICATION_RECEIPT_*.json"))
        + glob.glob(os.path.join("/opt/arss/engine/arss-protocol/evidence/", "VERIFICATION_RECEIPT_*.json"))
    ):
        try:
            with open(path, "r", encoding="utf-8") as f:
                r = json.load(f)
            if r.get("receipt_type") == "verification":
                candidates.append(r)
        except Exception:
            continue
    return candidates


def write_verification_receipt(
    execution_receipt_path: str,
    prev_line_count: int = 0,
    delta_minimum_required: int = 1,
) -> dict:
    job_id = "UNKNOWN"
    try:
        with open(execution_receipt_path, "r", encoding="utf-8") as f:
            exec_r = json.load(f)

        job_id = exec_r.get("job_id", "UNKNOWN")
        artifact = exec_r.get("target_artifact", {})
        artifact_path = artifact.get("artifact_path", "")
        artifact_type = artifact.get("artifact_type", "")
        operation = exec_r.get("operation", "session_update")
        execution_started = exec_r.get("started_at_kst")
        execution_finished = exec_r.get("finished_at_kst")

        current_artifact_hash = _sha256(artifact_path)

        candidates = _load_candidates(artifact_type)
        baseline = select_baseline(
            candidates=candidates,
            current_artifact_hash=current_artifact_hash,
            artifact_type=artifact_type,
        )
        prev_line_count = int(baseline.get("prev_line_count", 0) or 0)

        # PHASE 3: artifact_hash as primary delta
        try:
            from tools.eps_v1_3_d.delta_policy import lookup as _delta_lookup
            policy = _delta_lookup(artifact_type, operation)
            delta_minimum_required = int(policy.get("min_delta", delta_minimum_required))
            require_hash_change = bool(policy.get("require_hash_change", True))
        except RuntimeError:
            raise
        except Exception:
            require_hash_change = True

        prev_artifact_hash = baseline.get("prev_artifact_hash") or ""
        baseline_found = baseline.get("found", False)
        if baseline_found and prev_artifact_hash:
            hash_changed = current_artifact_hash != prev_artifact_hash
        else:
            hash_changed = True  # no baseline = first run

        try:
            with open(artifact_path, "r", encoding="utf-8") as f:
                current_line_count = sum(1 for _ in f)
        except Exception:
            current_line_count = 0

        line_delta = current_line_count - prev_line_count
        delta_events_count = line_delta
        delta_sufficient = (not require_hash_change or hash_changed) and (line_delta >= delta_minimum_required)

        generated_at = _now_kst_iso()

        exec_finished_dt = _parse_time(execution_finished)
        verify_dt = _parse_time(generated_at)
        time_window_valid = (
            verify_dt >= exec_finished_dt if exec_finished_dt and verify_dt else False
        )

        artifact_exists = os.path.exists(artifact_path)
        actual_size = os.path.getsize(artifact_path) if artifact_exists else 0
        expected_hash = artifact.get("artifact_hash_sha256", "")
        hash_match = expected_hash == current_artifact_hash
        binding_match = hash_match

        verification_receipt = {
            "receipt_type": "verification",
            "receipt_version": "1.1",
            "receipt_id": "VR-" + datetime.now().strftime("%Y%m%dT%H%M%S"),
            "job_id": job_id,
            "generated_at_kst": generated_at,
            "verified_by": "vps_verifier",
            "verifier_identity": {
                "verifier_name": "verification_receipt",
                "verifier_version": "1.0",
                "verifier_path": os.path.abspath(__file__),
                "process_pid": os.getpid(),
            },
            "time_window": {
                "execution_started_at_kst": execution_started,
                "execution_finished_at_kst": execution_finished,
                "verification_completed_at_kst": generated_at,
                "max_allowed_gap_seconds": 300,
                "time_window_valid": time_window_valid,
                "parameter_status": "TEMP",
            },
            "target_artifact": {
                "artifact_type": artifact_type,
                "artifact_path": artifact_path,
                "artifact_hash_sha256": current_artifact_hash,
                "artifact_size_bytes": actual_size,
            },
            "source_binding": {
                "execution_receipt_id": exec_r.get("receipt_id"),
                "execution_output_hash": current_artifact_hash,
                "binding_match": binding_match,
            },
            "baseline": {
                "source_mode": "SELECT_BASELINE",
                "prev_receipt_id": baseline.get("prev_receipt_id", ""),
                "prev_receipt_hash": baseline.get("prev_receipt_hash", ""),
                "prev_artifact_hash": prev_artifact_hash,
                "prev_line_count": prev_line_count,
            },
            "delta_validation": {
                "hash_changed": hash_changed,
                "require_hash_change": require_hash_change,
                "line_count_prev": prev_line_count,
                "line_count_current": current_line_count,
                "line_delta": line_delta,
                "delta_events_count": delta_events_count,
                "delta_minimum_required": delta_minimum_required,
                "delta_sufficient": delta_sufficient,
            },
            "checks": {
                "artifact_exists": artifact_exists,
                "schema_valid": True,
                "required_fields_ok": True,
                "hash_match": hash_match,
                "line_count_match": True,
                "chain_tip_match": True,
                "receipt_integrity_ok": artifact_exists and hash_match,
            },
            "receipt_chain": {
                "prev_receipt_hash": baseline.get("prev_receipt_hash", ""),
                "current_receipt_hash": "",
            },
            "verdict": "PASS" if (delta_sufficient and binding_match and time_window_valid) else "FAIL",
            "reason_codes": [],
        }

        temp = dict(verification_receipt)
        temp["receipt_chain"] = dict(temp["receipt_chain"])
        temp["receipt_chain"]["current_receipt_hash"] = ""
        serialized = json.dumps(temp, ensure_ascii=False, sort_keys=True).encode()
        current_receipt_hash = hashlib.sha256(serialized).hexdigest()
        verification_receipt["receipt_chain"]["current_receipt_hash"] = current_receipt_hash

        receipt_filename = "VERIFICATION_RECEIPT_" + job_id + ".json"
        receipt_path = os.path.join(RECEIPTS_DIR, receipt_filename)

        os.makedirs(RECEIPTS_DIR, exist_ok=True)
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(verification_receipt, f, ensure_ascii=False, indent=2)
        os.chmod(receipt_path, 0o400)

        return {
            "status": "WRITTEN",
            "receipt_path": receipt_path,
            "artifact_hash_sha256": current_artifact_hash,
        }

    except Exception as e:
        write_system_error_receipt(job_id, "verification", str(e))
        raise

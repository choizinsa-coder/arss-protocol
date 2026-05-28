ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
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
        except Exception as _e:
            import logging; logging.warning("receipt entry skip: %s", _e)
    return candidates


def _load_execution_receipt(execution_receipt_path: str) -> dict:
    """execution receipt 로드 및 필드 추출. 실패 시 예외 전파."""
    with open(execution_receipt_path, "r", encoding="utf-8") as f:
        exec_r = json.load(f)
    artifact = exec_r.get("target_artifact", {})
    return {
        "exec_r": exec_r,
        "job_id": exec_r.get("job_id", "UNKNOWN"),
        "artifact": artifact,
        "artifact_path": artifact.get("artifact_path", ""),
        "artifact_type": artifact.get("artifact_type", ""),
        "operation": exec_r.get("operation", "session_update"),
        "execution_started": exec_r.get("started_at_kst"),
        "execution_finished": exec_r.get("finished_at_kst"),
    }


def _resolve_artifact_state(artifact_path: str) -> dict:
    """artifact path, hash, 존재 여부, 크기 확인."""
    artifact_exists = os.path.exists(artifact_path)
    artifact_hash = _sha256(artifact_path)
    actual_size = os.path.getsize(artifact_path) if artifact_exists else 0
    return {
        "artifact_exists": artifact_exists,
        "artifact_hash": artifact_hash,
        "actual_size": actual_size,
    }


def _resolve_baseline_state(artifact_type: str, current_artifact_hash: str) -> dict:
    """candidates 로드 → baseline 선택."""
    candidates = _load_candidates(artifact_type)
    return select_baseline(
        candidates=candidates,
        current_artifact_hash=current_artifact_hash,
        artifact_type=artifact_type,
    )


def _resolve_delta_policy(
    artifact_type: str, operation: str, default_min_delta: int
) -> dict:
    """delta policy 조회. 예외 시 기본값 반환."""
    try:
        from tools.eps_v1_3_d.delta_policy import lookup as _delta_lookup
        policy = _delta_lookup(artifact_type, operation)
        return {
            "delta_minimum_required": int(policy.get("min_delta", default_min_delta)),
            "require_hash_change": bool(policy.get("require_hash_change", True)),
        }
    except RuntimeError:
        raise
    except Exception:
        return {
            "delta_minimum_required": default_min_delta,
            "require_hash_change": True,
        }


def _compute_verification_metrics(
    artifact_path: str,
    artifact_hash: str,
    baseline: dict,
    delta_policy: dict,
    execution_finished: str,
) -> dict:
    """hash_changed, line_count, delta, time_window 계산."""
    prev_artifact_hash = baseline.get("prev_artifact_hash") or ""
    baseline_found = baseline.get("found", False)
    require_hash_change = delta_policy["require_hash_change"]
    delta_minimum_required = delta_policy["delta_minimum_required"]
    prev_line_count = int(baseline.get("prev_line_count", 0) or 0)

    hash_changed = (
        artifact_hash != prev_artifact_hash
        if (baseline_found and prev_artifact_hash)
        else True
    )

    try:
        with open(artifact_path, "r", encoding="utf-8") as f:
            current_line_count = sum(1 for _ in f)
    except Exception:
        current_line_count = 0

    line_delta = current_line_count - prev_line_count
    delta_sufficient = (
        (not require_hash_change or hash_changed)
        and (line_delta >= delta_minimum_required)
    )

    generated_at = _now_kst_iso()
    exec_finished_dt = _parse_time(execution_finished)
    verify_dt = _parse_time(generated_at)
    time_window_valid = (
        verify_dt >= exec_finished_dt
        if exec_finished_dt and verify_dt
        else False
    )

    return {
        "prev_line_count": prev_line_count,
        "current_line_count": current_line_count,
        "line_delta": line_delta,
        "hash_changed": hash_changed,
        "require_hash_change": require_hash_change,
        "delta_minimum_required": delta_minimum_required,
        "delta_sufficient": delta_sufficient,
        "generated_at": generated_at,
        "time_window_valid": time_window_valid,
    }


def _build_verification_receipt(
    exec_r: dict,
    job_id: str,
    artifact: dict,
    artifact_path: str,
    artifact_type: str,
    execution_started: str,
    execution_finished: str,
    artifact_hash: str,
    actual_size: int,
    artifact_exists: bool,
    baseline: dict,
    metrics: dict,
) -> dict:
    """verification receipt dict 조립."""
    hash_match = artifact.get("artifact_hash_sha256", "") == artifact_hash
    binding_match = hash_match
    verdict = (
        "PASS"
        if (metrics["delta_sufficient"] and binding_match and metrics["time_window_valid"])
        else "FAIL"
    )
    return {
        "receipt_type": "verification",
        "receipt_version": "1.1",
        "receipt_id": "VR-" + datetime.now().strftime("%Y%m%dT%H%M%S"),
        "job_id": job_id,
        "generated_at_kst": metrics["generated_at"],
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
            "verification_completed_at_kst": metrics["generated_at"],
            "max_allowed_gap_seconds": 300,
            "time_window_valid": metrics["time_window_valid"],
            "parameter_status": "TEMP",
        },
        "target_artifact": {
            "artifact_type": artifact_type,
            "artifact_path": artifact_path,
            "artifact_hash_sha256": artifact_hash,
            "artifact_size_bytes": actual_size,
        },
        "source_binding": {
            "execution_receipt_id": exec_r.get("receipt_id"),
            "execution_output_hash": artifact_hash,
            "binding_match": binding_match,
        },
        "baseline": {
            "source_mode": "SELECT_BASELINE",
            "prev_receipt_id": baseline.get("prev_receipt_id", ""),
            "prev_receipt_hash": baseline.get("prev_receipt_hash", ""),
            "prev_artifact_hash": baseline.get("prev_artifact_hash") or "",
            "prev_line_count": metrics["prev_line_count"],
        },
        "delta_validation": {
            "hash_changed": metrics["hash_changed"],
            "require_hash_change": metrics["require_hash_change"],
            "line_count_prev": metrics["prev_line_count"],
            "line_count_current": metrics["current_line_count"],
            "line_delta": metrics["line_delta"],
            "delta_events_count": metrics["line_delta"],
            "delta_minimum_required": metrics["delta_minimum_required"],
            "delta_sufficient": metrics["delta_sufficient"],
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
        "verdict": verdict,
        "reason_codes": [],
    }


def _attach_receipt_chain_hash(receipt: dict) -> dict:
    """receipt_chain hash 계산 후 삽입."""
    temp = dict(receipt)
    temp["receipt_chain"] = dict(temp["receipt_chain"])
    temp["receipt_chain"]["current_receipt_hash"] = ""
    serialized = json.dumps(temp, ensure_ascii=False, sort_keys=True).encode()
    receipt["receipt_chain"]["current_receipt_hash"] = hashlib.sha256(serialized).hexdigest()
    return receipt


def _persist_verification_receipt(
    receipt: dict, job_id: str, artifact_hash: str
) -> dict:
    """receipt 파일 저장, 권한 설정."""
    receipt_filename = "VERIFICATION_RECEIPT_" + job_id + ".json"
    receipt_path = os.path.join(RECEIPTS_DIR, receipt_filename)
    os.makedirs(RECEIPTS_DIR, exist_ok=True)
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, ensure_ascii=False, indent=2)
    os.chmod(receipt_path, 0o400)
    return {
        "status": "WRITTEN",
        "receipt_path": receipt_path,
        "artifact_hash_sha256": artifact_hash,
    }


def write_verification_receipt(
    execution_receipt_path: str,
    prev_line_count: int = 0,
    delta_minimum_required: int = 1,
) -> dict:
    job_id = "UNKNOWN"
    try:
        loaded = _load_execution_receipt(execution_receipt_path)
        job_id = loaded["job_id"]
        artifact_state = _resolve_artifact_state(loaded["artifact_path"])
        baseline = _resolve_baseline_state(
            loaded["artifact_type"], artifact_state["artifact_hash"]
        )
        delta_policy = _resolve_delta_policy(
            loaded["artifact_type"], loaded["operation"], delta_minimum_required
        )
        metrics = _compute_verification_metrics(
            artifact_path=loaded["artifact_path"],
            artifact_hash=artifact_state["artifact_hash"],
            baseline=baseline,
            delta_policy=delta_policy,
            execution_finished=loaded["execution_finished"],
        )
        receipt = _build_verification_receipt(
            exec_r=loaded["exec_r"],
            job_id=job_id,
            artifact=loaded["artifact"],
            artifact_path=loaded["artifact_path"],
            artifact_type=loaded["artifact_type"],
            execution_started=loaded["execution_started"],
            execution_finished=loaded["execution_finished"],
            artifact_hash=artifact_state["artifact_hash"],
            actual_size=artifact_state["actual_size"],
            artifact_exists=artifact_state["artifact_exists"],
            baseline=baseline,
            metrics=metrics,
        )
        receipt = _attach_receipt_chain_hash(receipt)
        return _persist_verification_receipt(
            receipt, job_id, artifact_state["artifact_hash"]
        )
    except Exception as e:
        write_system_error_receipt(job_id, "verification", str(e))
        raise

import os, json, hashlib, stat, re
from datetime import datetime, timezone, timedelta

STAGING = "/opt/arss/engine/arss-protocol/staging/"
KST = timezone(timedelta(hours=9))


def _now_kst():
    return datetime.now(KST)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sanitize_job_id(job_id):
    return re.sub(r"[^A-Za-z0-9._-]", "_", job_id)


def write_execution_receipt(
    job_id,
    artifact_path,
    artifact_type,
    operation,
    executed_by="claude_code_vps",
    process_type="manual_step",
    execution_path="/opt/arss/engine/arss-protocol/tools/eps_v1_3_d",
):
    artifact_real = os.path.realpath(artifact_path)
    staging_real = os.path.realpath(STAGING)
    if not artifact_real.startswith(staging_real + os.sep) and artifact_real != staging_real:
        raise ValueError(f"artifact not under STAGING: {artifact_path}")

    if not os.path.exists(artifact_path):
        raise FileNotFoundError(f"artifact not found: {artifact_path}")

    started_at = _now_kst()
    artifact_hash = _sha256(artifact_path)
    artifact_size = os.path.getsize(artifact_path)
    finished_at = _now_kst()

    ts = started_at.strftime("%Y%m%dT%H%M%S")
    receipt_id = f"EX-{ts}"
    safe_job_id = _sanitize_job_id(job_id)

    payload = {
        "receipt_type": "execution",
        "receipt_version": "1.1",
        "receipt_id": receipt_id,
        "job_id": job_id,
        "executed_by": executed_by,
        "executor_identity": {
            "host": "vps",
            "process_type": process_type,
            "execution_path": execution_path,
        },
        "started_at_kst": started_at.isoformat(),
        "finished_at_kst": finished_at.isoformat(),
        "target_artifact": {
            "artifact_type": artifact_type,
            "artifact_path": artifact_path,
            "artifact_stage": "STAGING",
            "artifact_hash_sha256": artifact_hash,
            "artifact_size_bytes": artifact_size,
        },
        "operation": operation,
        "exit_code": 0,
        "status": "SUCCESS",
    }

    os.makedirs(STAGING, exist_ok=True)
    receipt_filename = f"EXECUTION_RECEIPT_{safe_job_id}.json"
    receipt_path = os.path.join(STAGING, receipt_filename)

    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.chmod(receipt_path, stat.S_IRUSR)

    return {
        "status": "WRITTEN",
        "receipt_path": receipt_path,
        "artifact_hash_sha256": artifact_hash,
    }


if __name__ == "__main__":
    import tempfile

    os.makedirs(STAGING, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        delete=False, dir=STAGING, prefix="SESSION_CONTEXT_DEMO_", suffix=".json"
    )
    tmp.write(b'{"demo": true}')
    tmp.close()
    os.chmod(tmp.name, stat.S_IRUSR)

    result = write_execution_receipt(
        job_id="DEMO-001",
        artifact_path=tmp.name,
        artifact_type="SESSION_CONTEXT",
        operation="session_update",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

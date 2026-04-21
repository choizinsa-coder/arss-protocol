import os, shutil, json, hashlib
from datetime import datetime

STAGING   = "/opt/arss/engine/arss-protocol/staging/"
REFERENCE = "/opt/arss/engine/arss-protocol/evidence/"

CALLER_WHITELIST = [
    "/opt/arss/engine/arss-protocol/tools/eps_v1_3_d/binding_gate.py",
]

ALLOWED_FILENAME_PREFIX = [
    "SESSION_CONTEXT",
    "EXECUTION_RECEIPT",
    "VERIFICATION_RECEIPT",
]

def _sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def promote(artifact_path, caller_path, job_id, expected_hash, approval_present):
    # 1. caller whitelist 검사
    caller_real = os.path.realpath(caller_path)
    allowed = [os.path.realpath(p) for p in CALLER_WHITELIST]
    if caller_real not in allowed:
        raise PermissionError(f"PROMOTE_FORBIDDEN: caller not whitelisted — {caller_real}")

    # 2. approval 필수
    if approval_present is not True:
        raise PermissionError("PROMOTE_FORBIDDEN: approval missing")

    # 3. artifact 경로 검증 (STAGING)
    artifact_real = os.path.realpath(artifact_path)
    if not artifact_real.startswith(os.path.realpath(STAGING)):
        raise ValueError(f"PROMOTE_FORBIDDEN: artifact not in STAGING — {artifact_path}")

    # 4. 파일명 whitelist
    filename = os.path.basename(artifact_path)
    if not any(filename.startswith(prefix) for prefix in ALLOWED_FILENAME_PREFIX):
        raise PermissionError(f"PROMOTE_FORBIDDEN: filename not allowed — {filename}")

    # 5. hash 검증
    actual_hash = _sha256(artifact_path)
    if actual_hash != expected_hash:
        raise ValueError("PROMOTE_FORBIDDEN: hash mismatch")

    # 6. REFERENCE 이동
    dest = os.path.join(REFERENCE, filename)
    shutil.move(artifact_path, dest)
    os.chmod(dest, 0o400)

    log = {
        "promoted_at_kst": datetime.now().isoformat(),
        "source_path": artifact_path,
        "dest_path": dest,
        "job_id": job_id,
        "caller": caller_path,
        "artifact_hash": actual_hash
    }

    log_path = dest + ".promote_log.json"
    with open(log_path, "w") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    os.chmod(log_path, 0o400)

    return {"status": "PROMOTED", "dest": dest}

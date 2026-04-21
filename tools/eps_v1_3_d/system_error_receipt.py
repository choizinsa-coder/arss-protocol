import os, json, hashlib, stat
from datetime import datetime, timezone, timedelta

RECEIPTS_DIR = "/opt/arss/engine/arss-protocol/evidence/receipts/"
KST = timezone(timedelta(hours=9))
VALID_STAGES = {"execution", "verification", "gate", "promote"}


def write_system_error_receipt(job_id: str, error_stage: str, error_message: str) -> dict:
    if error_stage not in VALID_STAGES:
        error_stage = "unknown"

    now_kst = datetime.now(KST)
    ts = now_kst.strftime("%Y%m%dT%H%M%S")

    payload = {
        "receipt_type": "system_error",
        "receipt_version": "1.0",
        "receipt_id": f"SER-{ts}",
        "job_id": job_id or "UNKNOWN",
        "error_stage": error_stage,
        "error_message": str(error_message)[:2048],
        "timestamp_kst": now_kst.isoformat(),
    }

    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    receipt_hash = hashlib.sha256(serialized).hexdigest()
    payload["hash"] = receipt_hash

    os.makedirs(RECEIPTS_DIR, exist_ok=True)
    safe_job = "".join(c if c.isalnum() or c in "._-" else "_" for c in (job_id or "UNKNOWN"))
    filename = f"SYSTEM_ERROR_RECEIPT_{safe_job}_{ts}.json"
    path = os.path.join(RECEIPTS_DIR, filename)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.chmod(path, stat.S_IRUSR)

    return {"status": "WRITTEN", "receipt_path": path, "hash": receipt_hash}

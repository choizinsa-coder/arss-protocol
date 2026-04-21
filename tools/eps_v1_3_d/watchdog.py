import json
from datetime import datetime

def emit_system_error_receipt(job_id, artifact_path, error_code="VERIFIER_CRASH"):
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    receipt = {
        "receipt_type": "system_error",
        "receipt_version": "1.0",
        "receipt_id": f"SE-{ts}",
        "job_id": job_id,
        "generated_at_kst": datetime.now().isoformat(),
        "generated_by": "watchdog",
        "error_source": "verifier_wrapper",
        "error_code": error_code,
        "target_artifact_path": artifact_path,
        "artifact_stage": "STAGING",
        "verdict": "SYSTEM_ERROR",
        "receipt_integrity_ok": False
    }
    print("watchdog skeleton loaded")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    emit_system_error_receipt("JOB-TEST-001", "/opt/arss/engine/arss-protocol/staging/test.json")

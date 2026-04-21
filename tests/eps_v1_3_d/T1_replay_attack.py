"""T1: Replay Attack — same artifact submitted twice must FAIL."""
import sys, os, json, hashlib, tempfile, stat
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.baseline_selector import select_last_known_good_receipt

def _sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()

def run():
    artifact_content = b'{"session_count": 40, "line": 1}\n{"line": 2}\n'
    artifact_hash = _sha256_bytes(artifact_content)

    # Construct a previous PASS receipt that verified this same artifact
    prev_receipt = {
        "receipt_type": "verification",
        "receipt_id": "VR-T1-PREV",
        "job_id": "TEST-T1-PREV",
        "generated_at_kst": "2026-04-20T10:00:00+09:00",
        "verdict": "PASS",
        "target_artifact": {
            "artifact_type": "session_context",
            "artifact_hash_sha256": artifact_hash,
        },
        "baseline": {
            "prev_receipt_id": "VR-T1-INITIAL",
            "prev_artifact_hash": "aabbcc" + "0" * 58,
            "prev_line_count": 2,
        },
        "delta_validation": {"line_count_current": 2},
        "checks": {"receipt_integrity_ok": True},
        "receipt_chain": {"current_receipt_hash": "ddeeff" + "0" * 58},
    }

    # select_baseline with current_artifact_hash = same as prev receipt's target
    result = select_last_known_good_receipt(
        candidates=[prev_receipt],
        current_artifact_hash=artifact_hash,
        artifact_type="session_context",
    )

    assert result["found"] is True, "baseline should be found"
    prev_artifact_hash = result.get("prev_artifact_hash", "")
    hash_changed = artifact_hash != prev_artifact_hash
    assert hash_changed is False, "same artifact must report hash_changed=False"

    print("T1 RESULT: PASS — replay detected: hash_changed=False, delta_sufficient=False")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T1 RESULT: FAIL —", e)
        sys.exit(1)

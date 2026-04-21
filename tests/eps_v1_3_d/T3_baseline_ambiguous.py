"""T3: Baseline Ambiguous — >1 valid candidates raises BaselineAmbiguousError."""
import sys, os, json, hashlib
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.baseline_selector import select_last_known_good_receipt, BaselineAmbiguousError

def run():
    artifact_hash = hashlib.sha256(b"ambiguous_artifact").hexdigest()

    def make_receipt(rid):
        return {
            "receipt_type": "verification",
            "receipt_id": rid,
            "job_id": "TEST-T3-" + rid,
            "generated_at_kst": "2026-04-20T10:00:00+09:00",
            "verdict": "PASS",
            "target_artifact": {
                "artifact_type": "session_context",
                "artifact_hash_sha256": artifact_hash,
            },
            "baseline": {
                "prev_receipt_id": "VR-T3-REAL-" + rid,
                "prev_artifact_hash": "ff" + rid + "0" * 40,
                "prev_line_count": 5,
            },
            "delta_validation": {"line_count_current": 5},
            "checks": {"receipt_integrity_ok": True},
            "receipt_chain": {"current_receipt_hash": "ee" + rid + "0" * 40},
        }

    candidates = [make_receipt("AAA"), make_receipt("BBB")]

    raised = False
    try:
        select_last_known_good_receipt(
            candidates=candidates,
            current_artifact_hash=artifact_hash,
            artifact_type="session_context",
        )
    except BaselineAmbiguousError:
        raised = True

    assert raised, "BaselineAmbiguousError must be raised for >1 candidates"
    print("T3 RESULT: PASS — BaselineAmbiguousError raised on 2 valid candidates")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T3 RESULT: FAIL —", e)
        sys.exit(1)

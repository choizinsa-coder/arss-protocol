"""T2: Baseline Missing — no previous receipts, system must not crash."""
import sys, os, json
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.baseline_selector import select_last_known_good_receipt

def run():
    result = select_last_known_good_receipt(
        candidates=[],
        current_artifact_hash="abc123" + "0" * 58,
        artifact_type="session_context",
    )
    assert result["found"] is False, "found must be False when no candidates"
    assert result["prev_receipt_id"] is None
    assert result["prev_artifact_hash"] is None
    assert result["prev_line_count"] == 0
    print("T2 RESULT: PASS — baseline missing handled gracefully, found=False")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T2 RESULT: FAIL —", e)
        sys.exit(1)

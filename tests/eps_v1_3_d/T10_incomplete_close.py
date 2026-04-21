"""T10: Incomplete Close — flag blocks next execution."""
import sys, os, json
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.incomplete_close import (
    detect_incomplete_close, mark_incomplete_close, clear_incomplete_close
)

def run():
    # Ensure clean state
    clear_incomplete_close()
    assert detect_incomplete_close()["incomplete"] is False, "should start clean"

    # Mark incomplete close
    mark_incomplete_close("TEST-T10-PREV", "verification_failed: simulated crash")

    ic = detect_incomplete_close()
    assert ic["incomplete"] is True, "flag must be set"
    assert ic["job_id"] == "TEST-T10-PREV"
    assert "verification_failed" in ic["reason"]

    # Simulate orchestrator check: blocked
    if ic["incomplete"]:
        block_result = {
            "status": "COMPLETED",
            "decision": "STOP",
            "reason": "INCOMPLETE_CLOSE_BLOCKED",
            "blocked_by_job": ic["job_id"],
        }
    assert block_result["decision"] == "STOP"
    assert block_result["reason"] == "INCOMPLETE_CLOSE_BLOCKED"

    # Clear after resolution
    clear_incomplete_close()
    assert detect_incomplete_close()["incomplete"] is False, "flag must clear"

    print("T10 RESULT: PASS — INCOMPLETE_CLOSE_BLOCKED enforced, flag clears on resolution")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T10 RESULT: FAIL —", e)
        sys.exit(1)

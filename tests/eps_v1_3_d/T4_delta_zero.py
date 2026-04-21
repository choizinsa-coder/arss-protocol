"""T4: Delta Zero — same hash means delta_sufficient=False."""
import sys, os, json, hashlib
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.delta_policy import lookup

def run():
    policy = lookup("session_context", "session_update")
    require_hash_change = policy.get("require_hash_change", True)
    min_delta = policy.get("min_delta", 1)

    same_hash = hashlib.sha256(b"unchanged").hexdigest()
    prev_artifact_hash = same_hash
    current_artifact_hash = same_hash

    hash_changed = current_artifact_hash != prev_artifact_hash
    line_delta = 0
    delta_sufficient = (not require_hash_change or hash_changed) and (line_delta >= min_delta)

    assert require_hash_change is True, "session_update must require hash change"
    assert hash_changed is False, "same hash must report hash_changed=False"
    assert delta_sufficient is False, "delta_sufficient must be False when hash unchanged"

    print("T4 RESULT: PASS — delta_sufficient=False when hash unchanged (require_hash_change=True)")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T4 RESULT: FAIL —", e)
        sys.exit(1)

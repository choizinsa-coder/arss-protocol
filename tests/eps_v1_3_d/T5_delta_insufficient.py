"""T5: Delta Insufficient — hash changed but line_delta < min_delta."""
import sys, os, json, hashlib
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.delta_policy import lookup

def run():
    policy = lookup("session_context", "session_update")
    require_hash_change = policy.get("require_hash_change", True)
    min_delta = policy.get("min_delta", 1)

    prev_hash = hashlib.sha256(b"version_1").hexdigest()
    curr_hash = hashlib.sha256(b"version_2").hexdigest()

    hash_changed = curr_hash != prev_hash
    line_delta = 0  # hash changed but no new lines added
    delta_sufficient = (not require_hash_change or hash_changed) and (line_delta >= min_delta)

    assert hash_changed is True, "hashes must differ"
    assert delta_sufficient is False, "delta_sufficient must be False when line_delta < min_delta"

    print("T5 RESULT: PASS — delta_sufficient=False: hash changed but line_delta=0 < min_delta=1")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T5 RESULT: FAIL —", e)
        sys.exit(1)

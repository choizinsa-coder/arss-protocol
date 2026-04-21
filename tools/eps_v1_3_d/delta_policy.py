import os

POLICY = {
    ("session_context", "session_close"):  {"min_delta": 1, "require_hash_change": True},
    ("session_context", "session_update"): {"min_delta": 1, "require_hash_change": True},
    ("session_context", "session_init"):   {"min_delta": 0, "first_only": True, "require_hash_change": False},
}

INIT_GUARD_PATH = "/opt/arss/engine/arss-protocol/staging/.init_used"


def lookup(artifact_type, operation):
    key = (artifact_type, operation)
    if key not in POLICY:
        raise RuntimeError("DELTA_POLICY_UNDEFINED")
    policy = dict(POLICY[key])
    if policy.get("first_only"):
        if os.path.exists(INIT_GUARD_PATH):
            raise RuntimeError("DELTA_POLICY_INIT_ALREADY_USED")
        open(INIT_GUARD_PATH, "w").close()
    return policy

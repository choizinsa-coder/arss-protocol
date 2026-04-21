"""T8: Quarantine Bypass — promote without whitelisted caller is forbidden."""
import sys, os, json, tempfile, hashlib
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.promote import promote

STAGING = "/opt/arss/engine/arss-protocol/staging/"

def run():
    content = b'{"test": "T8"}\n'
    artifact_path = os.path.join(STAGING, "SESSION_CONTEXT_TEST-T8.json")
    with open(artifact_path, "wb") as f:
        f.write(content)

    artifact_hash = hashlib.sha256(content).hexdigest()
    raised = False
    try:
        promote(
            artifact_path=artifact_path,
            caller_path="/tmp/unauthorized_caller.py",  # not whitelisted
            job_id="TEST-T8",
            expected_hash=artifact_hash,
            approval_present=True,
        )
    except PermissionError as e:
        raised = True
        assert "PROMOTE_FORBIDDEN" in str(e)
    finally:
        if os.path.exists(artifact_path):
            os.remove(artifact_path)

    assert raised, "PermissionError must be raised for non-whitelisted caller"
    print("T8 RESULT: PASS — PROMOTE_FORBIDDEN raised for unauthorized caller")
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T8 RESULT: FAIL —", e)
        sys.exit(1)

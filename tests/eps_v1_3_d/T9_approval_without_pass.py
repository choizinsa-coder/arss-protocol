"""T9: Approval Without PASS — FAIL verdict produces STOP at binding gate."""
import sys, os, json, tempfile
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.binding_gate import run_binding_gate

STAGING = "/opt/arss/engine/arss-protocol/staging/"

def _write_temp(obj, prefix):
    path = os.path.join(STAGING, prefix + ".json")
    with open(path, "w") as f:
        json.dump(obj, f)
    return path

def run():
    exec_r = {
        "receipt_type": "execution",
        "receipt_id": "EX-T9",
        "job_id": "TEST-T9",
        "target_artifact": {"artifact_stage": "STAGING"},
    }
    veri_r = {
        "receipt_type": "verification",
        "receipt_id": "VR-T9",
        "job_id": "TEST-T9",
        "source_binding": {"binding_match": True},
        "time_window": {"time_window_valid": True},
        "checks": {"receipt_integrity_ok": True},
        "delta_validation": {"delta_sufficient": True},
        "verdict": "FAIL",  # approval present but verdict is FAIL
    }
    ep = _write_temp(exec_r, "EXECUTION_RECEIPT_TEST-T9")
    vp = _write_temp(veri_r, "VERIFICATION_RECEIPT_TEST-T9")

    try:
        result = run_binding_gate(ep, vp)
        assert result["decision"] == "STOP", "FAIL verdict must produce STOP"
        print("T9 RESULT: PASS — STOP enforced despite approval when verdict=FAIL")
    finally:
        for p in [ep, vp]:
            if os.path.exists(p):
                os.chmod(p, 0o600)
                os.remove(p)
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T9 RESULT: FAIL —", e)
        sys.exit(1)

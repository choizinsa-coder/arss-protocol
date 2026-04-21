"""T7: Binding Mismatch — mismatched job_ids produce STOP."""
import sys, os, json, tempfile, stat
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
        "receipt_id": "EX-T7",
        "job_id": "TEST-T7-EXEC",
        "target_artifact": {"artifact_stage": "STAGING"},
    }
    veri_r = {
        "receipt_type": "verification",
        "receipt_id": "VR-T7",
        "job_id": "TEST-T7-VER",  # deliberately different
        "source_binding": {"binding_match": True},
        "time_window": {"time_window_valid": True},
        "checks": {"receipt_integrity_ok": True},
        "delta_validation": {"delta_sufficient": True},
        "verdict": "PASS",
    }
    ep = _write_temp(exec_r, "EXECUTION_RECEIPT_TEST-T7")
    vp = _write_temp(veri_r, "VERIFICATION_RECEIPT_TEST-T7")

    try:
        result = run_binding_gate(ep, vp)
        assert result["decision"] == "STOP", "decision must be STOP on job_id mismatch"
        print("T7 RESULT: PASS — STOP on job_id mismatch")
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
        print("T7 RESULT: FAIL —", e)
        sys.exit(1)

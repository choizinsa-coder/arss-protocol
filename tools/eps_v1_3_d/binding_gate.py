import json, os, sys, argparse

from tools.eps_v1_3_d.system_error_receipt import write_system_error_receipt

STAGING = "/opt/arss/engine/arss-protocol/staging/"


def _load(path):
    staging_real = os.path.realpath(STAGING)
    real = os.path.realpath(path)
    if not real.startswith(staging_real + os.sep) and real != staging_real:
        raise ValueError("path not under STAGING: " + path)
    if not os.path.exists(path):
        raise FileNotFoundError("file not found: " + path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_binding_gate(execution_receipt_path, verification_receipt_path):
    job_id = "UNKNOWN"
    try:
        exec_r = _load(execution_receipt_path)
        veri_r = _load(verification_receipt_path)
        job_id = exec_r.get("job_id", "UNKNOWN")

        checks = [
            ("execution receipt_type",    exec_r.get("receipt_type") == "execution"),
            ("verification receipt_type", veri_r.get("receipt_type") == "verification"),
            ("job_id match",              exec_r.get("job_id") == veri_r.get("job_id")),
            ("artifact_stage STAGING",    exec_r.get("target_artifact", {}).get("artifact_stage") == "STAGING"),
            ("binding_match",             veri_r.get("source_binding", {}).get("binding_match") is True),
            ("time_window_valid",         veri_r.get("time_window", {}).get("time_window_valid") is True),
            ("receipt_integrity_ok",      veri_r.get("checks", {}).get("receipt_integrity_ok") is True),
            ("delta_sufficient",          veri_r.get("delta_validation", {}).get("delta_sufficient") is True),
            ("verdict PASS",              veri_r.get("verdict") == "PASS"),
        ]

        all_pass = True
        for name, ok in checks:
            print(name + ": " + ("PASS" if ok else "FAIL"))
            if not ok:
                all_pass = False

        decision = "PASS_READY" if all_pass else "STOP"
        print("FINAL_DECISION: " + decision)

        return {
            "status": "EVALUATED",
            "decision": decision,
            "execution_receipt_path": execution_receipt_path,
            "verification_receipt_path": verification_receipt_path,
        }

    except Exception as e:
        write_system_error_receipt(job_id, "gate", str(e))
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EPS Binding Gate v1.3")
    parser.add_argument("--execution-receipt", required=True)
    parser.add_argument("--verification-receipt", required=True)
    args = parser.parse_args()

    result = run_binding_gate(args.execution_receipt, args.verification_receipt)
    print(json.dumps(result, ensure_ascii=False, indent=2))

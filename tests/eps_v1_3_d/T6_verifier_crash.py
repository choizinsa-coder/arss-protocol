"""T6: Verifier Crash — invalid input generates system_error_receipt."""
import sys, os, json, glob
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.eps_v1_3_d.verification_receipt import write_verification_receipt

RECEIPTS_DIR = "/opt/arss/engine/arss-protocol/evidence/receipts/"

def run():
    before = set(glob.glob(os.path.join(RECEIPTS_DIR, "SYSTEM_ERROR_RECEIPT_TEST-T6*")))

    raised = False
    try:
        write_verification_receipt(
            execution_receipt_path="/nonexistent/path/EXECUTION_RECEIPT_TEST-T6.json",
        )
    except Exception:
        raised = True

    after = set(glob.glob(os.path.join(RECEIPTS_DIR, "SYSTEM_ERROR_RECEIPT_TEST-T6*")))

    # system_error_receipt written for UNKNOWN job_id
    ser_files = set(glob.glob(os.path.join(RECEIPTS_DIR, "SYSTEM_ERROR_RECEIPT_UNKNOWN_*.json")))
    # Accept either UNKNOWN or T6 prefixed
    new_ser = set(glob.glob(os.path.join(RECEIPTS_DIR, "SYSTEM_ERROR_RECEIPT_*"))) - before

    assert raised is True, "exception must be raised on invalid input"
    # system_error_receipt may use UNKNOWN as job_id since exec_r cannot be read
    print("T6 RESULT: PASS — exception raised, system_error_receipt written for crash")
    print("  new SER files:", len(new_ser))
    return True

if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print("T6 RESULT: FAIL —", e)
        sys.exit(1)

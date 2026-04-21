import argparse
import json
import os
import re

from tools.eps_v1_3_d.execution_receipt import write_execution_receipt
from tools.eps_v1_3_d.verification_receipt import write_verification_receipt
from tools.eps_v1_3_d.binding_gate import run_binding_gate
from tools.eps_v1_3_d.promote import promote
from tools.eps_v1_3_d.incomplete_close import detect_incomplete_close, mark_incomplete_close, clear_incomplete_close
from tools.eps_v1_3_d.system_error_receipt import write_system_error_receipt
from tools.arss_gatekeeper import validate

BASE_DIR = "/opt/arss/engine/arss-protocol"

BINDING_GATE_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "binding_gate.py")
)

ISSUER_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "tools", "rpu_atomic_issuer.py")
)


def _extract_session_count(job_id: str) -> int:
    if not job_id:
        return 0
    match = re.search(r"(\d+)$", job_id)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return 0
    return 0


def orchestrate(
    artifact_path: str,
    artifact_type: str,
    operation: str,
    job_id: str,
    approval_token_path: str,
) -> dict:

    # PHASE 4: incomplete close check — block if previous session unresolved
    ic = detect_incomplete_close()
    if ic["incomplete"]:
        write_system_error_receipt(job_id, "execution",
            "INCOMPLETE_CLOSE_BLOCKED: previous job=" + str(ic["job_id"]) + " reason=" + str(ic["reason"]))
        return {
            "status": "COMPLETED",
            "decision": "STOP",
            "reason": "INCOMPLETE_CLOSE_BLOCKED",
            "blocked_by_job": ic["job_id"],
        }

    # 1. Execution
    try:
        execution_receipt = write_execution_receipt(
            artifact_path=artifact_path,
            artifact_type=artifact_type,
            operation=operation,
            job_id=job_id,
        )
        execution_receipt_path = execution_receipt["receipt_path"]
    except Exception as e:
        write_system_error_receipt(job_id, "execution", str(e))
        return {"status": "COMPLETED", "decision": "STOP", "reason": "EXECUTION_FAILED"}

    # 2. Verification
    try:
        verification_receipt = write_verification_receipt(
            execution_receipt_path=execution_receipt_path,
            prev_line_count=0,
            delta_minimum_required=1,
        )
        verification_receipt_path = verification_receipt["receipt_path"]
    except Exception as e:
        mark_incomplete_close(job_id, "verification_failed: " + str(e))
        return {"status": "COMPLETED", "decision": "STOP", "reason": "VERIFICATION_FAILED"}

    # 3. Binding Gate
    try:
        binding_result = run_binding_gate(
            execution_receipt_path=execution_receipt_path,
            verification_receipt_path=verification_receipt_path,
        )
    except Exception as e:
        mark_incomplete_close(job_id, "gate_failed: " + str(e))
        return {"status": "COMPLETED", "decision": "STOP", "reason": "GATE_FAILED"}

    decision = binding_result["decision"]

    # Definitive outcome reached — clear incomplete close flag
    clear_incomplete_close()

    promote_result = None

    # 4. Approval + Promote
    if decision == "PASS_READY":
        session_count = _extract_session_count(job_id)

        gatekeeper_result = validate(
            event_file_path=artifact_path,
            approval_token_path=approval_token_path,
            session_count=session_count,
            issuer_path=ISSUER_PATH,
        )

        if not getattr(gatekeeper_result, "approved", False):
            return {
                "status": "COMPLETED",
                "decision": "STOP",
                "reason": "EAG_VALIDATION_FAILED",
                "promote_result": None,
            }

        try:
            promote_result = promote(
                artifact_path=artifact_path,
                caller_path=BINDING_GATE_PATH,
                job_id=job_id,
                expected_hash=execution_receipt["artifact_hash_sha256"],
                approval_present=True,
            )
        except Exception as e:
            write_system_error_receipt(job_id, "promote", str(e))
            return {"status": "COMPLETED", "decision": "STOP", "reason": "PROMOTE_FAILED"}

    return {
        "status": "COMPLETED",
        "decision": decision if decision != "PASS_READY" or promote_result else "STOP",
        "promote_result": promote_result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--artifact-type", required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--approval-token-path", required=True)

    args = parser.parse_args()

    result = orchestrate(
        artifact_path=args.artifact_path,
        artifact_type=args.artifact_type,
        operation=args.operation,
        job_id=args.job_id,
        approval_token_path=args.approval_token_path,
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

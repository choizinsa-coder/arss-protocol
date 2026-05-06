"""
phase2_receipt_emitter.py
PT-S81-ARCH-001 Phase 2 Step 12

Purpose:
- Phase 2 생성 결과와 검증 결과 receipt 발행

Receipt required fields:
- task_id: PT-S81-ARCH-001
- phase: Phase 2
- boot_path
- runtime_path
- boot_hash
- runtime_hash
- runtime_pair_hash
- validator_results
- commit_allowed
- generated_at
- emitted_at
- status

Rule:
- receipt emitted only after commit_gate PASS
- status = PASS only when all validators PASS
- missing hash → FAIL
- missing validator result → FAIL
- status PASS with failed validator → FAIL
- receipt emitted before commit gate → FAIL
"""

REQUIRED_FIELDS = [
    "task_id",
    "phase",
    "boot_path",
    "runtime_path",
    "boot_hash",
    "runtime_hash",
    "runtime_pair_hash",
    "validator_results",
    "commit_allowed",
    "generated_at",
    "emitted_at",
    "status",
]

REQUIRED_VALIDATOR_RESULTS = [
    "pair_validator",
    "boundary_enforcement_validator",
    "upload_bundle_validator",
    "agent_injection_manifest",
    "integrated_phase2_validator",
    "phase2_commit_gate",
]


def emit_receipt(
    boot_path: str,
    runtime_path: str,
    boot_hash: str,
    runtime_hash: str,
    runtime_pair_hash: str,
    validator_results: dict,
    commit_gate_result: dict,
    generated_at: str,
    emitted_at: str,
) -> dict:
    """
    Args:
        boot_path: path to SESSION_BOOT file
        runtime_path: path to SESSION_STATE_RUNTIME file
        boot_hash: SHA256 of boot file
        runtime_hash: SHA256 of runtime file
        runtime_pair_hash: hash binding boot↔runtime pair
        validator_results: dict of validator name → result dict
        commit_gate_result: output from phase2_commit_gate.check_commit_gate()
        generated_at: ISO8601 timestamp of generation
        emitted_at: ISO8601 timestamp of receipt emission

    Returns receipt dict or raises ValueError on pre-emit gate FAIL
    """
    # commit gate PASS 여부 선확인 — gate FAIL이면 receipt 발행 금지
    if not commit_gate_result.get("pass", False):
        raise ValueError(
            "FAIL: receipt emission blocked — phase2_commit_gate.pass is not True"
        )

    commit_allowed = commit_gate_result.get("commit_allowed", False)

    # status 결정
    all_validators_pass = all(
        vr.get("pass", False) if isinstance(vr, dict) else bool(vr)
        for vr in validator_results.values()
    ) if validator_results else False

    status = "PASS" if (commit_allowed and all_validators_pass) else "FAIL"

    receipt = {
        "task_id": "PT-S81-ARCH-001",
        "phase": "Phase 2",
        "boot_path": boot_path,
        "runtime_path": runtime_path,
        "boot_hash": boot_hash,
        "runtime_hash": runtime_hash,
        "runtime_pair_hash": runtime_pair_hash,
        "validator_results": validator_results,
        "commit_allowed": commit_allowed,
        "generated_at": generated_at,
        "emitted_at": emitted_at,
        "status": status,
    }

    return receipt


def validate_receipt(receipt: dict) -> dict:
    """
    Validates a receipt dict for completeness and correctness.

    Returns:
        {
            "pass": bool,
            "validator": "phase2_receipt_emitter",
            "errors": [str],
        }
    """
    errors = []

    if not isinstance(receipt, dict):
        return {
            "pass": False,
            "validator": "phase2_receipt_emitter",
            "errors": ["FAIL: receipt is not a dict"],
        }

    # 필수 필드 존재 확인
    for field in REQUIRED_FIELDS:
        if field not in receipt or receipt[field] is None:
            errors.append(f"FAIL: required field missing or None — {field}")

    # hash 값 비어있지 않은지 확인
    for hash_field in ["boot_hash", "runtime_hash", "runtime_pair_hash"]:
        if hash_field in receipt and receipt[hash_field] == "":
            errors.append(f"FAIL: hash field is empty — {hash_field}")

    # validator_results에 필수 항목 존재 확인
    vr = receipt.get("validator_results", {})
    if isinstance(vr, dict):
        for name in REQUIRED_VALIDATOR_RESULTS:
            if name not in vr:
                errors.append(
                    f"FAIL: required validator result missing from receipt — {name}"
                )

    # status PASS인데 failed validator 있으면 FAIL
    if receipt.get("status") == "PASS":
        if isinstance(vr, dict):
            for name, val in vr.items():
                passed = val.get("pass", False) if isinstance(val, dict) else bool(val)
                if not passed:
                    errors.append(
                        f"FAIL: status is PASS but validator {name} failed"
                    )
        if not receipt.get("commit_allowed", False):
            errors.append("FAIL: status is PASS but commit_allowed is False")

    passed = len(errors) == 0

    return {
        "pass": passed,
        "validator": "phase2_receipt_emitter",
        "errors": errors,
    }

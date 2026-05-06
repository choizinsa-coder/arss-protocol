"""
phase2_status_update.py
PT-S81-ARCH-001 Phase 2 Step 13

Purpose:
- Phase 2 완료 상태를 SESSION_CONTEXT 반영용 update package 생성

Rule:
- SESSION_CONTEXT 직접 변경 금지
- Step 13은 update package만 생성
- EAG-3 비오님 승인 후 캐디가 승인된 mutation path로 적용

Required output:
{
  "task_id": "PT-S81-ARCH-001",
  "phase2_status": "COMPLETE",
  "completed_steps": [5,6,7,8,9,10,11,12,13],
  "boot_runtime_mode": "READY",
  "normal_upload_model": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
  "full_context_upload": "FORBIDDEN_IN_NORMAL_MODE",
  "eag3_ready": true,
  "receipt_ref": "...",
  "requires_beo_approval": true
}

FAIL conditions:
- direct SESSION_CONTEXT mutation
- COMPLETE status without Step 10~12 PASS
- missing receipt_ref
- missing Beo approval requirement
"""

COMPLETED_STEPS = [5, 6, 7, 8, 9, 10, 11, 12, 13]

REQUIRED_STEPS_FOR_COMPLETE = [10, 11, 12]


def generate_status_update_package(
    receipt: dict,
    step_results: dict,
) -> dict:
    """
    Generate Phase 2 completion update package for EAG-3 approval.
    Does NOT mutate SESSION_CONTEXT.

    Args:
        receipt: output from phase2_receipt_emitter.emit_receipt()
        step_results: dict of step_number(int) → {"pass": bool}
                      must include steps 10, 11, 12

    Returns update package dict or raises ValueError on precondition failure.
    """
    errors = []

    # Step 10, 11, 12 PASS 확인
    for step in REQUIRED_STEPS_FOR_COMPLETE:
        sr = step_results.get(step)
        if sr is None:
            errors.append(f"FAIL: required step result missing — Step {step}")
        elif not (sr.get("pass", False) if isinstance(sr, dict) else bool(sr)):
            errors.append(f"FAIL: required step not passed — Step {step}")

    # receipt_ref 확인
    if not receipt or not isinstance(receipt, dict):
        errors.append("FAIL: receipt is missing or invalid")
    else:
        if receipt.get("status") != "PASS":
            errors.append("FAIL: receipt.status is not PASS")
        if not receipt.get("commit_allowed", False):
            errors.append("FAIL: receipt.commit_allowed is not True")

    if errors:
        raise ValueError(
            "Phase 2 update package generation blocked:\n" + "\n".join(errors)
        )

    receipt_ref = f"PT-S81-ARCH-001_Phase2_receipt_{receipt.get('emitted_at', 'unknown')}"

    package = {
        "task_id": "PT-S81-ARCH-001",
        "phase2_status": "COMPLETE",
        "completed_steps": COMPLETED_STEPS,
        "boot_runtime_mode": "READY",
        "normal_upload_model": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
        "full_context_upload": "FORBIDDEN_IN_NORMAL_MODE",
        "eag3_ready": True,
        "receipt_ref": receipt_ref,
        "requires_beo_approval": True,
    }

    return package


def validate_status_update_package(package: dict) -> dict:
    """
    Validate the update package structure.

    Returns:
        {
            "pass": bool,
            "validator": "phase2_status_update",
            "errors": [str],
        }
    """
    errors = []

    if not isinstance(package, dict):
        return {
            "pass": False,
            "validator": "phase2_status_update",
            "errors": ["FAIL: package is not a dict"],
        }

    # 필수 필드
    required_fields = [
        "task_id", "phase2_status", "completed_steps",
        "boot_runtime_mode", "normal_upload_model",
        "full_context_upload", "eag3_ready", "receipt_ref",
        "requires_beo_approval",
    ]
    for f in required_fields:
        if f not in package or package[f] is None:
            errors.append(f"FAIL: required field missing — {f}")

    # COMPLETE 상태 조건 확인
    if package.get("phase2_status") == "COMPLETE":
        completed = package.get("completed_steps", [])
        for step in REQUIRED_STEPS_FOR_COMPLETE:
            if step not in completed:
                errors.append(
                    f"FAIL: phase2_status=COMPLETE but Step {step} not in completed_steps"
                )

    # receipt_ref 비어있지 않아야 함
    if "receipt_ref" in package and package["receipt_ref"] in (None, ""):
        errors.append("FAIL: receipt_ref is empty")

    # requires_beo_approval 반드시 True
    if package.get("requires_beo_approval") is not True:
        errors.append("FAIL: requires_beo_approval must be True")

    # eag3_ready 반드시 True
    if package.get("eag3_ready") is not True:
        errors.append("FAIL: eag3_ready must be True")

    # normal_upload_model 확인
    model = package.get("normal_upload_model", [])
    if "SESSION_CONTEXT_FULL" in model:
        errors.append("FAIL: SESSION_CONTEXT_FULL must not appear in normal_upload_model")

    passed = len(errors) == 0

    return {
        "pass": passed,
        "validator": "phase2_status_update",
        "errors": errors,
    }

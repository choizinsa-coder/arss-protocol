"""
phase2_commit_gate.py
PT-S81-ARCH-001 Phase 2 Step 11

Purpose:
- 통합 검증 PASS 전 commit 차단
- ALL PASS 후에만 commit 허용

Required PASS:
- integrated_phase2_validator.pass == true
- commit_allowed == true
- no missing validator result
- no skipped required validator

FAIL:
- any validator missing
- any validator failed
- commit_allowed=false
- partial validation result
"""

REQUIRED_VALIDATORS_IN_RESULT = [
    "generation_pipeline",
    "pair_validator",
    "boundary_enforcement_validator",
    "upload_bundle_validator",
    "agent_injection_manifest",
    "runtime_first_generation",
    "runtime_pair_hash_match",
    "no_circular_hash_binding",
    "no_full_in_normal_upload_bundle",
]


def check_commit_gate(integrated_result: dict) -> dict:
    """
    Args:
        integrated_result: output from integrated_phase2_validator.validate_integrated()

    Returns:
        {
            "pass": bool,
            "validator": "phase2_commit_gate",
            "commit_allowed": bool,
            "errors": [str],
        }
    """
    errors = []

    # integrated_phase2_validator 자체 pass 확인
    if not isinstance(integrated_result, dict):
        errors.append("FAIL: integrated_result is not a dict")
        return {
            "pass": False,
            "validator": "phase2_commit_gate",
            "commit_allowed": False,
            "errors": errors,
        }

    if integrated_result.get("validator") != "integrated_phase2_validator":
        errors.append(
            "FAIL: input is not from integrated_phase2_validator"
        )

    if not integrated_result.get("pass", False):
        errors.append("FAIL: integrated_phase2_validator.pass is not True")

    if not integrated_result.get("commit_allowed", False):
        errors.append("FAIL: commit_allowed is not True")

    # 개별 results 검사 — MISSING 또는 FAIL 항목 차단
    results = integrated_result.get("results", {})

    for name in REQUIRED_VALIDATORS_IN_RESULT:
        status = results.get(name)
        if status is None:
            errors.append(f"FAIL: required validator result missing from results — {name}")
        elif status == "MISSING":
            errors.append(f"FAIL: validator was skipped — {name}")
        elif status == "FAIL":
            errors.append(f"FAIL: validator failed — {name}")

    passed = len(errors) == 0
    commit_allowed = passed

    return {
        "pass": passed,
        "validator": "phase2_commit_gate",
        "commit_allowed": commit_allowed,
        "errors": errors,
    }

"""
integrated_phase2_validator.py
PT-S81-ARCH-001 Phase 2 Step 10

Purpose:
- Step 5~9 결과를 통합 검증
- commit 진입 가능 여부 판정

Required checks:
- generation_pipeline PASS
- pair_validator PASS
- boundary_enforcement_validator PASS
- upload_bundle_validator PASS
- agent_injection_manifest PASS
- runtime-first generation evidence PASS
- runtime_pair_hash match PASS
- no circular hash binding PASS
- no FULL in normal upload bundle PASS

Output:
{
  "pass": bool,
  "validator": "integrated_phase2_validator",
  "commit_allowed": bool,
  "errors": [],
  "results": {}
}

Rule:
- any FAIL → commit_allowed=false
"""

REQUIRED_VALIDATORS = [
    "generation_pipeline",
    "pair_validator",
    "boundary_enforcement_validator",
    "upload_bundle_validator",
    "agent_injection_manifest",
]

REQUIRED_CHECKS = [
    "runtime_first_generation",
    "runtime_pair_hash_match",
    "no_circular_hash_binding",
    "no_full_in_normal_upload_bundle",
]


def validate_integrated(validator_results: dict, extra_checks: dict = None) -> dict:
    """
    Args:
        validator_results: dict keyed by validator name → {"pass": bool, ...}
        extra_checks: dict keyed by check name → bool

    Returns:
        {
            "pass": bool,
            "validator": "integrated_phase2_validator",
            "commit_allowed": bool,
            "errors": [str],
            "results": dict,
        }
    """
    if extra_checks is None:
        extra_checks = {}

    errors = []
    results = {}

    # 필수 validator 결과 확인
    for name in REQUIRED_VALIDATORS:
        if name not in validator_results:
            errors.append(f"FAIL: required validator result missing — {name}")
            results[name] = "MISSING"
            continue

        vr = validator_results[name]
        passed = vr.get("pass", False) if isinstance(vr, dict) else bool(vr)

        if not passed:
            errors.append(f"FAIL: validator failed — {name}")
            results[name] = "FAIL"
        else:
            results[name] = "PASS"

    # 필수 extra check 확인
    for check in REQUIRED_CHECKS:
        if check not in extra_checks:
            errors.append(f"FAIL: required check missing — {check}")
            results[check] = "MISSING"
            continue

        if not extra_checks[check]:
            errors.append(f"FAIL: check failed — {check}")
            results[check] = "FAIL"
        else:
            results[check] = "PASS"

    passed = len(errors) == 0
    commit_allowed = passed

    return {
        "pass": passed,
        "validator": "integrated_phase2_validator",
        "commit_allowed": commit_allowed,
        "errors": errors,
        "results": results,
    }

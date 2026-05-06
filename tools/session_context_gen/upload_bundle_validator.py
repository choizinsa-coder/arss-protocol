"""
upload_bundle_validator.py
PT-S81-ARCH-001 Phase 2 Step 8

Purpose:
- 정상 업로드 번들에서 SESSION_CONTEXT_FULL 제외 여부 검증
- SESSION_BOOT + SESSION_STATE_RUNTIME 존재 여부 검증

Rule:
- normal_upload_bundle = [SESSION_BOOT, SESSION_STATE_RUNTIME] only
- SESSION_CONTEXT_FULL은 normal upload bundle에 포함 금지
"""

REQUIRED_KEYS = {"SESSION_BOOT", "SESSION_STATE_RUNTIME"}
FORBIDDEN_KEYS = {"SESSION_CONTEXT_FULL"}


def validate_upload_bundle(bundle: dict) -> dict:
    """
    Args:
        bundle: dict with keys representing zone names present in the upload bundle.
                e.g. {"SESSION_BOOT": {...}, "SESSION_STATE_RUNTIME": {...}}

    Returns:
        {
            "pass": bool,
            "validator": "upload_bundle_validator",
            "errors": [str],
            "present_keys": [str],
            "missing_required": [str],
            "forbidden_found": [str],
        }
    """
    errors = []
    present_keys = set(bundle.keys())

    missing_required = sorted(REQUIRED_KEYS - present_keys)
    forbidden_found = sorted(FORBIDDEN_KEYS & present_keys)

    if missing_required:
        for key in missing_required:
            errors.append(f"FAIL: required key missing — {key}")

    if forbidden_found:
        for key in forbidden_found:
            errors.append(f"FAIL: forbidden key present in normal upload bundle — {key}")

    passed = len(errors) == 0

    return {
        "pass": passed,
        "validator": "upload_bundle_validator",
        "errors": errors,
        "present_keys": sorted(present_keys),
        "missing_required": missing_required,
        "forbidden_found": forbidden_found,
    }

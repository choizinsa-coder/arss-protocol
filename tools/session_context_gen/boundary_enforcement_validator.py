ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"

# boundary_enforcement_validator.py
# PT-S81-ARCH-001 Phase 2
# Absorbs context_sanitizer (B안) — detect-and-fail, no silent mutation.


class BoundaryEnforcementValidatorError(Exception):
    pass


# Allowed injection maps per Domi spec
_ALLOWED = {
    "domi": {"SESSION_BOOT"},
    "jeni": {"SESSION_BOOT", "SESSION_STATE_RUNTIME"},
    "caddy": {"SESSION_BOOT", "SESSION_STATE_RUNTIME"},
    "normal_upload_bundle": {"SESSION_BOOT", "SESSION_STATE_RUNTIME"},
}

_FORBIDDEN_FULL = "SESSION_CONTEXT_FULL"


def validate_agent_boundaries(bundle_manifest: dict) -> dict:
    """
    Validate agent injection boundary rules.

    Input bundle_manifest example:
    {
      "domi": ["SESSION_BOOT"],
      "jeni": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
      "caddy": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"],
      "normal_upload_bundle": ["SESSION_BOOT", "SESSION_STATE_RUNTIME"]
    }

    PASS conditions (Domi spec):
    - Domi receives SESSION_BOOT only.
    - Domi does not receive SESSION_STATE_RUNTIME.
    - Domi does not receive SESSION_CONTEXT_FULL.
    - Jeni receives SESSION_BOOT + SESSION_STATE_RUNTIME.
    - Caddy receives SESSION_BOOT + SESSION_STATE_RUNTIME.
    - Normal upload bundle excludes SESSION_CONTEXT_FULL.
    - SESSION_CONTEXT_FULL may appear only under emergency_fallback mode
      with Beo approval flag.

    FAIL conditions:
    - Domi receives RUNTIME.
    - Domi receives FULL.
    - FULL appears in normal upload bundle.
    - agent routing map is missing.
    - boundary is ambiguous (unknown agent key with FULL).
    - context_sanitizer legacy behavior (silent mutation) — not applicable here;
      this validator only detects and fails.
    """
    errors = []
    warnings = []

    # 1. agent routing map must be present
    if not bundle_manifest:
        errors.append("agent routing map is missing or empty")
        return _result(False, errors, warnings)

    # 2. Emergency fallback check
    emergency_fallback = bundle_manifest.get("emergency_fallback", False)
    beo_approval = bundle_manifest.get("beo_approval_flag", False)

    # 3. Per-agent boundary checks
    for agent, allowed_set in _ALLOWED.items():
        if agent not in bundle_manifest:
            # Missing agent entry — ambiguous boundary
            errors.append(f"agent routing map missing entry for '{agent}'")
            continue

        received = set(bundle_manifest[agent])

        # FULL check (applies to all normal agents)
        if _FORBIDDEN_FULL in received:
            if emergency_fallback and beo_approval:
                warnings.append(
                    f"SESSION_CONTEXT_FULL present for '{agent}' "
                    f"under emergency_fallback with Beo approval — WARNING only"
                )
            else:
                errors.append(
                    f"SESSION_CONTEXT_FULL present in '{agent}' bundle "
                    f"without emergency_fallback + beo_approval_flag"
                )

        # Domi-specific: must not receive RUNTIME
        if agent == "domi":
            if "SESSION_STATE_RUNTIME" in received:
                errors.append(
                    "Domi receives SESSION_STATE_RUNTIME — boundary violation"
                )
            if "SESSION_BOOT" not in received:
                errors.append("Domi does not receive SESSION_BOOT — required")

        # Jeni / Caddy: must receive both BOOT and RUNTIME
        if agent in ("jeni", "caddy"):
            if "SESSION_BOOT" not in received:
                errors.append(
                    f"'{agent}' does not receive SESSION_BOOT — required"
                )
            if "SESSION_STATE_RUNTIME" not in received:
                errors.append(
                    f"'{agent}' does not receive SESSION_STATE_RUNTIME — required"
                )

        # normal_upload_bundle: must not contain FULL
        if agent == "normal_upload_bundle":
            if _FORBIDDEN_FULL in received:
                if not (emergency_fallback and beo_approval):
                    errors.append(
                        "SESSION_CONTEXT_FULL present in normal_upload_bundle — forbidden"
                    )

    # 4. Unknown agent keys with FULL = ambiguous boundary
    known_keys = set(_ALLOWED.keys()) | {
        "emergency_fallback", "beo_approval_flag"
    }
    for key in bundle_manifest:
        if key not in known_keys:
            val = bundle_manifest[key]
            if isinstance(val, list) and _FORBIDDEN_FULL in val:
                errors.append(
                    f"Unknown agent '{key}' contains SESSION_CONTEXT_FULL "
                    f"— boundary is ambiguous"
                )

    result_pass = len(errors) == 0
    return _result(result_pass, errors, warnings)


def _result(pass_: bool, errors: list, warnings: list) -> dict:
    return {
        "pass": pass_,
        "validator": "boundary_enforcement_validator",
        "errors": errors,
        "warnings": warnings,
    }

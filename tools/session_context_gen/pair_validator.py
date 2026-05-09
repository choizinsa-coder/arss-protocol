ACTIVE_VERSION = "1.1.0"
VERSION_STATUS = "active"

import json
import hashlib

from .hash_utils import compute_hash


class PairValidatorError(Exception):
    pass


def validate_boot_runtime_pair(boot: dict, runtime: dict) -> dict:
    """
    Validate SESSION_BOOT / SESSION_STATE_RUNTIME pair integrity.

    PASS conditions (Domi Option A — actual file structure):
    - boot.session_count == runtime.session_count
    - boot.chain.tip == runtime.chain.tip
    - boot.boot_meta.runtime_pair_hash == hash(runtime canonical content)
    - boot.boot_meta.runtime_pair_rule == "BOOT_REFERENCES_RUNTIME_ONLY"
    - runtime does not contain boot_hash / boot_ref / boot_pair_hash /
      runtime_pair_hash / reverse_boot_reference
    - hash direction is one-way: RUNTIME -> hash -> BOOT reference

    Returns dict with keys: pass, validator, errors, warnings,
                            boot_hash, runtime_hash, runtime_pair_hash
    """
    errors = []
    warnings = []

    # Compute hashes
    try:
        runtime_hash = compute_hash(runtime)
    except Exception as e:
        return {
            "pass": False,
            "validator": "pair_validator",
            "errors": [f"runtime hash computation failed: {e}"],
            "warnings": [],
            "boot_hash": None,
            "runtime_hash": None,
            "runtime_pair_hash": None,
        }

    try:
        boot_hash = compute_hash(boot)
    except Exception as e:
        return {
            "pass": False,
            "validator": "pair_validator",
            "errors": [f"boot hash computation failed: {e}"],
            "warnings": [],
            "boot_hash": None,
            "runtime_hash": runtime_hash,
            "runtime_pair_hash": None,
        }

    # Extract fields — actual file structure
    boot_session_count = boot.get("session_count")
    runtime_session_count = runtime.get("session_count")

    boot_chain_tip = boot.get("chain", {}).get("tip")
    runtime_chain_tip = runtime.get("chain", {}).get("tip")

    boot_meta = boot.get("boot_meta", {})
    boot_runtime_pair_hash = boot_meta.get("runtime_pair_hash")
    boot_runtime_pair_rule = boot_meta.get("runtime_pair_rule")

    # --- PASS condition checks ---

    # 1. session_count match
    if boot_session_count is None or runtime_session_count is None:
        errors.append("session_count missing in boot or runtime")
    elif boot_session_count != runtime_session_count:
        errors.append(
            f"session_count mismatch: boot={boot_session_count} runtime={runtime_session_count}"
        )

    # 2. chain.tip match
    if boot_chain_tip is None or runtime_chain_tip is None:
        errors.append("chain.tip missing in boot or runtime")
    elif boot_chain_tip != runtime_chain_tip:
        errors.append(
            f"chain.tip mismatch: boot={boot_chain_tip} runtime={runtime_chain_tip}"
        )

    # 3. runtime_pair_hash present in boot_meta
    if boot_runtime_pair_hash is None:
        errors.append("runtime_pair_hash missing in boot_meta")
    else:
        # 4. runtime_pair_hash == hash(runtime canonical content)
        if boot_runtime_pair_hash != runtime_hash:
            errors.append(
                f"runtime_pair_hash mismatch: "
                f"boot_meta.runtime_pair_hash={boot_runtime_pair_hash} "
                f"hash(runtime)={runtime_hash}"
            )

    # 5. runtime_pair_rule
    if boot_runtime_pair_rule is None:
        errors.append("runtime_pair_rule missing in boot_meta")
    elif boot_runtime_pair_rule != "BOOT_REFERENCES_RUNTIME_ONLY":
        errors.append(
            f"runtime_pair_rule invalid: {boot_runtime_pair_rule}"
        )

    # 6. RUNTIME must not contain reverse BOOT references
    forbidden_in_runtime = [
        "boot_hash", "boot_ref", "boot_pair_hash",
        "runtime_pair_hash", "reverse_boot_reference"
    ]
    for field in forbidden_in_runtime:
        if field in runtime:
            errors.append(
                f"RUNTIME contains forbidden field '{field}' — circular hash binding detected"
            )

    result_pass = len(errors) == 0

    return {
        "pass": result_pass,
        "validator": "pair_validator",
        "errors": errors,
        "warnings": warnings,
        "boot_hash": boot_hash,
        "runtime_hash": runtime_hash,
        "runtime_pair_hash": boot_runtime_pair_hash,
    }

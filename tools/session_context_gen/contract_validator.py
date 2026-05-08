ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
contract_validator.py — Sub-Phase 3A BOOT/RUNTIME/PAIR Contract Validator
Authority: 도미 설계 / 캐디 구현 / 제니 검증 / 비오 EAG
SSOT Ref: Sub-Phase 3A 재구성 설계 — S101

Principle:
  formalization_ready != pytest pass
  formalization_ready != execution success
  Hash Boundary == Governance Boundary
"""

import json
from pathlib import Path
from typing import Optional

from .hash_utils import compute_hash


class ContractViolationError(Exception):
    pass


# ── Constants (도미 설계 권한 — 캐디 독자 변경 금지) ──────────────────────────

BOOT_REQUIRED_FIELDS = [
    "session_count",
    "chain",
    "boot_meta",
    "canonical_rules",
    "lessons",
    "pending_tasks",
    "state_events",
    "decisions",
]

BOOT_META_REQUIRED_FIELDS = [
    "boot_is_ssot",
    "ssot_ref",
    "conflict_resolution",
    "generated_from_sha256",
    "boot_generated_at",
    "runtime_pair_hash",
    "runtime_pair_rule",
]

BOOT_FORBIDDEN_FIELDS = [
    "boot_hash",
    "boot_ref",
    "boot_pair_hash",
    "reverse_boot_reference",
]

RUNTIME_REQUIRED_FIELDS = [
    "session_count",
    "chain",
]

RUNTIME_FORBIDDEN_FIELDS = [
    "boot_hash",
    "boot_ref",
    "boot_pair_hash",
    "runtime_pair_hash",
    "reverse_boot_reference",
]

EXPECTED_RUNTIME_PAIR_RULE = "BOOT_REFERENCES_RUNTIME_ONLY"


# ── BOOT Contract Validator ───────────────────────────────────────────────────

def validate_boot_contract(boot: dict) -> dict:
    """
    Validate SESSION_BOOT against BOOT_CONTRACT_V1.

    Returns:
        dict with keys: pass, contract, errors, warnings
    """
    errors = []
    warnings = []

    # 1. required fields
    for field in BOOT_REQUIRED_FIELDS:
        if field not in boot:
            errors.append(f"[S3A-STOP-1] BOOT missing required field: '{field}'")

    # 2. boot_meta required fields
    boot_meta = boot.get("boot_meta", {})
    if not isinstance(boot_meta, dict):
        errors.append("[S3A-STOP-1] boot_meta is not a dict")
    else:
        for field in BOOT_META_REQUIRED_FIELDS:
            if field not in boot_meta:
                errors.append(
                    f"[S3A-STOP-1] boot_meta missing required field: '{field}'"
                )

        # 3. boot_is_ssot must be False
        if boot_meta.get("boot_is_ssot") is not False:
            errors.append(
                "[BOOT_CONTRACT] boot_meta.boot_is_ssot must be false"
            )

        # 4. runtime_pair_rule
        rule = boot_meta.get("runtime_pair_rule")
        if rule != EXPECTED_RUNTIME_PAIR_RULE:
            errors.append(
                f"[BOOT_CONTRACT] runtime_pair_rule invalid: '{rule}' "
                f"(expected '{EXPECTED_RUNTIME_PAIR_RULE}')"
            )

        # 5. runtime_pair_hash must be non-empty
        rph = boot_meta.get("runtime_pair_hash")
        if not rph or not isinstance(rph, str):
            errors.append(
                "[BOOT_CONTRACT] boot_meta.runtime_pair_hash must be non-empty string"
            )

    # 6. forbidden fields
    for field in BOOT_FORBIDDEN_FIELDS:
        if field in boot:
            errors.append(
                f"[BOOT_CONTRACT] BOOT contains forbidden field: '{field}'"
            )

    # 7. session_count type check
    sc = boot.get("session_count")
    if sc is not None and not isinstance(sc, int):
        errors.append("[BOOT_CONTRACT] session_count must be integer")

    # 8. chain.tip non-empty
    chain = boot.get("chain", {})
    if isinstance(chain, dict):
        tip = chain.get("tip")
        if not tip or not isinstance(tip, str):
            warnings.append("[BOOT_CONTRACT] chain.tip missing or empty")

    return {
        "pass": len(errors) == 0,
        "contract": "BOOT_CONTRACT_V1",
        "errors": errors,
        "warnings": warnings,
    }


# ── RUNTIME Contract Validator ────────────────────────────────────────────────

def validate_runtime_contract(runtime: dict) -> dict:
    """
    Validate SESSION_STATE_RUNTIME against RUNTIME_CONTRACT_V1.

    Returns:
        dict with keys: pass, contract, errors, warnings
    """
    errors = []
    warnings = []

    # 1. required fields
    for field in RUNTIME_REQUIRED_FIELDS:
        if field not in runtime:
            errors.append(
                f"[S3A-STOP-1] RUNTIME missing required field: '{field}'"
            )

    # 2. forbidden reverse-reference fields
    for field in RUNTIME_FORBIDDEN_FIELDS:
        if field in runtime:
            errors.append(
                f"[RUNTIME_CONTRACT] RUNTIME contains forbidden field: '{field}' "
                f"— circular hash binding risk"
            )

    # 3. session_count type check
    sc = runtime.get("session_count")
    if sc is not None and not isinstance(sc, int):
        errors.append("[RUNTIME_CONTRACT] session_count must be integer")

    # 4. chain.tip non-empty
    chain = runtime.get("chain", {})
    if isinstance(chain, dict):
        tip = chain.get("tip")
        if not tip or not isinstance(tip, str):
            warnings.append("[RUNTIME_CONTRACT] chain.tip missing or empty")

    return {
        "pass": len(errors) == 0,
        "contract": "RUNTIME_CONTRACT_V1",
        "errors": errors,
        "warnings": warnings,
    }


# ── PAIR Contract Validator ───────────────────────────────────────────────────

def validate_pair_contract(boot: dict, runtime: dict) -> dict:
    """
    Validate BOOT/RUNTIME pair integrity against PAIR_CONTRACT_V1.
    Hash direction: RUNTIME -> BOOT (one-way only).

    Returns:
        dict with keys: pass, contract, errors, warnings,
                        boot_hash, runtime_hash, runtime_pair_hash
    """
    errors = []
    warnings = []

    # compute hashes
    try:
        runtime_hash = compute_hash(runtime)
    except Exception as e:
        return {
            "pass": False,
            "contract": "PAIR_CONTRACT_V1",
            "errors": [f"[PAIR_CONTRACT] runtime hash computation failed: {e}"],
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
            "contract": "PAIR_CONTRACT_V1",
            "errors": [f"[PAIR_CONTRACT] boot hash computation failed: {e}"],
            "warnings": [],
            "boot_hash": None,
            "runtime_hash": runtime_hash,
            "runtime_pair_hash": None,
        }

    boot_meta = boot.get("boot_meta", {})

    # 1. session_count match
    boot_sc = boot.get("session_count")
    runtime_sc = runtime.get("session_count")
    if boot_sc is None or runtime_sc is None:
        errors.append("[PAIR_CONTRACT] session_count missing in boot or runtime")
    elif boot_sc != runtime_sc:
        errors.append(
            f"[PAIR_CONTRACT] session_count mismatch: "
            f"boot={boot_sc} runtime={runtime_sc}"
        )

    # 2. chain.tip match
    boot_tip = boot.get("chain", {}).get("tip")
    runtime_tip = runtime.get("chain", {}).get("tip")
    if boot_tip is None or runtime_tip is None:
        errors.append("[PAIR_CONTRACT] chain.tip missing in boot or runtime")
    elif boot_tip != runtime_tip:
        errors.append(
            f"[PAIR_CONTRACT] chain.tip mismatch: "
            f"boot={boot_tip} runtime={runtime_tip}"
        )

    # 3. runtime_pair_hash present and correct
    stored_rph = boot_meta.get("runtime_pair_hash")
    if not stored_rph:
        errors.append(
            "[PAIR_CONTRACT] boot_meta.runtime_pair_hash missing"
        )
    elif stored_rph != runtime_hash:
        errors.append(
            f"[PAIR_CONTRACT] runtime_pair_hash mismatch: "
            f"stored={stored_rph} computed={runtime_hash}"
        )

    # 4. runtime_pair_rule
    rule = boot_meta.get("runtime_pair_rule")
    if rule != EXPECTED_RUNTIME_PAIR_RULE:
        errors.append(
            f"[PAIR_CONTRACT] runtime_pair_rule invalid: '{rule}'"
        )

    # 5. runtime forbidden fields (no reverse reference)
    for field in RUNTIME_FORBIDDEN_FIELDS:
        if field in runtime:
            errors.append(
                f"[PAIR_CONTRACT] RUNTIME contains forbidden field '{field}' "
                f"— circular hash binding detected"
            )

    return {
        "pass": len(errors) == 0,
        "contract": "PAIR_CONTRACT_V1",
        "errors": errors,
        "warnings": warnings,
        "boot_hash": boot_hash,
        "runtime_hash": runtime_hash,
        "runtime_pair_hash": stored_rph,
    }


# ── Full Contract Validation ──────────────────────────────────────────────────

def validate_all(boot: dict, runtime: dict) -> dict:
    """
    Run BOOT + RUNTIME + PAIR contract validation.

    Returns:
        dict with keys: pass, results (list), summary
    """
    boot_result = validate_boot_contract(boot)
    runtime_result = validate_runtime_contract(runtime)
    pair_result = validate_pair_contract(boot, runtime)

    all_pass = all([
        boot_result["pass"],
        runtime_result["pass"],
        pair_result["pass"],
    ])

    return {
        "pass": all_pass,
        "results": [boot_result, runtime_result, pair_result],
        "summary": {
            "BOOT_CONTRACT_V1": boot_result["pass"],
            "RUNTIME_CONTRACT_V1": runtime_result["pass"],
            "PAIR_CONTRACT_V1": pair_result["pass"],
        },
    }


# ── Contract File Loader ──────────────────────────────────────────────────────

def load_contract_spec(contract_path: Optional[str] = None) -> dict:
    """
    Load boot_runtime_contract.json from given path or default location.
    """
    if contract_path is None:
        default = Path(__file__).parent / "boot_runtime_contract.json"
        contract_path = str(default)

    p = Path(contract_path)
    if not p.exists():
        raise FileNotFoundError(
            f"[S3A-STOP-1] Contract spec not found: {contract_path}"
        )

    with open(p, encoding="utf-8") as f:
        return json.load(f)

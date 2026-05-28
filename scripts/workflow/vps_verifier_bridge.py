#!/usr/bin/env python3
ACTIVE_VERSION = "1.1.0"
VERSION_STATUS = "active"
"""
vps_verifier_bridge.py
ARSS VPS Production Chain Verifier — Bridge v0.3
Refactored for RULE-5 compliance per BRIEFING-DOMI-S159-VL2VL3-001 (S159, EAG approved)

Purpose:
    Verify the production RPU chain stored at VPS
    ARSS_HUB/04_EVIDENCE/SNAPSHOT_LOG/
    against the ARSS-RPU-1.0 production schema.

    NOTE: This verifier targets the production schema (ARSS-RPU-1.0),
    which differs from the sample chain schema used by
    reference-verifier/src/verifier.py (samples/ only).

    Schema differences from samples verifier:
      - payload_hash : rpu["chain"]["payload_hash"]     (not top-level)
      - prev_hash    : rpu["chain"]["prev_chain_hash"]  (not top-level)
      - chain_hash   : rpu["chain"]["chain_hash"]       (not top-level)
      - event_type   : rpu["payload"]["event_type"]     (not top-level)
      - filename     : RPU-XXXX.json                    (uppercase)

    Algorithm (matches arss_generator_v1.py exactly):
      canonical_json : recursive dict alpha sort +
                       json.dumps(obj, ensure_ascii=False)
      payload_hash   : SHA256(canonical_json(payload).encode("utf-8"))
      chain_hash     : SHA256("GENESIS:" + payload_hash)  [Genesis]
                       SHA256((prev + ":" + payload_hash).encode("utf-8"))
      null handling  : None forbidden in payload (ValueError)

Usage:
    python vps_verifier_bridge.py
    python vps_verifier_bridge.py --chain-dir /custom/path/to/SNAPSHOT_LOG
    python vps_verifier_bridge.py --output-json

Exit codes:
    0 — ALL PASS
    1 — FAIL or ERROR
"""

import json
import hashlib
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone


# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

DEFAULT_CHAIN_DIR = "/opt/arss/engine/arss-protocol/evidence"
BRIDGE_VERSION = "0.3"
PRODUCTION_SCHEMA = "ARSS-RPU-1.0"


# ─────────────────────────────────────────────
# Canonicalization — matches arss_generator_v1.py exactly
# recursive dict alpha sort + json.dumps(ensure_ascii=False)
# None forbidden (ValueError)
# ─────────────────────────────────────────────

def canonical_json(obj) -> str:
    """
    Canonical JSON serialization matching arss_generator_v1.py.
    - Dict keys sorted alphabetically (recursive)
    - json.dumps with ensure_ascii=False
    - None forbidden — raises ValueError
    """
    if isinstance(obj, dict):
        sorted_items = sorted(obj.items(), key=lambda x: x[0])
        inner = ",".join(
            f"{json.dumps(k, ensure_ascii=False)}:{canonical_json(v)}"
            for k, v in sorted_items
        )
        return "{" + inner + "}"
    elif isinstance(obj, list):
        return "[" + ",".join(canonical_json(i) for i in obj) + "]"
    elif obj is None:
        raise ValueError("None is forbidden in production payload")
    else:
        return json.dumps(obj, ensure_ascii=False)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_payload_hash(payload: dict) -> str:
    """
    payload_hash = SHA256(canonical_json(payload).encode("utf-8"))
    Matches arss_generator_v1.py L49-52.
    """
    canonical = canonical_json(payload)
    return sha256_hex(canonical.encode("utf-8"))


def compute_chain_hash(prev_chain_hash: str, payload_hash: str,
                       is_genesis: bool = False) -> str:
    """
    Production chain_hash algorithm (arss_generator_v1.py L55-65).
    Genesis : SHA256("GENESIS:" + payload_hash)
    Others  : SHA256((prev_chain_hash + ":" + payload_hash).encode("utf-8"))
    """
    if is_genesis:
        combined = ("GENESIS:" + payload_hash).encode("utf-8")
    else:
        combined = (prev_chain_hash + ":" + payload_hash).encode("utf-8")
    return sha256_hex(combined)


# ─────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_ledger(chain_dir: Path) -> dict:
    """
    Load ledger.json from chain_dir.
    Returns None if not found — triggers WARNING.
    """
    ledger_path = chain_dir / "ledger.json"
    if not ledger_path.exists():
        return None
    return load_json(ledger_path)


# ─────────────────────────────────────────────
# VL-2 decomposition helpers
# Design: BRIEFING-DOMI-S159-VL2VL3-001
# fail_signal dict 반환만 / loop ownership verify_production_chain 전담
# ─────────────────────────────────────────────

def _load_chain_ledger(chain_dir: Path) -> dict:
    """
    Load ledger.json and extract chain_tip.

    Returns:
        {"fail_signal": None, "ledger_tip": str | None}
    NOTE: No fail_signal — ledger absence is a WARNING, not a hard failure.
    """
    ledger = load_ledger(chain_dir)
    if ledger is None:
        print("WARNING: ledger.json not found — tip validation skipped")
        return {"fail_signal": None, "ledger_tip": None}
    return {"fail_signal": None, "ledger_tip": ledger.get("chain_tip")}


def _collect_sorted_rpus(chain_dir: Path) -> dict:
    """
    Collect and sort RPU-XXXX.json files by numeric suffix.

    Returns:
        {"fail_signal": {"error": str} | None, "rpu_files": list}
    NOTE: Does NOT manage result dict. Caller sets result["error"] on fail_signal.
    """
    try:
        rpu_files = sorted(
            [f for f in chain_dir.iterdir()
             if f.name.upper().startswith("RPU-") and f.name.endswith(".json")
             and f.name != "RPU-ledger.json"],
            key=lambda f: int(f.stem.split("-")[1])
        )
    except (ValueError, IndexError) as e:
        return {
            "fail_signal": {"error": f"RPU filename parse error: {e}"},
            "rpu_files": [],
        }
    if not rpu_files:
        return {
            "fail_signal": {"error": f"No RPU files (RPU-XXXX.json) found in {chain_dir}"},
            "rpu_files": [],
        }
    return {"fail_signal": None, "rpu_files": rpu_files}


def _verify_single_rpu(rpu_file: Path, prev_chain_hash, is_first: bool) -> dict:
    """
    Steps 1-6: single RPU verification.

    Returns:
        {
            "rpu_result":          dict,
            "updated_chain_hash":  str | None,
            "fail_signal":         {"error": str} | None,
        }
    NOTE: Does NOT manage loop state or result dict. Caller owns prev_chain_hash threading.
    """
    rpu = load_json(rpu_file)
    rpu_result = {
        "file":           rpu_file.name,
        "rpu_id":         rpu.get("rpu_id", "?"),
        "event_type":     rpu.get("payload", {}).get("event_type", "UNKNOWN"),
        "schema_version": None,
        "payload_hash":   None,
        "prev_hash":      None,
        "chain_hash":     None,
        "pass":           False,
    }

    all_ok = []

    # Step 1: schema_version
    schema_ver = rpu.get("schema_version", "")
    schema_ok = schema_ver == PRODUCTION_SCHEMA
    rpu_result["schema_version"] = "PASS" if schema_ok else f"FAIL (got: {schema_ver})"
    all_ok.append(schema_ok)

    # Step 2: payload existence
    if "payload" not in rpu:
        return {"rpu_result": rpu_result, "updated_chain_hash": None,
                "fail_signal": {"error": f"Missing payload in {rpu_file.name}"}}

    # Step 3: chain block existence
    if "chain" not in rpu:
        return {"rpu_result": rpu_result, "updated_chain_hash": None,
                "fail_signal": {"error": f"Missing chain block in {rpu_file.name}"}}

    payload     = rpu["payload"]
    chain_block = rpu["chain"]

    # Step 4: payload_hash recomputation
    try:
        recomputed_ph = compute_payload_hash(payload)
    except ValueError as e:
        return {"rpu_result": rpu_result, "updated_chain_hash": None,
                "fail_signal": {"error": f"payload canonicalization error in {rpu_file.name}: {e}"}}

    declared_ph = chain_block.get("payload_hash", "")
    ph_ok = recomputed_ph == declared_ph
    rpu_result["payload_hash"] = "PASS" if ph_ok else "FAIL"
    all_ok.append(ph_ok)

    # Step 5: prev_chain_hash continuity
    declared_prev = chain_block.get("prev_chain_hash", "")
    if is_first:
        current_prev = declared_prev
        prev_ok = True
    else:
        current_prev = prev_chain_hash
        prev_ok = declared_prev == current_prev
    rpu_result["prev_hash"] = "PASS" if prev_ok else "FAIL"
    all_ok.append(prev_ok)

    # Step 6: chain_hash recomputation
    is_genesis_rpu = (declared_prev == "GENESIS" or declared_prev == "")
    recomputed_ch  = compute_chain_hash(current_prev, recomputed_ph, is_genesis=is_genesis_rpu)
    declared_ch    = chain_block.get("chain_hash", "")
    ch_ok = recomputed_ch == declared_ch
    rpu_result["chain_hash"] = "PASS" if ch_ok else "FAIL"
    all_ok.append(ch_ok)

    rpu_result["pass"] = all(all_ok)
    return {
        "rpu_result":         rpu_result,
        "updated_chain_hash": declared_ch,
        "fail_signal":        None,
    }


def _cross_validate_ledger_tip(ledger_tip, final_chain_hash) -> bool:
    """
    Ledger tip cross-validation.

    Returns:
        bool (match result) if both values present, None otherwise.
    NOTE: Caller sets result["ledger_tip_match"] only when return is not None.
    """
    if ledger_tip and final_chain_hash:
        return ledger_tip == final_chain_hash
    return None


# ─────────────────────────────────────────────
# Core verification — Production schema ARSS-RPU-1.0
# ─────────────────────────────────────────────

def verify_production_chain(chain_dir: Path) -> dict:
    """
    Verify all RPU files in chain_dir against ARSS-RPU-1.0 schema.

    RPU files: RPU-XXXX.json (uppercase, sorted by numeric suffix)
    Verification layers:
        1. schema_version check (ARSS-RPU-1.0)
        2. payload existence + None guard
        3. chain block existence
        4. payload_hash recomputation (canonical_json + SHA256)
        5. prev_chain_hash continuity
        6. chain_hash recomputation
        7. ledger.json chain_tip cross-validation (if present)
    All layers must pass for all_pass = True.
    """
    result = {
        "bridge_version":   BRIDGE_VERSION,
        "production_schema": PRODUCTION_SCHEMA,
        "chain_dir":        str(chain_dir),
        "verified_at":      datetime.now(timezone.utc).isoformat(),
        "rpus":             [],
        "all_pass":         False,
        "final_chain_hash": None,
        "ledger_tip_match": None,
        "error":            None,
    }

    # ── Load ledger ──
    ledger_info = _load_chain_ledger(chain_dir)
    ledger_tip  = ledger_info["ledger_tip"]

    # ── Collect RPU files ──
    rpu_collection = _collect_sorted_rpus(chain_dir)
    if rpu_collection["fail_signal"]:
        result["error"] = rpu_collection["fail_signal"]["error"]
        return result

    all_pass        = True
    prev_chain_hash = None
    final_chain_hash = None
    is_first        = True

    for rpu_file in rpu_collection["rpu_files"]:
        step = _verify_single_rpu(rpu_file, prev_chain_hash, is_first)
        result["rpus"].append(step["rpu_result"])

        if step["fail_signal"]:
            result["error"] = step["fail_signal"]["error"]
            return result

        if not step["rpu_result"]["pass"]:
            all_pass = False

        prev_chain_hash  = step["updated_chain_hash"]
        final_chain_hash = step["updated_chain_hash"]
        is_first = False

    result["final_chain_hash"] = final_chain_hash

    # ── Ledger tip cross-validation ──
    tip_match = _cross_validate_ledger_tip(ledger_tip, final_chain_hash)
    if tip_match is not None:
        result["ledger_tip_match"] = tip_match
        if not tip_match:
            all_pass = False

    result["all_pass"] = all_pass
    return result


# ─────────────────────────────────────────────
# Output formatter
# ─────────────────────────────────────────────

def print_result(result: dict):
    print("=" * 60)
    print(f"ARSS VPS Production Chain Verifier — Bridge v{BRIDGE_VERSION}")
    print(f"Production Schema: {result['production_schema']}")
    print(f"Chain Dir: {result['chain_dir']}")
    print(f"Verified At: {result['verified_at']}")
    print("=" * 60)

    if result.get("error"):
        print(f"\nERROR: {result['error']}")
        print("=" * 60)
        return

    for rpu in result["rpus"]:
        status = "✓" if rpu["pass"] else "✗"
        print(f"\n[{status}] {rpu['event_type']}  ({rpu['rpu_id']})")
        print(f"  file           : {rpu['file']}")
        print(f"  schema_version : {rpu['schema_version']}")
        print(f"  payload_hash   : {rpu['payload_hash']}")
        print(f"  prev_hash      : {rpu['prev_hash']}")
        print(f"  chain_hash     : {rpu['chain_hash']}")

    print("\n" + "=" * 60)

    if result["all_pass"]:
        print("RESULT: ALL PASS")
    else:
        print("RESULT: FAIL — see details above")

    print(f"\nFinal chain hash:")
    print(f"  {result['final_chain_hash']}")

    if result["ledger_tip_match"] is not None:
        match_str = "MATCH" if result["ledger_tip_match"] else "MISMATCH ← FAIL"
        print(f"\nLedger tip cross-check : {match_str}")

    print("\nGovernance is not declared. It is recomputed.")
    print("=" * 60)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ARSS VPS Production Chain Verifier — Bridge v0.3"
    )
    parser.add_argument(
        "--chain-dir",
        default=DEFAULT_CHAIN_DIR,
        help=f"Path to SNAPSHOT_LOG directory (default: {DEFAULT_CHAIN_DIR})"
    )
    parser.add_argument(
        "--single",
        metavar="FILE",
        help="Verify a single candidate RPU JSON file (generator precheck only)"
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output result as JSON instead of human-readable format"
    )
    args = parser.parse_args()

    # --single mode: single candidate precheck (generator 연동용)
    if args.single:
        single_path = Path(args.single)
        if not single_path.exists():
            print(json.dumps({"ok": False, "errors": [f"File not found: {args.single}"]}))
            sys.exit(1)
        try:
            candidate  = load_json(single_path)
            errors     = []
            chain_block  = candidate.get("chain", {})
            payload_obj  = candidate.get("payload", candidate)
            computed_payload = compute_payload_hash(payload_obj)
            declared_ph      = chain_block.get("payload_hash")
            if computed_payload != declared_ph:
                errors.append("payload_hash mismatch: expected "
                               + computed_payload + ", got " + str(declared_ph))
            prev_hash     = chain_block.get("prev_chain_hash", "")
            computed_chain = compute_chain_hash(prev_hash, computed_payload)
            declared_ch   = chain_block.get("chain_hash")
            if computed_chain != declared_ch:
                errors.append("chain_hash mismatch: expected "
                               + computed_chain + ", got " + str(declared_ch))
            result = {
                "ok":   len(errors) == 0,
                "mode": "single_candidate_precheck",
                "note": "prev_hash chain continuity not verified — generator precheck only",
                "errors": errors,
            }
            print(json.dumps(result))
            sys.exit(0 if result["ok"] else 1)
        except Exception as e:
            print(json.dumps({"ok": False, "mode": "single_candidate_precheck",
                               "errors": [str(e)]}))
            sys.exit(1)

    chain_dir = Path(args.chain_dir)
    if not chain_dir.is_dir():
        print(f"ERROR: '{chain_dir}' is not a directory")
        sys.exit(1)

    result = verify_production_chain(chain_dir)

    if args.output_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_result(result)

    sys.exit(0 if result["all_pass"] else 1)


# =============================================================================
# BRIDGE-MODE EXTENSION v1.0 — Candidate State Verification
# Added: 2026-04-09 | EAG-2 Approved
# Purpose: Verify candidate RPU in memory without touching evidence/ directly
# =============================================================================

import argparse as _argparse
import json as _json
import sys as _sys


# ─────────────────────────────────────────────
# VL-3 decomposition helpers
# Design: BRIEFING-DOMI-S159-VL2VL3-001
# fail_signal dict 반환만 / verify_production_chain 호출 관계 verify_with_candidate 전담
# ─────────────────────────────────────────────

def _load_candidate_rpu(candidate_rpu_path: Path) -> dict:
    """
    Step 1: Load candidate RPU JSON.

    Returns:
        {"fail_signal": {"error": str} | None, "candidate_rpu": dict | None}
    """
    try:
        candidate_rpu = load_json(candidate_rpu_path)
        return {"fail_signal": None, "candidate_rpu": candidate_rpu}
    except Exception as e:
        return {"fail_signal": {"error": f"CANDIDATE_RPU_LOAD_FAILED: {e}"},
                "candidate_rpu": None}


def _load_candidate_ledger(candidate_ledger_path: Path) -> dict:
    """
    Step 2: Load candidate ledger JSON.

    Returns:
        {"fail_signal": {"error": str} | None, "candidate_ledger": dict | None}
    """
    try:
        candidate_ledger = load_json(candidate_ledger_path)
        return {"fail_signal": None, "candidate_ledger": candidate_ledger}
    except Exception as e:
        return {"fail_signal": {"error": f"CANDIDATE_LEDGER_LOAD_FAILED: {e}"},
                "candidate_ledger": None}


def _verify_candidate_integrity(
    candidate_rpu: dict,
    base_final_hash: str,
) -> dict:
    """
    Steps 4-7: candidate schema, hash length, flat leakage, continuity,
               payload hash, chain hash.

    Returns:
        {
            "fail_signal":       {"error": str} | None,
            "schema_valid":      bool,
            "chain_continuity":  bool,
            "declared_ch":       str | None,
        }
    NOTE: Does NOT manage result dict. Caller sets result flags on return.
    """
    # Step 4a: schema_version
    schema_ver = candidate_rpu.get("schema_version", "")
    if schema_ver != PRODUCTION_SCHEMA:
        return {"fail_signal": {"error": f"SCHEMA_MISMATCH: {schema_ver}"},
                "schema_valid": False, "chain_continuity": False, "declared_ch": None}

    chain_block = candidate_rpu.get("chain")
    if not chain_block:
        return {"fail_signal": {"error": "CANDIDATE_MISSING_CHAIN_BLOCK"},
                "schema_valid": False, "chain_continuity": False, "declared_ch": None}

    declared_ph   = chain_block.get("payload_hash", "")
    declared_prev = chain_block.get("prev_chain_hash", "")
    declared_ch   = chain_block.get("chain_hash", "")

    # Step 4b: hash length validation
    if len(declared_ph) != 64 or len(declared_prev) != 64 or len(declared_ch) != 64:
        return {"fail_signal": {"error": "CANDIDATE_HASH_LENGTH_INVALID"},
                "schema_valid": False, "chain_continuity": False, "declared_ch": None}

    # Step 4c: flat schema leakage check
    forbidden_flat_keys = {"payload_hash", "prev_chain_hash", "chain_hash",
                            "event_type", "content"}
    flat_leakage = set(candidate_rpu.keys()) & forbidden_flat_keys
    if flat_leakage:
        return {"fail_signal": {"error": f"FLAT_SCHEMA_DETECTED: {flat_leakage}"},
                "schema_valid": False, "chain_continuity": False, "declared_ch": None}

    # Step 5: prev_chain_hash continuity
    if declared_prev != base_final_hash:
        return {
            "fail_signal": {"error": (
                f"CHAIN_CONTINUITY_BROKEN: "
                f"candidate.prev={declared_prev[:16]}... "
                f"base_final={base_final_hash[:16] if base_final_hash else 'None'}..."
            )},
            "schema_valid": True, "chain_continuity": False, "declared_ch": None,
        }

    # Step 6: payload hash recomputation
    payload = candidate_rpu.get("payload")
    if payload is None:
        return {"fail_signal": {"error": "CANDIDATE_MISSING_PAYLOAD"},
                "schema_valid": True, "chain_continuity": True, "declared_ch": declared_ch}

    recomputed_ph = compute_payload_hash(payload)
    if recomputed_ph != declared_ph:
        return {"fail_signal": {"error": "CANDIDATE_PAYLOAD_HASH_MISMATCH"},
                "schema_valid": True, "chain_continuity": True, "declared_ch": declared_ch}

    # Step 7: chain hash recomputation
    recomputed_ch = compute_chain_hash(declared_prev, recomputed_ph, is_genesis=False)
    if recomputed_ch != declared_ch:
        return {"fail_signal": {"error": "CANDIDATE_CHAIN_HASH_MISMATCH"},
                "schema_valid": True, "chain_continuity": True, "declared_ch": declared_ch}

    return {
        "fail_signal":      None,
        "schema_valid":     True,
        "chain_continuity": True,
        "declared_ch":      declared_ch,
    }


def _verify_candidate_ledger_tip(candidate_ledger: dict, declared_ch: str) -> dict:
    """
    Step 8: Validate candidate ledger chain_tip against declared_ch.

    Returns:
        {"fail_signal": {"error": str} | None}
    """
    candidate_tip = candidate_ledger.get("chain_tip")
    if candidate_tip != declared_ch:
        return {"fail_signal": {"error": (
            f"LEDGER_TIP_MISMATCH: "
            f"ledger={candidate_tip[:16] if candidate_tip else 'None'}... "
            f"candidate_ch={declared_ch[:16]}..."
        )}}
    return {"fail_signal": None}


# ─────────────────────────────────────────────
# Bridge-Mode — Candidate State Verification (VL-3 orchestrator)
# ─────────────────────────────────────────────

def verify_with_candidate(
    chain_dir: Path,
    candidate_rpu_path: Path,
    candidate_ledger_path: Path
) -> dict:
    """
    Bridge-Mode: 기존 체인 + candidate RPU를 메모리상 가상 결합하여 검증.
    evidence/ 파일에 대한 쓰기 없음 (Zero-Trust Validation).

    출력 계약:
    {
        "status": "PASS|FAIL",
        "all_pass": bool,
        "ledger_tip_match": bool,
        "schema_valid": bool,
        "chain_continuity": bool,
        "checked_rpu_count": int,
        "candidate_rpu": str,
        "error": str | null
    }
    """
    result = {
        "status":            "FAIL",
        "all_pass":          False,
        "ledger_tip_match":  False,
        "schema_valid":      False,
        "chain_continuity":  False,
        "checked_rpu_count": 0,
        "candidate_rpu":     None,
        "error":             None,
    }

    try:
        # Step 1: load candidate RPU
        rpu_load = _load_candidate_rpu(candidate_rpu_path)
        if rpu_load["fail_signal"]:
            result["error"] = rpu_load["fail_signal"]["error"]
            return result
        candidate_rpu = rpu_load["candidate_rpu"]
        result["candidate_rpu"] = candidate_rpu.get("rpu_id", str(candidate_rpu_path))

        # Step 2: load candidate ledger
        ledger_load = _load_candidate_ledger(candidate_ledger_path)
        if ledger_load["fail_signal"]:
            result["error"] = ledger_load["fail_signal"]["error"]
            return result
        candidate_ledger = ledger_load["candidate_ledger"]

        # Step 3: verify base production chain (단방향 신뢰 의존성 유지)
        base_result = verify_production_chain(chain_dir)
        if not base_result.get("all_pass"):
            result["error"] = "BASE_CHAIN_VERIFICATION_FAILED"
            return result

        base_final_hash = base_result.get("final_chain_hash")
        base_rpu_count  = len(base_result.get("rpus", []))

        # Steps 4-7: candidate integrity
        integrity = _verify_candidate_integrity(candidate_rpu, base_final_hash)
        result["schema_valid"]     = integrity["schema_valid"]
        result["chain_continuity"] = integrity["chain_continuity"]
        if integrity["fail_signal"]:
            result["error"] = integrity["fail_signal"]["error"]
            return result

        # Step 8: candidate ledger tip
        ledger_check = _verify_candidate_ledger_tip(
            candidate_ledger, integrity["declared_ch"]
        )
        if ledger_check["fail_signal"]:
            result["error"] = ledger_check["fail_signal"]["error"]
            return result

        result["ledger_tip_match"] = True
        result["checked_rpu_count"] = base_rpu_count + 1
        result["all_pass"] = True
        result["status"]   = "PASS"

    except Exception as e:
        result["error"] = f"EXCEPTION: {str(e)}"

    return result


def _bridge_mode_main():
    """Bridge-Mode CLI 진입점 (--candidate-rpu, --candidate-ledger)"""
    parser = _argparse.ArgumentParser(description="ARSS Verifier Bridge-Mode")
    parser.add_argument("--candidate-rpu", required=True,
                        help="candidate RPU .tmp 파일 경로")
    parser.add_argument("--candidate-ledger", required=True,
                        help="candidate ledger .tmp 파일 경로")
    parser.add_argument("--chain-dir", default=DEFAULT_CHAIN_DIR,
                        help="production chain 디렉토리 (기본: evidence/)")
    args = parser.parse_args()

    result = verify_with_candidate(
        chain_dir=Path(args.chain_dir),
        candidate_rpu_path=Path(args.candidate_rpu),
        candidate_ledger_path=Path(args.candidate_ledger)
    )

    print(_json.dumps(result, ensure_ascii=False, indent=2))
    _sys.exit(0 if result["status"] == "PASS" else 1)


# Bridge-Mode 진입 감지: --candidate-rpu 인자 존재 시 bridge mode 실행
if __name__ == "__main__":
    import sys as _entry_check
    if "--candidate-rpu" in _entry_check.argv:
        _bridge_mode_main()
    else:
        main()

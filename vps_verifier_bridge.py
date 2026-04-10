#!/usr/bin/env python3
"""
vps_verifier_bridge.py
ARSS VPS Production Chain Verifier — Bridge v0.2

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

DEFAULT_CHAIN_DIR = "/opt/arss/engine/arss-protocol/ARSS_HUB/04_EVIDENCE/SNAPSHOT_LOG"
BRIDGE_VERSION = "0.2"
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
        "bridge_version": BRIDGE_VERSION,
        "production_schema": PRODUCTION_SCHEMA,
        "chain_dir": str(chain_dir),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "rpus": [],
        "all_pass": False,
        "final_chain_hash": None,
        "ledger_tip_match": None,
        "error": None
    }

    # ── Load ledger ──
    ledger = load_ledger(chain_dir)
    if ledger is None:
        print("WARNING: ledger.json not found — tip validation skipped")
        ledger_tip = None
    else:
        ledger_tip = ledger.get("chain_tip")

    # ── Collect RPU files — uppercase RPU-XXXX.json, numeric sort ──
    try:
        rpu_files = sorted(
            [f for f in chain_dir.iterdir()
             if f.name.startswith("RPU-") and f.name.endswith(".json")
             and f.name != "RPU-ledger.json"],
            key=lambda f: int(f.stem.split("-")[1])
        )
    except (ValueError, IndexError) as e:
        result["error"] = f"RPU filename parse error: {e}"
        return result

    if not rpu_files:
        result["error"] = f"No RPU files (RPU-XXXX.json) found in {chain_dir}"
        return result

    all_pass = True
    prev_chain_hash = None
    final_chain_hash = None
    is_first = True

    for rpu_file in rpu_files:
        rpu = load_json(rpu_file)
        rpu_id = rpu.get("rpu_id", "?")
        event_type = rpu.get("payload", {}).get("event_type", "UNKNOWN")

        rpu_result = {
            "file": rpu_file.name,
            "rpu_id": rpu_id,
            "event_type": event_type,
            "schema_version": None,
            "payload_hash": None,
            "prev_hash": None,
            "chain_hash": None,
            "pass": False
        }

        # Step 1: schema_version check
        schema_ver = rpu.get("schema_version", "")
        schema_ok = schema_ver == PRODUCTION_SCHEMA
        rpu_result["schema_version"] = "PASS" if schema_ok else \
            f"FAIL (got: {schema_ver})"
        if not schema_ok:
            all_pass = False

        # Step 2: payload 존재 확인
        if "payload" not in rpu:
            result["error"] = f"Missing payload in {rpu_file.name}"
            result["rpus"].append(rpu_result)
            return result

        # Step 3: chain 블록 존재 확인
        if "chain" not in rpu:
            result["error"] = f"Missing chain block in {rpu_file.name}"
            result["rpus"].append(rpu_result)
            return result

        payload = rpu["payload"]
        chain_block = rpu["chain"]

        # Step 4: payload_hash 재계산 (보정 1)
        try:
            recomputed_ph = compute_payload_hash(payload)
        except ValueError as e:
            result["error"] = f"payload canonicalization error in " \
                              f"{rpu_file.name}: {e}"
            result["rpus"].append(rpu_result)
            return result

        declared_ph = chain_block.get("payload_hash", "")
        ph_ok = recomputed_ph == declared_ph
        rpu_result["payload_hash"] = "PASS" if ph_ok else "FAIL"
        if not ph_ok:
            all_pass = False

        # Step 5: prev_chain_hash continuity (보정 2 — current_prev 분리)
        declared_prev = chain_block.get("prev_chain_hash", "")
        if is_first:
            # Genesis 처리 명시화
            # 첫 번째 RPU의 prev_chain_hash를 프로덕션 체인 시작점으로 수용.
            # Phase 1: genesis anchor 독립 검증 미구현 — 신뢰 수용 후 진행.
            # TODO: Phase 2 — ARSS-RPU-Production-Spec-v1.0 확정 후
            #        genesis anchor 독립 재계산 검증 추가 예정.
            current_prev = declared_prev
            prev_ok = True
            is_first = False
        else:
            current_prev = prev_chain_hash
            prev_ok = declared_prev == current_prev
        rpu_result["prev_hash"] = "PASS" if prev_ok else "FAIL"
        if not prev_ok:
            all_pass = False

        # Step 6: chain_hash 재계산
        # Genesis 판별: prev_chain_hash가 "GENESIS" 또는 빈값이면 genesis 처리
        is_genesis_rpu = (declared_prev == "GENESIS" or declared_prev == "")
        recomputed_ch = compute_chain_hash(
            current_prev, recomputed_ph, is_genesis=is_genesis_rpu
        )
        declared_ch = chain_block.get("chain_hash", "")
        ch_ok = recomputed_ch == declared_ch
        rpu_result["chain_hash"] = "PASS" if ch_ok else "FAIL"
        if not ch_ok:
            all_pass = False

        rpu_result["pass"] = schema_ok and ph_ok and prev_ok and ch_ok
        result["rpus"].append(rpu_result)

        # [보정 2] prev_chain_hash 갱신 — 계산 완료 후 업데이트
        prev_chain_hash = declared_ch
        final_chain_hash = declared_ch

    result["final_chain_hash"] = final_chain_hash

    # ── Ledger tip cross-validation ──
    if ledger_tip and final_chain_hash:
        tip_match = (ledger_tip == final_chain_hash)
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
        description="ARSS VPS Production Chain Verifier — Bridge v0.2"
    )
    parser.add_argument(
        "--chain-dir",
        default=DEFAULT_CHAIN_DIR,
        help=f"Path to SNAPSHOT_LOG directory (default: {DEFAULT_CHAIN_DIR})"
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Output result as JSON instead of human-readable format"
    )
    args = parser.parse_args()

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


if __name__ == "__main__":
    main()

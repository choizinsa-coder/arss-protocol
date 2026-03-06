#!/usr/bin/env python3
"""
ARSS Reference Verifier v0.1
Official reference implementation of the ARSS RPU Specification v0.1

Usage:
    python verifier.py <samples_dir>
    python verifier.py samples/
"""

import json
import hashlib
import sys
import os
from pathlib import Path


# ─────────────────────────────────────────────
# JCS — JSON Canonicalization Scheme (RFC 8785)
# ─────────────────────────────────────────────

def jcs_serialize(obj) -> str:
    """
    Canonical JSON serialization per RFC 8785.
    - Dict keys sorted by Unicode code point (ascending)
    - No whitespace
    - Null fields excluded at the caller level (not here)
    """
    if isinstance(obj, dict):
        sorted_items = sorted(obj.items(), key=lambda x: x[0])
        inner = ",".join(
            f"{jcs_serialize(k)}:{jcs_serialize(v)}"
            for k, v in sorted_items
        )
        return "{" + inner + "}"
    elif isinstance(obj, list):
        return "[" + ",".join(jcs_serialize(i) for i in obj) + "]"
    elif isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False)
    elif isinstance(obj, bool):
        return "true" if obj else "false"
    elif obj is None:
        return "null"
    elif isinstance(obj, int):
        return str(obj)
    else:
        raise ValueError(f"Unsupported type for JCS: {type(obj)}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_payload_hash(payload: dict) -> str:
    """payload_hash = SHA256(JCS(payload))"""
    canonical = jcs_serialize(payload)
    return sha256_hex(canonical.encode("utf-8"))


def compute_chain_hash(prev_hash: str, payload_hash: str) -> str:
    """chain_hash = SHA256(prev_hash_bytes || 0x00 || payload_hash_bytes)"""
    prev_bytes = bytes.fromhex(prev_hash)
    payload_bytes = bytes.fromhex(payload_hash)
    return sha256_hex(prev_bytes + b'\x00' + payload_bytes)


def compute_genesis_hash(genesis_input: dict) -> str:
    """genesis_hash = SHA256(JCS(genesis_input))"""
    canonical = jcs_serialize(genesis_input)
    return sha256_hex(canonical.encode("utf-8"))


# ─────────────────────────────────────────────
# Verifier
# ─────────────────────────────────────────────

def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_chain(samples_dir: str) -> bool:
    samples = Path(samples_dir)

    print("=" * 60)
    print("ARSS Reference Verifier v0.1")
    print("Spec: ARSS-RPU-Specification-v0.1")
    print("=" * 60)

    # ── Genesis Anchor ──
    genesis_file = samples / "genesis.json"
    if not genesis_file.exists():
        print("ERROR: genesis.json not found")
        return False

    genesis_data = load_json(str(genesis_file))
    recomputed_genesis = compute_genesis_hash(genesis_data["input"])
    declared_genesis = genesis_data["genesis_hash"]

    genesis_ok = recomputed_genesis == declared_genesis
    print(f"\nGenesis Anchor")
    print(f"  declared : {declared_genesis}")
    print(f"  computed : {recomputed_genesis}")
    print(f"  result   : {'OK' if genesis_ok else 'FAIL'}")
    if not genesis_ok:
        print("  ABORT: Genesis hash mismatch")
        return False

    # ── RPU files (sorted) ──
    rpu_files = sorted([
        f for f in samples.iterdir()
        if f.name.startswith("rpu-") and f.name.endswith(".json")
    ])

    if not rpu_files:
        print("ERROR: No RPU files found (expected rpu-*.json)")
        return False

    all_pass = True
    prev_chain_hash = declared_genesis
    final_chain_hash = None

    for rpu_file in rpu_files:
        rpu = load_json(str(rpu_file))
        event_type = rpu.get("event_type", "UNKNOWN")
        rpu_id = rpu.get("rpu_id", "?")

        print(f"\nRPU — {event_type}")
        print(f"  rpu_id   : {rpu_id}")

        # Step 1: payload_hash
        payload = rpu.get("payload", {})
        recomputed_ph = compute_payload_hash(payload)
        declared_ph = rpu.get("payload_hash", "")
        ph_ok = recomputed_ph == declared_ph
        print(f"  payload_hash : {'PASS' if ph_ok else 'FAIL'}")
        if not ph_ok:
            print(f"    declared : {declared_ph}")
            print(f"    computed : {recomputed_ph}")
            all_pass = False

        # Step 2: prev_hash continuity
        declared_prev = rpu.get("prev_hash", "")
        prev_ok = declared_prev == prev_chain_hash
        print(f"  prev_hash    : {'PASS' if prev_ok else 'FAIL'}")
        if not prev_ok:
            print(f"    expected : {prev_chain_hash}")
            print(f"    declared : {declared_prev}")
            all_pass = False

        # Step 3: chain_hash
        recomputed_ch = compute_chain_hash(prev_chain_hash, recomputed_ph)
        declared_ch = rpu.get("chain_hash", "")
        ch_ok = recomputed_ch == declared_ch
        print(f"  chain_hash   : {'PASS' if ch_ok else 'FAIL'}")
        if not ch_ok:
            print(f"    declared : {declared_ch}")
            print(f"    computed : {recomputed_ch}")
            all_pass = False

        # Step 4: HACS signature (presence check — full verification requires public key)
        if event_type == "HUMAN_APPROVAL_RECORDED":
            hacs = payload.get("hacs_signature", "")
            hacs_present = bool(hacs)
            print(f"  hacs_sig     : {'PRESENT' if hacs_present else 'MISSING'} "
                  f"(full verification requires approver public key)")

        prev_chain_hash = declared_ch
        final_chain_hash = declared_ch

    # ── Result ──
    print("\n" + "=" * 60)
    if all_pass:
        print("RESULT: ALL PASS")
        print(f"\nFinal chain hash:")
        print(f"  {final_chain_hash}")
        print("\nGovernance is not declared. It is recomputed.")
    else:
        print("RESULT: FAIL — see details above")

    print("=" * 60)
    return all_pass


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python verifier.py <samples_dir>")
        print("Example: python verifier.py samples/")
        sys.exit(1)

    samples_dir = sys.argv[1]
    if not os.path.isdir(samples_dir):
        print(f"ERROR: '{samples_dir}' is not a directory")
        sys.exit(1)

    success = verify_chain(samples_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

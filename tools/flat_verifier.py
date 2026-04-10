#!/usr/bin/env python3
"""
flat_verifier.py — AIBA Flat Schema Verifier
대상: SNAPSHOT_LOG/rpu-0024.json ~ rpu-0030.json
설계: 도미(Domi) Phase 3 Governance Lock
EAG: EAG-1/EAG-2 비오(Joshua) 승인 2026-04-10
"""

import argparse
import hashlib
import json
import os
import sys

REQUIRED_FIELDS = ["rpu_id", "timestamp", "actor_id", "event_type", "content", "prev_hash", "hash"]


def canonical_json(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def compute_hash(rpu: dict) -> str:
    payload = {k: rpu[k] for k in ["rpu_id", "timestamp", "actor_id", "event_type", "content", "prev_hash"]}
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def parse_range(range_str: str):
    parts = range_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid range format: {range_str}")
    return parts[0], parts[1]


def load_rpus(input_dir: str, start: str, end: str):
    start_num = int(start.split("-")[1])
    end_num = int(end.split("-")[1])
    rpus = []
    for i in range(start_num, end_num + 1):
        filename = f"rpu-{i:04d}.json"
        filepath = os.path.join(input_dir, filename)
        if not os.path.exists(filepath):
            print(f"[WARN] File not found: {filepath}", file=sys.stderr)
            continue
        with open(filepath, "r") as f:
            rpus.append((filename, json.load(f)))
    return rpus


def validate(input_dir: str, range_str: str) -> dict:
    start, end = parse_range(range_str)
    rpus = load_rpus(input_dir, start, end)

    if not rpus:
        return {
            "mode": "flat",
            "validated_count": 0,
            "chain_integrity": False,
            "hash_match": False,
            "importable": False,
            "reason": "no files found"
        }

    field_ok = True
    hash_ok = True
    chain_ok = True
    prev_hash = None

    for filename, rpu in rpus:
        # Step 1: 필드 검증
        missing = [f for f in REQUIRED_FIELDS if f not in rpu]
        if missing:
            print(f"[FAIL] {filename} missing fields: {missing}", file=sys.stderr)
            field_ok = False
            continue

        # Step 2: hash 검증
        computed = compute_hash(rpu)
        if computed != rpu["hash"]:
            print(f"[FAIL] {filename} hash mismatch: expected {computed}, got {rpu['hash']}", file=sys.stderr)
            hash_ok = False

        # Step 3: chain 연결 검증
        if prev_hash is not None and rpu["prev_hash"] != prev_hash:
            print(f"[FAIL] {filename} chain break: prev_hash mismatch", file=sys.stderr)
            chain_ok = False

        prev_hash = rpu["hash"]

    return {
        "mode": "flat",
        "validated_count": len(rpus),
        "chain_integrity": chain_ok,
        "hash_match": hash_ok,
        "importable": False,
        "reason": "missing canonical chain structure — flat schema not compatible with canonical verifier"
    }


def main():
    parser = argparse.ArgumentParser(description="AIBA Flat Schema Verifier")
    parser.add_argument("--input-dir", required=True, help="Directory containing flat schema RPU files")
    parser.add_argument("--range", required=True, help="RPU range e.g. rpu-0024:rpu-0030")
    args = parser.parse_args()

    result = validate(args.input_dir, args.range)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if not result["hash_match"] or not result["chain_integrity"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

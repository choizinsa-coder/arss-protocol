"""
ARSS Reference Verifier — Test Suite
Tests the reference implementation against the sample chain.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))
from verifier import (
    jcs_serialize,
    compute_payload_hash,
    compute_chain_hash,
    compute_genesis_hash,
    verify_chain,
)

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "../../samples")
EXPECTED_HASH_FILE = os.path.join(os.path.dirname(__file__), "../../tests/expected-chain-hash.txt")
EXPECTED_FINAL_HASH = "3de51ae75318d7493fe7850046df41920e92362630a50a1a63af951adadf7763"


# ── Unit Tests ────────────────────────────────────────

class TestJCS:
    def test_dict_sorted(self):
        result = jcs_serialize({"z": 1, "a": 2})
        assert result == '{"a":2,"z":1}'

    def test_nested(self):
        result = jcs_serialize({"b": {"z": 1, "a": 2}, "a": 3})
        assert result == '{"a":3,"b":{"a":2,"z":1}}'

    def test_string(self):
        assert jcs_serialize("hello") == '"hello"'

    def test_list(self):
        assert jcs_serialize([3, 1, 2]) == "[3,1,2]"

    def test_bool(self):
        assert jcs_serialize(True) == "true"
        assert jcs_serialize(False) == "false"

    def test_null(self):
        assert jcs_serialize(None) == "null"


class TestHashing:
    def test_chain_hash_formula(self):
        prev = "0" * 64
        payload = "a" * 64
        import hashlib
        expected = hashlib.sha256(
            bytes.fromhex(prev) + b'\x00' + bytes.fromhex(payload)
        ).hexdigest()
        assert compute_chain_hash(prev, payload) == expected

    def test_genesis_hash_deterministic(self):
        genesis_input = {
            "chain_id": "test-chain-id",
            "protocol": "ARSS",
            "timestamp": "2026-01-01T00:00:00.000000Z",
            "version": "1.0"
        }
        h1 = compute_genesis_hash(genesis_input)
        h2 = compute_genesis_hash(genesis_input)
        assert h1 == h2

    def test_payload_hash_deterministic(self):
        payload = {"event_type": "AI_OUTPUT_GENERATED", "model_id": "test"}
        h1 = compute_payload_hash(payload)
        h2 = compute_payload_hash(payload)
        assert h1 == h2


# ── Integration Test ──────────────────────────────────

class TestSampleChain:
    def test_full_chain_passes(self, capsys):
        result = verify_chain(SAMPLES_DIR)
        assert result is True

    def test_expected_final_hash(self, capsys):
        """
        Core test: recomputation must produce the known-good hash.
        This is the ARSS Independence Test.
        """
        verify_chain(SAMPLES_DIR)
        captured = capsys.readouterr()
        assert EXPECTED_FINAL_HASH in captured.out, (
            f"Expected final hash {EXPECTED_FINAL_HASH} not found in output.\n"
            f"Output was:\n{captured.out}"
        )

    def test_expected_hash_file_matches(self):
        """The expected hash file must match the hardcoded constant."""
        with open(EXPECTED_HASH_FILE, "r") as f:
            file_hash = f.read().strip()
        assert file_hash == EXPECTED_FINAL_HASH

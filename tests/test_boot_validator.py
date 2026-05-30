"""
test_boot_validator.py
source: tools/session_context_gen/boot_validator.py
P4-C2 (S174): SESSION_BOOT_PENDING stub → Fixture Layer 실제 테스트 작성
원칙: 실제 BOOT ≠ 테스트 입력 — tempfile 기반 Fixture Layer 사용

구조:
  BV-1: _validate_boot_input_files — full 미존재 → FAIL/stop_signal
  BV-2: _validate_boot_input_files — boot 미존재 → FAIL/stop_signal
  BV-3: _validate_boot_required_keys — 필수 키 누락 → FAIL
  BV-4: _check_chain_tip_match — tip 불일치 → failure 등재
  BV-5: _check_boot_is_not_ssot — boot_is_ssot=True → FAIL
  BV-6: validate_and_mutate_state 정상 path — PASS 반환
  BV-7: validate_and_mutate_state — SHA256 불일치 → FAIL
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.boot_validator import (
    _validate_boot_input_files,
    _validate_boot_required_keys,
    _check_chain_tip_match,
    _check_boot_is_not_ssot,
    validate_and_mutate_state,
    REQUIRED_BOOT_KEYS,
)


# ── Fixture 헬퍼 ────────────────────────────────────────────────────────────

def _make_minimal_full() -> dict:
    """최소 유효 full_context fixture (SESSION_BOOT 파일 비의존)."""
    return {
        "chain": {"tip": "abc1234", "session": 174},
        "pending_tasks": [],
        "state_events": [],
        "lessons": [],
        "canonical_rules": {},
        "decisions": [],
        "archive_refs": {},
        "boot_meta": {"boot_is_ssot": False},
    }


def _make_minimal_boot(full_sha256: str) -> dict:
    """최소 유효 boot_context fixture — archive_refs에 full SHA256 포함."""
    return {
        "boot_meta": {"boot_is_ssot": False, "validator_result": "PENDING"},
        "chain": {"tip": "abc1234", "session": 174},
        "pending_tasks": [],
        "state_events": [],
        "lessons": [],
        "canonical_rules": {},
        "decisions": [],
        "archive_refs": {
            "full_context": {"sha256": full_sha256}
        },
    }


def _write_json_tmp(data: dict, f) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2)
    f.write(content.encode("utf-8"))
    f.flush()


# ── BV-1: full 파일 미존재 → FAIL/stop_signal ──────────────────────────────

class TestBV1_FullFileMissing(unittest.TestCase):
    def test_BV1_full_not_found_returns_fail(self):
        """full 파일 미존재 → FAIL + stop_signal=True (RULE-8 failure path)"""
        result = _validate_boot_input_files("/nonexistent/full.json", "/nonexistent/boot.json")
        self.assertIsNotNone(result)
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result["stop_signal"])
        self.assertIn("FULL file not found", result["failures"][0])


# ── BV-2: boot 파일 미존재 → FAIL/stop_signal ─────────────────────────────

class TestBV2_BootFileMissing(unittest.TestCase):
    def test_BV2_boot_not_found_returns_fail(self):
        """full 존재 + boot 미존재 → FAIL + stop_signal=True (RULE-8 failure path)"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as full_f:
            _write_json_tmp(_make_minimal_full(), full_f)
            full_path = full_f.name
        result = _validate_boot_input_files(full_path, "/nonexistent/boot.json")
        self.assertIsNotNone(result)
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result["stop_signal"])
        self.assertIn("BOOT file not found", result["failures"][0])


# ── BV-3: 필수 키 누락 → FAIL ──────────────────────────────────────────────

class TestBV3_RequiredKeysMissing(unittest.TestCase):
    def test_BV3_missing_required_key_returns_fail(self):
        """BOOT 필수 키 누락 → FAIL (RULE-8 failure path)"""
        incomplete_boot = {"boot_meta": {}, "chain": {}}  # 나머지 키 없음
        result = _validate_boot_required_keys(incomplete_boot)
        self.assertIsNotNone(result)
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result["stop_signal"])
        self.assertIn("missing required keys", result["failures"][0])

    def test_BV3_all_required_keys_present_returns_none(self):
        """필수 키 전부 존재 → None 반환 (정상 path)"""
        full_boot = {k: {} for k in REQUIRED_BOOT_KEYS}
        result = _validate_boot_required_keys(full_boot)
        self.assertIsNone(result)


# ── BV-4: chain tip 불일치 → failure 등재 ─────────────────────────────────

class TestBV4_ChainTipMismatch(unittest.TestCase):
    def test_BV4_chain_tip_mismatch_adds_failure(self):
        """full/boot chain.tip 불일치 → failures에 등재 (RULE-8 failure path)"""
        full = {"chain": {"tip": "aaa111"}}
        boot = {"chain": {"tip": "bbb222"}}
        failures, results = [], {}
        _check_chain_tip_match(full, boot, failures, results)
        self.assertFalse(results["CHECK-2_chain_tip"]["pass"])
        self.assertTrue(any("chain.tip mismatch" in f for f in failures))

    def test_BV4_chain_tip_match_no_failure(self):
        """full/boot chain.tip 일치 → failure 없음 (정상 path)"""
        full = {"chain": {"tip": "abc1234"}}
        boot = {"chain": {"tip": "abc1234"}}
        failures, results = [], {}
        _check_chain_tip_match(full, boot, failures, results)
        self.assertTrue(results["CHECK-2_chain_tip"]["pass"])
        self.assertEqual(failures, [])


# ── BV-5: boot_is_ssot=True → FAIL ────────────────────────────────────────

class TestBV5_BootIsSsot(unittest.TestCase):
    def test_BV5_boot_is_ssot_true_adds_failure(self):
        """boot_is_ssot=True → HARD STOP failure 등재 (RULE-8 failure path)"""
        boot = {"boot_meta": {"boot_is_ssot": True}}
        failures, results = [], {}
        _check_boot_is_not_ssot(boot, failures, results)
        self.assertFalse(results["CHECK-5_boot_not_ssot"]["pass"])
        self.assertTrue(any("boot_is_ssot" in f for f in failures))

    def test_BV5_boot_is_ssot_false_no_failure(self):
        """boot_is_ssot=False → failure 없음 (정상 path)"""
        boot = {"boot_meta": {"boot_is_ssot": False}}
        failures, results = [], {}
        _check_boot_is_not_ssot(boot, failures, results)
        self.assertTrue(results["CHECK-5_boot_not_ssot"]["pass"])
        self.assertEqual(failures, [])


# ── BV-6: validate_and_mutate_state 정상 path ─────────────────────────────

class TestBV6_ValidateAndMutatePass(unittest.TestCase):
    def test_BV6_valid_pair_returns_pass(self):
        """유효한 full+boot 쌍 → overall=PASS (정상 path)"""
        full_data = _make_minimal_full()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as full_f:
            _write_json_tmp(full_data, full_f)
            full_path = full_f.name

        full_sha256 = hashlib.sha256(Path(full_path).read_bytes()).hexdigest()
        boot_data = _make_minimal_boot(full_sha256)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as boot_f:
            _write_json_tmp(boot_data, boot_f)
            boot_path = boot_f.name

        result = validate_and_mutate_state(full_path, boot_path)
        self.assertEqual(result["overall"], "PASS")
        self.assertFalse(result["stop_signal"])


# ── BV-7: SHA256 불일치 → FAIL ─────────────────────────────────────────────

class TestBV7_Sha256Mismatch(unittest.TestCase):
    def test_BV7_sha256_mismatch_returns_fail(self):
        """archive_refs SHA256 불일치 → overall=FAIL (RULE-8 failure path)"""
        full_data = _make_minimal_full()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as full_f:
            _write_json_tmp(full_data, full_f)
            full_path = full_f.name

        # 잘못된 SHA256으로 boot 생성
        boot_data = _make_minimal_boot("0000000000000000000000000000000000000000000000000000000000000000")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as boot_f:
            _write_json_tmp(boot_data, boot_f)
            boot_path = boot_f.name

        result = validate_and_mutate_state(full_path, boot_path)
        self.assertEqual(result["overall"], "FAIL")
        self.assertTrue(result["stop_signal"])
        self.assertTrue(any("SHA256" in f for f in result["failures"]))


if __name__ == "__main__":
    unittest.main()

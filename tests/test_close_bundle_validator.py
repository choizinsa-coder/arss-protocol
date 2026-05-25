"""
test_close_bundle_validator.py
AIBA Context Gateway — Close Bundle Validator 전용 테스트
SSOT: RULE-8 매핑 (tools/context_gateway/close_bundle_validator.py)
S153 Code Health Remediation Phase 1
RULE-6 fix 검증 포함: fsync_ok degraded 신호 테스트
"""

import sys
import json
import hashlib
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.context_gateway.close_bundle_validator import (
    CloseBundleInput,
    ValidationResult,
    validate_close_bundle,
    make_stale_decision,
    make_commit_decision,
    _fsync_read_hash,
)


def _write_json(path: Path, data: dict) -> str:
    content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()


def _make_bundle(tmp: str, session: int, ts: str, context_hash=None, blocking_flags=None):
    final_path = Path(tmp) / f"SESSION_CONTEXT_S{session}_FINAL.json"
    actual_hash = _write_json(final_path, {"session": session})
    context_hash = context_hash or actual_hash

    ptr = {
        "current_session": session, "current_file_id": final_path.name,
        "session_count": session, "context_hash": context_hash,
        "updated_at": ts, "updated_by": "caddy", "previous_pointer_hash": "GENESIS",
    }
    ptr_hash = hashlib.sha256(
        json.dumps(ptr, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    mfst = {
        "manifest_session": session, "context_hash": context_hash,
        "pointer_hash": ptr_hash, "generated_at": ts, "generated_by": "caddy",
        "projection_status": "fresh", "shard_status_summary": {},
        "role_projection_status": {"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        "blocking_flags": blocking_flags or [],
    }
    if blocking_flags:
        mfst["projection_status"] = "stale"
    return CloseBundleInput(session=session, final_path=final_path, pointer=ptr, manifest=mfst)


class TestCloseBundleValidator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.session = 153
        self.ts = "2026-05-25T12:00:00+09:00"

    def test_T5_valid_close_bundle_passes(self):
        bundle = _make_bundle(self.tmp, self.session, self.ts)
        result = validate_close_bundle(bundle)
        self.assertTrue(result.passed, f"errors: {result.errors}")
        self.assertIsNotNone(result.context_hash)

    def test_T6_missing_final_file_fails(self):
        bundle = _make_bundle(self.tmp, self.session, self.ts)
        bundle.final_path = Path(self.tmp) / "NONEXISTENT.json"
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("FINAL_FILE_MISSING" in e for e in result.errors))

    def test_T7_context_hash_mismatch_fails(self):
        bundle = _make_bundle(self.tmp, self.session, self.ts, context_hash="a" * 64)
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("HASH_MISMATCH" in e for e in result.errors))

    def test_T8_session_count_mismatch_fails(self):
        bundle = _make_bundle(self.tmp, self.session, self.ts)
        bundle.pointer["current_session"] = 999
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("SESSION_MISMATCH" in e for e in result.errors))

    def test_T9_blocking_flags_fails(self):
        bundle = _make_bundle(self.tmp, self.session, self.ts, blocking_flags=["STALE_PROJECTION"])
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("BLOCKING_FLAGS" in e for e in result.errors))

    def test_T9b_fsync_read_hash_returns_tuple(self):
        """RULE-6 fix 검증: _fsync_read_hash는 (hash, fsync_ok) 튜플 반환"""
        path = Path(self.tmp) / "test_fsync.json"
        data = {"test": "fsync_check"}
        expected_hash = _write_json(path, data)
        result = _fsync_read_hash(path)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        computed, fsync_ok = result
        self.assertEqual(expected_hash, computed)
        self.assertIsInstance(fsync_ok, bool)

    def test_T9c_fsync_read_hash_missing_file(self):
        """존재하지 않는 파일 — (None, False) 반환"""
        path = Path(self.tmp) / "NONEXISTENT.json"
        computed, fsync_ok = _fsync_read_hash(path)
        self.assertIsNone(computed)
        self.assertFalse(fsync_ok)

    def test_stale_decision_no_recovery(self):
        result = ValidationResult(passed=False, errors=["TEST_ERROR"])
        decision = make_stale_decision(result)
        self.assertEqual(decision["decision"], "STALE")
        self.assertFalse(decision["recovery_attempted"])

    def test_commit_decision_has_hash(self):
        result = ValidationResult(passed=True, context_hash="abc123")
        decision = make_commit_decision(result)
        self.assertEqual(decision["decision"], "COMMIT")
        self.assertEqual(decision["context_hash"], "abc123")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""
test_context_writer.py
AIBA Context Gateway — Context Writer 전용 테스트
SSOT: RULE-8 매핑 (tools/context_gateway/context_writer.py)
S153 Code Health Remediation Phase 1
RULE-6 fix 검증 포함: fsync_ok degraded 신호 + commit 결과 테스트
"""

import sys
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.context_gateway.context_writer import (
    execute_close_bundle,
    get_writer_status,
    _fsync_write,
)
from tools.context_gateway.write_tier_policy import WriteAction, assert_tier1_required


def _write_json(path: Path, data: dict) -> str:
    content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()


class TestContextWriter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.session = 153

    def _create_final(self):
        final_path = Path(self.tmp) / f"SESSION_CONTEXT_S{self.session}_FINAL.json"
        _write_json(final_path, {"session": self.session, "status": "FINAL"})
        return final_path

    def test_T10_successful_commit(self):
        final_path = self._create_final()
        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path):
            result = execute_close_bundle(session=self.session, final_path=final_path)

        self.assertEqual(result["decision"], "COMMIT", f"errors: {result.get('errors')}")
        self.assertTrue(result.get("pointer_updated"))
        self.assertTrue(result.get("manifest_fresh"))

    def test_T11_missing_final_returns_stale(self):
        missing_path = Path(self.tmp) / "NONEXISTENT_FINAL.json"
        result = execute_close_bundle(session=self.session, final_path=missing_path)
        self.assertEqual(result["decision"], "STALE")
        self.assertFalse(result.get("recovery_attempted", True))

    def test_T12_tier1_policy_enforced(self):
        assert_tier1_required(WriteAction.CLOSE_BUNDLE_COMMIT)

    def test_T13_pointer_written_correctly(self):
        final_path = self._create_final()
        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path):
            result = execute_close_bundle(session=self.session, final_path=final_path)

        self.assertEqual(result["decision"], "COMMIT")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        self.assertEqual(pointer["current_session"], self.session)
        self.assertEqual(pointer["final_file"], final_path.name)

    def test_T14_manifest_fresh_after_commit(self):
        final_path = self._create_final()
        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path):
            result = execute_close_bundle(session=self.session, final_path=final_path)

        self.assertEqual(result["decision"], "COMMIT")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["projection_status"], "fresh")
        self.assertEqual(manifest["blocking_flags"], [])
        self.assertEqual(manifest["phase"], "C")

    def test_fsync_write_returns_bool(self):
        """RULE-6 fix 검증: _fsync_write는 bool 반환"""
        path = Path(self.tmp) / "fsync_test.json"
        result = _fsync_write(path, '{"test": true}')
        self.assertIsInstance(result, bool)
        self.assertTrue(path.exists())

    def test_fsync_write_degraded_signal_on_failure(self):
        """RULE-6 fix 검증: fsync 실패 시 False 반환 (성공으로 오인 방지)"""
        path = Path(self.tmp) / "fsync_degraded.json"

        import os
        original_fsync = os.fsync

        def failing_fsync(fd):
            raise OSError("simulated fsync failure")

        with patch("tools.context_gateway.context_writer.os.fsync", failing_fsync):
            result = _fsync_write(path, '{"test": "degraded"}')

        self.assertFalse(result)
        # 파일은 쓰였어야 함
        self.assertTrue(path.exists())

    def test_writer_status_structure(self):
        status = get_writer_status()
        self.assertEqual(status["tier"], "TIER_1")
        self.assertFalse(status["auto_recovery"])
        self.assertTrue(status["fail_closed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

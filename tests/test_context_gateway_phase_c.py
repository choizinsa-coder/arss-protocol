"""
test_context_gateway_phase_c.py
AIBA Context Gateway — Phase C Test Suite
SSOT: Domi Phase C Design / EAG Approved (S153)
제니 TRUST-ADVISORY: fsync 보장 + 해시 검증 시점 정합성 테스트 포함

테스트 구성:
  [write_tier_policy] T-1 ~ T-4
  [close_bundle_validator] T-5 ~ T-9
  [context_writer] T-10 ~ T-14
  [integration] T-15 ~ T-16
"""

import sys
import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.context_gateway.write_tier_policy import (
    WriteTier,
    WriteAction,
    Tier2Action,
    classify_write_action,
    classify_tier2_action,
    classify_path,
    assert_tier1_required,
    assert_tier2_safe,
    get_policy_summary,
)
from tools.context_gateway.close_bundle_validator import (
    CloseBundleInput,
    ValidationResult,
    validate_close_bundle,
    make_stale_decision,
    make_commit_decision,
    _fsync_read_hash,
)
from tools.context_gateway.context_writer import (
    execute_close_bundle,
    get_writer_status,
    ContextWriter,
)


# ── 헬퍼 ───────────────────────────────────────────────────────────────────

def _make_final_content(session: int) -> dict:
    return {"session": session, "status": "FINAL", "data": "test_content"}


def _write_json(path: Path, data: dict) -> str:
    """JSON 파일 쓰기 후 SHA256 반환"""
    content = json.dumps(data, ensure_ascii=False, indent=2)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode()).hexdigest()


def _make_pointer(session: int, context_hash: str, ts: str) -> dict:
    return {
        "current_session": session,
        "current_file_id": f"SESSION_CONTEXT_S{session}_FINAL.json",
        "session_count": session,
        "context_hash": context_hash,
        "updated_at": ts,
        "updated_by": "caddy",
        "previous_pointer_hash": "GENESIS",
    }


def _make_manifest(session: int, context_hash: str, pointer_hash: str, ts: str) -> dict:
    return {
        "manifest_session": session,
        "context_hash": context_hash,
        "pointer_hash": pointer_hash,
        "generated_at": ts,
        "generated_by": "caddy",
        "projection_status": "fresh",
        "shard_status_summary": {},
        "role_projection_status": {"domi": "fresh", "jeni": "fresh", "caddy": "fresh"},
        "blocking_flags": [],
    }


# ── write_tier_policy 테스트 ─────────────────────────────────────────────────

class TestWriteTierPolicy(unittest.TestCase):

    # T-1: 모든 WriteAction은 Tier 1
    def test_T1_all_write_actions_are_tier1(self):
        for action in WriteAction:
            tier = classify_write_action(action)
            self.assertEqual(tier, WriteTier.TIER_1, f"{action.value} should be TIER_1")

    # T-2: 모든 Tier2Action은 Tier 2
    def test_T2_all_tier2_actions_are_tier2(self):
        for action in Tier2Action:
            tier = classify_tier2_action(action)
            self.assertEqual(tier, WriteTier.TIER_2, f"{action.value} should be TIER_2")

    # T-3: 파일 경로 Tier 판정
    def test_T3_path_classification(self):
        tier1_paths = [
            Path("/opt/arss/SESSION_CONTEXT_S153_FINAL.json"),
            Path("/opt/arss/SESSION_CONTEXT_POINTER.json"),
            Path("/opt/arss/SESSION_CONTEXT_STALE_MANIFEST.json"),
        ]
        tier2_paths = [
            Path("/opt/arss/sandbox/draft_session.json"),
            Path("/opt/arss/tmp/check_result.json"),
            Path("/opt/arss/preflight/precheck.json"),
            Path("/opt/arss/result_draft.json"),
            Path("/opt/arss/mismatch_note.json"),
        ]
        unknown_paths = [
            Path("/opt/arss/some_other_file.json"),
            Path("/opt/arss/tools/my_tool.py"),
        ]

        for p in tier1_paths:
            self.assertEqual(classify_path(p), WriteTier.TIER_1, f"{p.name}")
        for p in tier2_paths:
            self.assertEqual(classify_path(p), WriteTier.TIER_2, f"{p.name}")
        for p in unknown_paths:
            self.assertEqual(classify_path(p), WriteTier.UNKNOWN, f"{p.name}")

    # T-4: Tier 경계 강제 — assert 함수
    def test_T4_assert_functions(self):
        # Tier 1 assert — 정상 통과
        assert_tier1_required(WriteAction.CLOSE_BUNDLE_COMMIT)

        # Tier 2 safe — sandbox 경로 통과
        safe_path = Path("/opt/arss/sandbox/test_draft.json")
        assert_tier2_safe(safe_path)

        # Tier 2 safe — Tier 1 경로 차단
        tier1_path = Path("/opt/arss/SESSION_CONTEXT_S153_FINAL.json")
        with self.assertRaises(RuntimeError):
            assert_tier2_safe(tier1_path)

        # Tier 2 safe — UNKNOWN 경로 차단
        unknown_path = Path("/opt/arss/unknown_file.json")
        with self.assertRaises(RuntimeError):
            assert_tier2_safe(unknown_path)

    def test_policy_summary_structure(self):
        summary = get_policy_summary()
        self.assertIn("tier_1", summary)
        self.assertIn("tier_2", summary)
        self.assertIn("principle", summary)


# ── close_bundle_validator 테스트 ─────────────────────────────────────────────

class TestCloseBundleValidator(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.session = 153
        self.ts = "2026-05-25T12:00:00+09:00"

    def _make_bundle(self, session=None, context_hash=None, ts=None, blocking_flags=None):
        session = session or self.session
        ts = ts or self.ts
        final_path = Path(self.tmp) / f"SESSION_CONTEXT_S{session}_FINAL.json"
        actual_hash = _write_json(final_path, _make_final_content(session))
        context_hash = context_hash or actual_hash

        ptr = _make_pointer(session, context_hash, ts)
        ptr_hash = hashlib.sha256(
            json.dumps(ptr, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        mfst = _make_manifest(session, context_hash, ptr_hash, ts)
        if blocking_flags is not None:
            mfst["blocking_flags"] = blocking_flags
            if blocking_flags:
                mfst["projection_status"] = "stale"

        return CloseBundleInput(session=session, final_path=final_path, pointer=ptr, manifest=mfst)

    # T-5: 정상 Close Bundle — PASS
    def test_T5_valid_close_bundle_passes(self):
        bundle = self._make_bundle()
        result = validate_close_bundle(bundle)
        self.assertTrue(result.passed, f"errors: {result.errors}")
        self.assertIsNotNone(result.context_hash)

    # T-6: FINAL 파일 없음 → FAIL
    def test_T6_missing_final_file_fails(self):
        bundle = self._make_bundle()
        bundle.final_path = Path(self.tmp) / "NONEXISTENT.json"
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("FINAL_FILE_MISSING" in e for e in result.errors))

    # T-7: context_hash 불일치 → FAIL
    def test_T7_context_hash_mismatch_fails(self):
        bundle = self._make_bundle(context_hash="a" * 64)
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("HASH_MISMATCH" in e for e in result.errors))

    # T-8: session_count 불일치 → FAIL
    def test_T8_session_count_mismatch_fails(self):
        bundle = self._make_bundle()
        bundle.pointer["current_session"] = 999  # 의도적 불일치
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("SESSION_MISMATCH" in e for e in result.errors))

    # T-9: blocking_flags 존재 → FAIL (Fail-Closed)
    def test_T9_blocking_flags_fails(self):
        bundle = self._make_bundle(blocking_flags=["STALE_PROJECTION"])
        result = validate_close_bundle(bundle)
        self.assertFalse(result.passed)
        self.assertTrue(any("BLOCKING_FLAGS" in e for e in result.errors))

    # T-9b: fsync_read_hash — 실제 파일 hash 일치
    def test_T9b_fsync_read_hash_correct(self):
        """제니 TRUST-ADVISORY: fsync 보장 후 hash 검증 정합성"""
        path = Path(self.tmp) / "test_fsync.json"
        data = {"test": "fsync_check"}
        expected_hash = _write_json(path, data)
        computed = _fsync_read_hash(path)
        self.assertEqual(expected_hash, computed)

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


# ── context_writer 테스트 ────────────────────────────────────────────────────

class TestContextWriter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.session = 153

    def _create_final(self):
        final_path = Path(self.tmp) / f"SESSION_CONTEXT_S{self.session}_FINAL.json"
        _write_json(final_path, _make_final_content(self.session))
        return final_path

    def _patch_paths(self, pointer_path, manifest_path):
        """pointer_manager / manifest_manager 경로를 tmp로 패치"""
        return [
            patch("tools.context_gateway.context_writer.POINTER_PATH" if False else
                  "tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path),
            patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path),
            patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path),
        ]

    # T-10: 정상 commit — COMMIT 반환
    def test_T10_successful_commit(self):
        final_path = self._create_final()
        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path):
            result = execute_close_bundle(
                session=self.session,
                final_path=final_path,
            )

        self.assertEqual(result["decision"], "COMMIT", f"errors: {result.get('errors')}")
        self.assertTrue(result.get("pointer_updated"))
        self.assertTrue(result.get("manifest_fresh"))

    # T-11: FINAL 파일 없음 → STALE
    def test_T11_missing_final_returns_stale(self):
        missing_path = Path(self.tmp) / "NONEXISTENT_FINAL.json"
        result = execute_close_bundle(session=self.session, final_path=missing_path)
        self.assertEqual(result["decision"], "STALE")
        self.assertFalse(result.get("recovery_attempted", True))

    # T-12: Tier 1 정책 — assert_tier1_required 통과
    def test_T12_tier1_policy_enforced(self):
        """context_writer는 반드시 Tier 1 정책을 통과해야 함"""
        from tools.context_gateway.write_tier_policy import WriteAction, assert_tier1_required
        # CLOSE_BUNDLE_COMMIT은 Tier 1 — 예외 없음
        assert_tier1_required(WriteAction.CLOSE_BUNDLE_COMMIT)

    # T-13: commit 후 POINTER 파일 정합성
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
        self.assertTrue(pointer_path.exists())
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        self.assertEqual(pointer["current_session"], self.session)
        self.assertEqual(pointer["current_file_id"], final_path.name)

    # T-14: commit 후 MANIFEST fresh 상태
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
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["projection_status"], "fresh")
        self.assertEqual(manifest["blocking_flags"], [])
        self.assertEqual(manifest["phase"], "C")

    def test_writer_status_structure(self):
        status = get_writer_status()
        self.assertEqual(status["tier"], "TIER_1")
        self.assertFalse(status["auto_recovery"])
        self.assertTrue(status["fail_closed"])


# ── 통합 테스트 ────────────────────────────────────────────────────────────

class TestPhaseC_Integration(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.session = 153

    # T-15: 3-way consistency — POINTER / MANIFEST / FINAL hash 일치 확인
    def test_T15_three_way_consistency_after_commit(self):
        final_path = Path(self.tmp) / f"SESSION_CONTEXT_S{self.session}_FINAL.json"
        _write_json(final_path, _make_final_content(self.session))

        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path):
            result = execute_close_bundle(session=self.session, final_path=final_path)

        self.assertEqual(result["decision"], "COMMIT")

        # 실제 파일 hash 재계산
        actual_hash = hashlib.sha256(final_path.read_bytes()).hexdigest()
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 3-way 일치 확인
        self.assertEqual(pointer["context_hash"], actual_hash)
        self.assertEqual(manifest["context_hash"], actual_hash)
        self.assertEqual(result["context_hash"], actual_hash)

    # T-16: Fail-Closed — hash 불일치 시 STALE, POINTER 불변
    def test_T16_fail_closed_on_hash_mismatch(self):
        """
        3-way check 실패 시:
        1. decision == STALE
        2. recovery_attempted == False
        3. POINTER 변경 없음
        """
        final_path = Path(self.tmp) / f"SESSION_CONTEXT_S{self.session}_FINAL.json"
        _write_json(final_path, _make_final_content(self.session))

        pointer_path = Path(self.tmp) / "SESSION_CONTEXT_POINTER.json"
        manifest_path = Path(self.tmp) / "SESSION_CONTEXT_STALE_MANIFEST.json"

        # FINAL 파일 내용을 commit 후 변경하여 hash 불일치 유도
        # → create_pointer 시점의 hash와 validate 시점 hash가 다름
        original_create = None

        import tools.context_gateway.pointer_manager as pm

        original_create = pm.create_pointer

        def tampered_create_pointer(session, file_id, context_path, updated_by, previous_pointer):
            ptr = original_create(session, file_id, context_path, updated_by, previous_pointer)
            ptr["context_hash"] = "b" * 64  # 의도적 hash 오염
            return ptr

        with patch("tools.context_gateway.pointer_manager.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.manifest_manager.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.POINTER_PATH", pointer_path), \
             patch("tools.context_gateway.context_writer.MANIFEST_PATH", manifest_path), \
             patch("tools.context_gateway.context_writer.create_pointer", tampered_create_pointer):
            result = execute_close_bundle(session=self.session, final_path=final_path)

        self.assertEqual(result["decision"], "STALE")
        self.assertFalse(result.get("recovery_attempted", True))
        self.assertFalse(result.get("pointer_changed", True))


if __name__ == "__main__":
    unittest.main(verbosity=2)

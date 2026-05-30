"""
test_boot_generator.py
source: tools/session_context_gen/boot_generator.py
P4-C2 (S174): SESSION_BOOT_PENDING stub → Fixture Layer 실제 테스트 작성
원칙: tempfile + dict fixture — 실제 SESSION_BOOT 파일 비의존

구조:
  BG-1: is_active_task — ACTIVE 상태 → True (정상 path)
  BG-2: is_active_task — COMPLETED 상태 → False (failure path)
  BG-3: filter_state_events — governance 이벤트 필터링 (정상 path)
  BG-4: minify_canonical_rules — 제거 대상 키 삭제 확인 (정상 path)
  BG-5: generate — FULL 파일 미존재 → FileNotFoundError (failure path)
  BG-6: generate — 필수 키 누락 → KeyError (failure path)
  BG-7: generate — 유효한 FULL → boot 파일 생성 성공 (정상 path)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.boot_generator import (
    is_active_task,
    filter_state_events,
    minify_canonical_rules,
    minify_decisions,
    generate,
    CANONICAL_RULES_REMOVE_KEYS,
    REQUIRED_FULL_KEYS,
)


# ── Fixture 헬퍼 ────────────────────────────────────────────────────────────

def _make_minimal_full_context() -> dict:
    """최소 유효 full_context fixture (SESSION_BOOT 파일 비의존)."""
    return {
        "chain": {"tip": "abc1234", "session": 174},
        "pending_tasks": [],
        "state_events": [],
        "lessons": [],
        "canonical_rules": {},
        "decisions": [],
    }


# ── BG-1: is_active_task — ACTIVE → True ─────────────────────────────────

class TestBG1_IsActiveTask(unittest.TestCase):
    def test_BG1_active_status_returns_true(self):
        """ACTIVE 상태 태스크 → True (정상 path)"""
        for status in ["PLANNED", "IN_PROGRESS", "PENDING", "DEFERRED"]:
            self.assertTrue(is_active_task({"status": status}), f"status={status}")

    def test_BG1_eag_prefix_returns_true(self):
        """EAG- prefix 태스크 → True (정상 path)"""
        self.assertTrue(is_active_task({"status": "EAG-1_COMPLETE"}))


# ── BG-2: is_active_task — COMPLETED → False ─────────────────────────────

class TestBG2_IsInactiveTask(unittest.TestCase):
    def test_BG2_completed_returns_false(self):
        """COMPLETED 태스크 → False (RULE-8 failure path)"""
        for status in ["COMPLETED", "CANCELED_BY_POLICY", "CLOSED"]:
            self.assertFalse(is_active_task({"status": status}), f"status={status}")

    def test_BG2_empty_status_returns_false(self):
        """status 없음 → False (RULE-8 failure path)"""
        self.assertFalse(is_active_task({}))


# ── BG-3: filter_state_events — governance 이벤트 필터링 ──────────────────

class TestBG3_FilterStateEvents(unittest.TestCase):
    def test_BG3_governance_event_included(self):
        """governance whitelist 이벤트 → 포함 (정상 path)"""
        events = [
            {"event_type": "EAG_APPROVED", "session": 174},
            {"event_type": "UNKNOWN_TYPE", "session": 174},
        ]
        result = filter_state_events(events)
        types = [e["event_type"] for e in result]
        self.assertIn("EAG_APPROVED", types)

    def test_BG3_unresolved_always_included(self):
        """status=unresolved 이벤트 → 세션 무관 포함 (정상 path)"""
        events = [
            {"event_type": "EAG_APPROVED", "session": 1, "status": "unresolved"},
        ]
        result = filter_state_events(events)
        self.assertEqual(len(result), 1)


# ── BG-4: minify_canonical_rules — 제거 키 확인 ───────────────────────────

class TestBG4_MinifyCanonicalRules(unittest.TestCase):
    def test_BG4_remove_keys_absent_from_result(self):
        """CANONICAL_RULES_REMOVE_KEYS → 결과에서 제거 (정상 path)"""
        rules = {k: {"value": "x"} for k in CANONICAL_RULES_REMOVE_KEYS}
        rules["keep_this"] = {"value": "y"}
        result = minify_canonical_rules(rules)
        for k in CANONICAL_RULES_REMOVE_KEYS:
            self.assertNotIn(k, result)
        self.assertIn("keep_this", result)

    def test_BG4_note_field_removed_from_items(self):
        """항목 내 'note' 필드 제거 (정상 path)"""
        rules = {"my_rule": {"id": "R1", "note": "should be removed", "value": "x"}}
        result = minify_canonical_rules(rules)
        self.assertNotIn("note", result["my_rule"])
        self.assertIn("value", result["my_rule"])


# ── BG-5: generate — FULL 파일 미존재 → FileNotFoundError ─────────────────

class TestBG5_GenerateFullMissing(unittest.TestCase):
    def test_BG5_full_not_found_raises(self):
        """FULL 파일 미존재 → FileNotFoundError (RULE-8 failure path)"""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as boot_f:
            boot_path = boot_f.name
        with self.assertRaises(FileNotFoundError):
            generate("/nonexistent/full.json", boot_path)


# ── BG-6: generate — 필수 키 누락 → KeyError ─────────────────────────────

class TestBG6_GenerateMissingKeys(unittest.TestCase):
    def test_BG6_missing_required_keys_raises(self):
        """FULL 필수 키 누락 → KeyError (RULE-8 failure path)"""
        incomplete = {"chain": {"tip": "abc"}}  # 나머지 필수 키 없음
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as full_f:
            json.dump(incomplete, full_f, ensure_ascii=False)
            full_path = full_f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as boot_f:
            boot_path = boot_f.name
        with self.assertRaises(KeyError):
            generate(full_path, boot_path)


# ── BG-7: generate — 유효한 FULL → boot 생성 성공 ─────────────────────────

class TestBG7_GenerateValid(unittest.TestCase):
    def test_BG7_valid_full_creates_boot(self):
        """유효한 FULL → boot 파일 생성 + boot_meta.boot_is_ssot=False (정상 path)"""
        full_data = _make_minimal_full_context()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as full_f:
            json.dump(full_data, full_f, ensure_ascii=False)
            full_path = full_f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as boot_f:
            boot_path = boot_f.name

        boot = generate(full_path, boot_path)
        self.assertIsInstance(boot, dict)
        self.assertFalse(boot["boot_meta"]["boot_is_ssot"])
        self.assertIn("chain", boot)
        self.assertTrue(Path(boot_path).exists())


if __name__ == "__main__":
    unittest.main()

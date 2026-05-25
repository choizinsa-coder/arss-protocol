"""
test_write_tier_policy.py
AIBA Context Gateway — Write Tier Policy 전용 테스트
SSOT: RULE-8 매핑 (tools/context_gateway/write_tier_policy.py)
S153 Code Health Remediation Phase 1
"""

import sys
import unittest
from pathlib import Path

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


class TestWriteTierPolicy(unittest.TestCase):

    def test_T1_all_write_actions_are_tier1(self):
        for action in WriteAction:
            tier = classify_write_action(action)
            self.assertEqual(tier, WriteTier.TIER_1, f"{action.value} should be TIER_1")

    def test_T2_all_tier2_actions_are_tier2(self):
        for action in Tier2Action:
            tier = classify_tier2_action(action)
            self.assertEqual(tier, WriteTier.TIER_2, f"{action.value} should be TIER_2")

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

    def test_T4_assert_functions(self):
        assert_tier1_required(WriteAction.CLOSE_BUNDLE_COMMIT)

        safe_path = Path("/opt/arss/sandbox/test_draft.json")
        assert_tier2_safe(safe_path)

        tier1_path = Path("/opt/arss/SESSION_CONTEXT_S153_FINAL.json")
        with self.assertRaises(RuntimeError):
            assert_tier2_safe(tier1_path)

        unknown_path = Path("/opt/arss/unknown_file.json")
        with self.assertRaises(RuntimeError):
            assert_tier2_safe(unknown_path)

    def test_policy_summary_structure(self):
        summary = get_policy_summary()
        self.assertIn("tier_1", summary)
        self.assertIn("tier_2", summary)
        self.assertIn("principle", summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)

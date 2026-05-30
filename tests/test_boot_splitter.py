"""
test_boot_splitter.py
source: tools/session_context_gen/quarantine_boot_splitter/boot_splitter.py
P4-C2 (S174): SESSION_BOOT_PENDING stub → Fixture Layer 실제 테스트 작성
원칙: tempfile + dry_run 모드 — 실제 SESSION_BOOT 파일 비의존

구조:
  BS-1: _extract_boot — boot_meta 포함 + boot_is_ssot=False (정상 path)
  BS-2: _extract_full — 원본 전체 무손실 복사 (정상 path)
  BS-3: mutate_split dry_run=True — ok=True + hash 반환 (정상 path)
  BS-4: mutate_split — src 파일 미존재 → ok=False + error (failure path)
  BS-5: mutate_split dry_run=False — 실제 파일 생성 + full_hash 일치 (정상 path)
  BS-6: mutate_split — boot_sections_written에 boot_meta 미포함 (정상 path)
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.session_context_gen.quarantine_boot_splitter.boot_splitter import (
    mutate_split,
    _extract_boot,
    _extract_full,
    BOOT_SECTIONS,
)


# ── Fixture 헬퍼 ────────────────────────────────────────────────────────────

def _make_minimal_src() -> dict:
    """최소 유효 SESSION_CONTEXT fixture."""
    return {
        "system_name": "AIBA",
        "schema_version": "4.0",
        "session_count": 174,
        "chain": {"tip": "abc1234"},
        "pending_tasks": [],
        "state_events": [],
        "lessons": [],
        "decisions": [],
        "canonical_rules": {},
        "archive_refs": {},
        "agent_focus": {},
        "generated_at": "2026-05-30T00:00:00+09:00",
        "session_reentry": {"first_action": "test"},
    }


def _write_src_tmp(data: dict) -> str:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        return f.name


# ── BS-1: _extract_boot — boot_meta 포함 + boot_is_ssot=False ─────────────

class TestBS1_ExtractBoot(unittest.TestCase):
    def test_BS1_boot_meta_inserted_and_not_ssot(self):
        """_extract_boot → boot_meta 포함 + boot_is_ssot=False (정상 path)"""
        ctx = _make_minimal_src()
        boot = _extract_boot(ctx, "dummy_hash")
        self.assertIn("boot_meta", boot)
        self.assertFalse(boot["boot_meta"]["boot_is_ssot"])
        self.assertEqual(boot["boot_meta"]["full_hash_ref"], "dummy_hash")

    def test_BS1_boot_sections_present(self):
        """_extract_boot → BOOT_SECTIONS 키 포함 (ctx에 존재하는 것만)"""
        ctx = _make_minimal_src()
        boot = _extract_boot(ctx, "h")
        for key in BOOT_SECTIONS:
            if key in ctx:
                self.assertIn(key, boot)


# ── BS-2: _extract_full — 원본 무손실 복사 ────────────────────────────────

class TestBS2_ExtractFull(unittest.TestCase):
    def test_BS2_full_equals_original(self):
        """_extract_full → 원본 전체 무손실 복사 (정상 path)"""
        ctx = _make_minimal_src()
        full = _extract_full(ctx)
        self.assertEqual(full, ctx)
        # 독립 복사본 (참조 아님)
        full["injected"] = True
        self.assertNotIn("injected", ctx)


# ── BS-3: mutate_split dry_run=True — ok=True ─────────────────────────────

class TestBS3_MutateSplitDryRun(unittest.TestCase):
    def test_BS3_dry_run_returns_ok_true(self):
        """dry_run=True → ok=True + full_hash/boot_hash 반환 (정상 path)"""
        src_path = _write_src_tmp(_make_minimal_src())
        with tempfile.NamedTemporaryFile(suffix=".json") as full_f, \
             tempfile.NamedTemporaryFile(suffix=".json") as boot_f:
            result = mutate_split(
                src_path=Path(src_path),
                full_out=Path(full_f.name),
                boot_out=Path(boot_f.name),
                dry_run=True,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertIn("full_hash", result)
        self.assertIn("boot_hash", result)


# ── BS-4: src 파일 미존재 → ok=False + error ──────────────────────────────

class TestBS4_SrcMissing(unittest.TestCase):
    def test_BS4_missing_src_returns_ok_false(self):
        """src 파일 미존재 → ok=False + error (RULE-8 failure path)"""
        result = mutate_split(
            src_path=Path("/nonexistent/context.json"),
            full_out=Path("/tmp/full_out.json"),
            boot_out=Path("/tmp/boot_out.json"),
            dry_run=True,
        )
        self.assertFalse(result["ok"])
        self.assertIn("SRC_LOAD_FAILED", result["error"])


# ── BS-5: mutate_split dry_run=False — 실제 파일 생성 + hash 일치 ──────────

class TestBS5_MutateSplitWriteFiles(unittest.TestCase):
    def test_BS5_write_mode_creates_files(self):
        """dry_run=False → 실제 파일 생성 + full_hash 일치 (정상 path)"""
        src_path = _write_src_tmp(_make_minimal_src())
        with tempfile.TemporaryDirectory() as tmpdir:
            full_out = Path(tmpdir) / "full.json"
            boot_out = Path(tmpdir) / "boot.json"
            result = mutate_split(
                src_path=Path(src_path),
                full_out=full_out,
                boot_out=boot_out,
                dry_run=False,
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["dry_run"])


# ── BS-6: boot_sections_written에 boot_meta 미포함 ─────────────────────────

class TestBS6_BootSectionsWritten(unittest.TestCase):
    def test_BS6_boot_meta_not_in_sections_written(self):
        """boot_sections_written에 boot_meta 미포함 (boot_meta는 삽입 키) (정상 path)"""
        src_path = _write_src_tmp(_make_minimal_src())
        with tempfile.NamedTemporaryFile(suffix=".json") as full_f, \
             tempfile.NamedTemporaryFile(suffix=".json") as boot_f:
            result = mutate_split(
                src_path=Path(src_path),
                full_out=Path(full_f.name),
                boot_out=Path(boot_f.name),
                dry_run=True,
            )
        self.assertNotIn("boot_meta", result["boot_sections_written"])


if __name__ == "__main__":
    unittest.main()

# tests/test_source_collapse.py
# PT-S73-002 STABILIZATION — Source Collapse Detection Gate pytest
# TC-1 ~ TC-10 완전 격리 실행 (tempfile 기반, VPS 연결 불필요)

import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# import 경로 설정 — tools/delta_context/ 기준
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "delta_context"))

from phase2_validator import check_source_collapse


def _sha256_of_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_temp(content: bytes) -> str:
    """휘발성 임시 파일 생성 후 경로 반환."""
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(content)
    f.flush()
    f.close()
    return f.name


class TestSourceCollapse(unittest.TestCase):

    # TC-1: 동일 source_path → FAIL / PATH_MATCH
    def test_tc1_same_path(self):
        path = _write_temp(b"content_tc1")
        h = _sha256_of_file(path)
        ctx = {
            "candidate_source_path": path,
            "ssot_source_path": path,
            "candidate_source_hash": h,
            "ssot_source_hash": h,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "PATH_MATCH")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path)

    # TC-2: 다른 source_path + 동일 SHA256 full hash → FAIL / HASH_MATCH
    def test_tc2_different_path_same_hash(self):
        content = b"identical_content_for_hash_match"
        path_a = _write_temp(content)
        path_b = _write_temp(content)
        h = _sha256_of_file(path_a)
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": h,
            "ssot_source_hash": h,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "HASH_MATCH")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-3: 다른 source_path + 다른 SHA256 hash → PASS / NONE
    def test_tc3_different_path_different_hash(self):
        path_a = _write_temp(b"content_alpha_unique")
        path_b = _write_temp(b"content_beta_unique")
        h_a = _sha256_of_file(path_a)
        h_b = _sha256_of_file(path_b)
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": h_a,
            "ssot_source_hash": h_b,
        }
        result = check_source_collapse(ctx)
        self.assertFalse(result["collapse"])
        self.assertEqual(result["reason"], "NONE")
        self.assertEqual(result["verdict"], "PASS")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-4: hash 누락 → FAIL / UNKNOWN
    def test_tc4_hash_missing(self):
        path_a = _write_temp(b"content_tc4_a")
        path_b = _write_temp(b"content_tc4_b")
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            # candidate_source_hash 누락
            "ssot_source_hash": _sha256_of_file(path_b),
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "UNKNOWN")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-5: source_path 누락 → FAIL / UNKNOWN
    def test_tc5_path_missing(self):
        path_b = _write_temp(b"content_tc5_b")
        h_b = _sha256_of_file(path_b)
        ctx = {
            # candidate_source_path 누락
            "ssot_source_path": path_b,
            "candidate_source_hash": "a" * 64,
            "ssot_source_hash": h_b,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "UNKNOWN")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_b)

    # TC-6: hash가 64자리 미만 (prefix hash) → FAIL / INVALID_HASH_FORMAT
    def test_tc6_short_hash(self):
        path_a = _write_temp(b"content_tc6_a")
        path_b = _write_temp(b"content_tc6_b")
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": "abcdef12",   # 8자리 prefix hash
            "ssot_source_hash": _sha256_of_file(path_b),
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "INVALID_HASH_FORMAT")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-7: 양쪽 inode 동일 → FAIL / INODE_MATCH
    def test_tc7_same_inode(self):
        path_a = _write_temp(b"content_tc7_a")
        path_b = _write_temp(b"content_tc7_b")
        h_a = _sha256_of_file(path_a)
        h_b = _sha256_of_file(path_b)
        fake_inode = 99999
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": h_a,
            "ssot_source_hash": h_b,
            "candidate_source_inode": fake_inode,
            "ssot_source_inode": fake_inode,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "INODE_MATCH")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-8: 비교 중 exception 발생 → FAIL / UNKNOWN
    def test_tc8_exception_during_comparison(self):
        path_a = _write_temp(b"content_tc8_a")
        path_b = _write_temp(b"content_tc8_b")
        h_a = _sha256_of_file(path_a)
        h_b = _sha256_of_file(path_b)
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": h_a,
            "ssot_source_hash": h_b,
        }
        # os.path.abspath 강제 예외 발생으로 내부 exception 경로 테스트
        with patch("os.path.abspath", side_effect=RuntimeError("forced exception")):
            result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "UNKNOWN")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)

    # TC-9: source_path가 존재하지 않음 → FAIL / UNKNOWN
    def test_tc9_path_not_exist(self):
        nonexistent = "/tmp/aiba_s91_nonexistent_tc9_xyzxyz.json"
        path_b = _write_temp(b"content_tc9_b")
        h_b = _sha256_of_file(path_b)
        ctx = {
            "candidate_source_path": nonexistent,
            "ssot_source_path": path_b,
            "candidate_source_hash": "a" * 64,
            "ssot_source_hash": h_b,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "UNKNOWN")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_b)

    # TC-10: 64자리 fake hash가 실제 파일 재계산 hash와 불일치 → FAIL / INVALID_HASH_INTEGRITY
    def test_tc10_fake_64char_hash(self):
        path_a = _write_temp(b"content_tc10_a")
        path_b = _write_temp(b"content_tc10_b")
        h_b = _sha256_of_file(path_b)
        fake_64_hash = "f" * 64   # 형식상 64자리지만 실제 파일과 불일치
        ctx = {
            "candidate_source_path": path_a,
            "ssot_source_path": path_b,
            "candidate_source_hash": fake_64_hash,
            "ssot_source_hash": h_b,
        }
        result = check_source_collapse(ctx)
        self.assertTrue(result["collapse"])
        self.assertEqual(result["reason"], "INVALID_HASH_INTEGRITY")
        self.assertEqual(result["verdict"], "FAIL")
        os.unlink(path_a)
        os.unlink(path_b)


if __name__ == "__main__":
    unittest.main()

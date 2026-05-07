# tests/test_collapse_integration.py
# PT-S73-002 STABILIZATION — Integration pytest TC-11~TC-14
# run_with_collapse_gate 통합 흐름 검증
# VPS 연결 불필요 — tempfile + unittest.mock 완전 격리

import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "delta_context"))

from phase2_validator import run_with_collapse_gate, validate_phase2, check_source_collapse


def _sha256_of_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _write_temp(content: bytes) -> str:
    f = tempfile.NamedTemporaryFile(delete=False)
    f.write(content)
    f.flush()
    f.close()
    return f.name


def _valid_phase2_ctx(candidate_path: str, ssot_path: str) -> dict:
    """collapse PASS 조건을 충족하는 최소 ctx 생성 (source 필드 포함)."""
    h_c = _sha256_of_file(candidate_path)
    h_s = _sha256_of_file(ssot_path)
    ts = "2026-05-07T12:00:00+09:00"
    payload = {
        "generated_at": ts,
        "chain": {"tip": "eeffbe71"},
        "schema_version": "4.0",
        "session_count": 91,
    }
    return {
        # source collapse 필드
        "candidate_source_path": candidate_path,
        "ssot_source_path": ssot_path,
        "candidate_source_hash": h_c,
        "ssot_source_hash": h_s,
        # validate_phase2 필드
        "shadow_mode": True,
        "index_loaded": True,
        "delta_count": 1,
        "session_number": 91,
        "candidate_payload": dict(payload),
        "ssot_payload": dict(payload),
        "phase1_complete": True,
    }


class TestCollapseIntegration(unittest.TestCase):

    # TC-11: source collapse FAIL → run_with_collapse_gate가 즉시 FAIL 반환
    def test_tc11_collapse_fail_returns_immediately(self):
        path = _write_temp(b"same_content_tc11")
        h = _sha256_of_file(path)
        ctx = {
            "candidate_source_path": path,
            "ssot_source_path": path,       # 동일 경로 → PATH_MATCH
            "candidate_source_hash": h,
            "ssot_source_hash": h,
        }
        result = run_with_collapse_gate(ctx)
        # collapse FAIL 구조 확인
        self.assertTrue(result["collapse"])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertEqual(result["reason"], "PATH_MATCH")
        # validate_phase2 반환 키("phase2_valid")가 없어야 함
        self.assertNotIn("phase2_valid", result)
        os.unlink(path)

    # TC-12: source collapse FAIL → validate_phase2()가 호출되지 않음
    def test_tc12_collapse_fail_validate_phase2_not_called(self):
        path = _write_temp(b"same_content_tc12")
        h = _sha256_of_file(path)
        ctx = {
            "candidate_source_path": path,
            "ssot_source_path": path,
            "candidate_source_hash": h,
            "ssot_source_hash": h,
        }
        with patch(
            "phase2_validator.validate_phase2", wraps=validate_phase2
        ) as mock_v:
            run_with_collapse_gate(ctx)
            mock_v.assert_not_called()
        os.unlink(path)

    # TC-13: source collapse PASS → validate_phase2(ctx)가 호출됨
    def test_tc13_collapse_pass_validate_phase2_called(self):
        path_c = _write_temp(b"candidate_content_tc13_unique")
        path_s = _write_temp(b"ssot_content_tc13_unique")
        ctx = _valid_phase2_ctx(path_c, path_s)

        with patch(
            "phase2_validator.validate_phase2", wraps=validate_phase2
        ) as mock_v:
            result = run_with_collapse_gate(ctx)
            mock_v.assert_called_once_with(ctx)

        # validate_phase2 반환 구조 확인
        self.assertIn("phase2_valid", result)
        self.assertIn("preconditions", result)
        self.assertIn("contract", result)
        os.unlink(path_c)
        os.unlink(path_s)

    # TC-14: shadow_pipeline.py 호출부가 validate_phase2가 아닌
    #         run_with_collapse_gate를 사용하는지 소스 코드 검사
    def test_tc14_shadow_pipeline_uses_run_with_collapse_gate(self):
        pipeline_path = os.path.join(
            os.path.dirname(__file__),
            "..", "tools", "delta_context", "shadow_pipeline.py"
        )
        pipeline_path = os.path.abspath(pipeline_path)
        self.assertTrue(
            os.path.exists(pipeline_path),
            f"shadow_pipeline.py not found at {pipeline_path}"
        )
        with open(pipeline_path, "r", encoding="utf-8") as f:
            source = f.read()

        # run_with_collapse_gate import 및 호출 확인
        self.assertIn(
            "run_with_collapse_gate",
            source,
            "shadow_pipeline.py must import or call run_with_collapse_gate"
        )
        # 직접 validate_phase2 호출이 제거되었는지 확인
        # (import 라인은 허용, 실제 호출 패턴 "= validate_phase2(" 금지)
        self.assertNotIn(
            "= validate_phase2(",
            source,
            "shadow_pipeline.py must not directly call validate_phase2() — use run_with_collapse_gate()"
        )


if __name__ == "__main__":
    unittest.main()

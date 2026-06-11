import sys
import json
import pytest
sys.path.insert(0, '/opt/arss/engine/arss-protocol')
from tools.flat_verifier import validate, compute_hash

GENESIS = "0" * 64

def _make_rpu(rpu_id, prev_hash, content="test-content"):
    rpu = {
        "rpu_id": rpu_id,
        "timestamp": "2026-01-01T00:00:00.000000Z",
        "actor_id": "test",
        "event_type": "TEST_EVENT",
        "content": content,
        "prev_hash": prev_hash,
    }
    rpu["hash"] = compute_hash(rpu)
    return rpu

class TestFlatVerifierV11:
    """flat_verifier.py v1.1.0 hash_match 3-state TC"""

    def test_tc1_pass_hash_match_true(self, tmp_path):
        """TC-1: 정상 RPU 검증 -> hash_match=True, chain_integrity=True"""
        rpu = _make_rpu("rpu-0001", GENESIS)
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is True, f"expected True, got {result['hash_match']}"
        assert result["chain_integrity"] is True
        assert result["validated_count"] == 1
        # A안 sys.exit 조건: is not True 불충족 -> exit(0)
        assert result["hash_match"] is True  # exit 조건 불충족 확인

    def test_tc2_fail_hash_match_false(self, tmp_path):
        """TC-2: hash 불일치 RPU -> hash_match=False"""
        rpu = _make_rpu("rpu-0001", GENESIS)
        rpu["hash"] = "a" * 64  # hash 조작
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is False, f"expected False, got {result['hash_match']}"
        # A안: is not True 충족 -> exit(1) 조건 성립
        assert result["hash_match"] is not True

    def test_tc3_skipped_hash_match_none(self, tmp_path):
        """TC-3: 필드 누락 RPU -> hash_match=None (미검증)"""
        rpu = {"rpu_id": "rpu-0001", "timestamp": "2026-01-01T00:00:00.000000Z"}
        # 필수 필드 누락: actor_id, event_type, content, prev_hash, hash 없음
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is None, f"expected None, got {result['hash_match']}"
        assert result["validated_count"] == 1
        # A안: is not True 충족 -> exit(1) 조건 성립 (Fail-Closed)
        assert result["hash_match"] is not True

    def test_tc4_empty_no_files(self, tmp_path):
        """TC-4: 파일 없음 -> hash_match=False, validated_count=0"""
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is False, f"expected False, got {result['hash_match']}"
        assert result["validated_count"] == 0

    def test_tc5_skipped_flag_true(self, tmp_path):
        """TC-5: 필드 누락 skip → hash_match=None, hash_match_skipped=True"""
        rpu = {"rpu_id": "rpu-0001", "timestamp": "2026-01-01T00:00:00.000000Z"}
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is None
        assert result["hash_match_skipped"] is True

    def test_tc6_pass_skipped_false(self, tmp_path):
        """TC-6: 정상 PASS → hash_match=True, hash_match_skipped=False"""
        rpu = _make_rpu("rpu-0001", GENESIS)
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is True
        assert result["hash_match_skipped"] is False

    def test_tc7_fail_skipped_false(self, tmp_path):
        """TC-7: hash 불일치 FAIL → hash_match=False, hash_match_skipped=False"""
        rpu = _make_rpu("rpu-0001", GENESIS)
        rpu["hash"] = "a" * 64
        (tmp_path / "rpu-0001.json").write_text(json.dumps(rpu), encoding="utf-8")
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is False
        assert result["hash_match_skipped"] is False

    def test_tc8_no_files_skipped_false(self, tmp_path):
        """TC-8: 파일 없음 → hash_match=False, hash_match_skipped=False"""
        result = validate(str(tmp_path), "rpu-0001:rpu-0001")
        assert result["hash_match"] is False
        assert result["hash_match_skipped"] is False

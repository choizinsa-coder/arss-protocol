import json
import sys
import pytest
from pathlib import Path

# tools/governance 를 경로에 추가
ROOT = Path("/opt/arss/engine/arss-protocol")
sys.path.insert(0, str(ROOT / "tools/governance"))

import sovereign_authority as sa


class TestSovereignAuthorityModule:
    """AIF Area 5: Beo Sovereign Authority (Constitutional Override)"""

    def test_module_version(self):
        """VERSION + EAG_ID 필드 확인"""
        assert sa.VERSION == "1.0.0"
        assert sa.EAG_ID == "EAG-S320-AIF-AREA5-001"

    def test_validate_allowed_scope(self):
        """dep_procedure 스코프 허용"""
        result = sa.validate_override_scope("dep_procedure")
        assert result is True

    def test_validate_allowed_agent_role(self):
        """agent_role 스코프 허용"""
        result = sa.validate_override_scope("agent_role")
        assert result is True

    def test_validate_immutable_chain(self):
        """chain_integrity 스코프 거부 확인"""
        with pytest.raises(sa.OverrideDeniedError):
            sa.validate_override_scope("chain_integrity")

    def test_validate_immutable_context_hash(self):
        """context_hash 스코프 거부 확인"""
        with pytest.raises(sa.OverrideDeniedError):
            sa.validate_override_scope("context_hash")

    def test_validate_immutable_govdoc(self):
        """govdoc_freeze_gate 스코프 거부 확인"""
        with pytest.raises(sa.OverrideDeniedError):
            sa.validate_override_scope("govdoc_freeze_gate")

    def test_validate_immutable_ssot(self):
        """ssot_direct_write 스코프 거부 확인"""
        with pytest.raises(sa.OverrideDeniedError):
            sa.validate_override_scope("ssot_direct_write")

    def test_validate_empty_scope_raises(self):
        """빈 scope ValueError 확인"""
        with pytest.raises(ValueError):
            sa.validate_override_scope("")

    def test_record_override_success(self, tmp_path):
        """record_override 정상 동작 + 로그 파일 확인"""
        original_log = sa.LOG_PATH
        test_log = tmp_path / "sovereign_override_log.jsonl"
        sa.LOG_PATH = test_log
        try:
            entry = sa.record_override(
                eag="EAG-TEST-001",
                scope="dep_procedure",
                target="DEP v1.2 override target",
                rationale="test rationale",
            )
            assert entry["eag"] == "EAG-TEST-001"
            assert entry["scope"] == "dep_procedure"
            assert entry["actor"] == "beo"
            assert entry["schema"] == "sovereign_override_v1"
            assert test_log.exists()
            line_text = test_log.read_text(encoding="utf-8").strip()
            parsed = json.loads(line_text)
            assert parsed["eag"] == "EAG-TEST-001"
        finally:
            sa.LOG_PATH = original_log

    def test_record_override_denied_immutable(self, tmp_path):
        """IMMUTABLE scope record_override 거부 확인"""
        original_log = sa.LOG_PATH
        sa.LOG_PATH = tmp_path / "sovereign_override_log.jsonl"
        try:
            with pytest.raises(sa.OverrideDeniedError):
                sa.record_override(
                    eag="EAG-TEST-002",
                    scope="chain_integrity",
                    target="chain.tip",
                    rationale="test",
                )
        finally:
            sa.LOG_PATH = original_log

    def test_record_override_missing_eag(self, tmp_path):
        """eag 누락 시 ValueError 확인"""
        original_log = sa.LOG_PATH
        sa.LOG_PATH = tmp_path / "sovereign_override_log.jsonl"
        try:
            with pytest.raises(ValueError):
                sa.record_override(
                    eag="",
                    scope="dep_procedure",
                    target="test",
                    rationale="test",
                )
        finally:
            sa.LOG_PATH = original_log

    def test_get_active_overrides_empty(self, tmp_path):
        """override 없을 때 빈 리스트 반환 확인"""
        original_log = sa.LOG_PATH
        sa.LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            result = sa.get_active_overrides()
            assert result == []
        finally:
            sa.LOG_PATH = original_log

    def test_get_active_overrides_append_two(self, tmp_path):
        """override 2건 append 후 순서 확인"""
        original_log = sa.LOG_PATH
        test_log = tmp_path / "log.jsonl"
        sa.LOG_PATH = test_log
        try:
            sa.record_override("EAG-A", "dep_procedure", "A", "r1")
            sa.record_override("EAG-B", "agent_role", "B", "r2")
            results = sa.get_active_overrides()
            assert len(results) == 2
            assert results[0]["eag"] == "EAG-A"
            assert results[1]["eag"] == "EAG-B"
        finally:
            sa.LOG_PATH = original_log

    def test_get_override_summary_empty(self, tmp_path):
        """summary 구조 확인 (빈 로그)"""
        original_log = sa.LOG_PATH
        sa.LOG_PATH = tmp_path / "nonexistent.jsonl"
        try:
            summary = sa.get_override_summary()
            assert "schema" in summary
            assert summary["total_count"] == 0
            assert summary["latest"] is None
            assert summary["version"] == "1.0.0"
        finally:
            sa.LOG_PATH = original_log

    def test_get_override_summary_with_entry(self, tmp_path):
        """summary 최신건 확인"""
        original_log = sa.LOG_PATH
        sa.LOG_PATH = tmp_path / "log.jsonl"
        try:
            sa.record_override("EAG-Z", "oi_hold", "OI-001", "reason")
            summary = sa.get_override_summary()
            assert summary["total_count"] == 1
            assert summary["latest"]["eag"] == "EAG-Z"
        finally:
            sa.LOG_PATH = original_log

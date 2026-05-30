import sys
import pytest
from unittest.mock import patch
from tools.auto_loader.auto_loader import AutoLoader
from tools.auto_loader.field_contract import LoadTarget, SourceType, LoadScope
from tools.auto_loader.source_adapter import AdapterRead


def _vps_target(source_ref: str, required: bool = False) -> LoadTarget:
    return LoadTarget(
        id="TEST-001",
        source_type=SourceType.VPS_FILE,
        source_ref=source_ref,
        load_scope=LoadScope.FULL,
        required=required,
        fail_closed=False,
    )


# AL-1 ─────────────────────────────────────────────────────────
def test_al1_none_target():
    """load_target=None → failure_reason에 LOAD_TARGET 포함"""
    loader = AutoLoader()
    result = loader.run(None)
    assert result.loaded is False
    assert result.failure_reason is not None
    assert "LOAD_TARGET" in result.failure_reason


# AL-2 ─────────────────────────────────────────────────────────
def test_al2_invalid_source_ref():
    """VPS_FILE에 상대경로 입력 → source_ref invalid format"""
    target = LoadTarget(
        id="TEST-002",
        source_type=SourceType.VPS_FILE,
        source_ref="relative/path/file.json",   # is_absolute() = False → invalid
        load_scope=LoadScope.FULL,
        required=False,
        fail_closed=False,
    )
    loader = AutoLoader()
    result = loader.run(target)
    assert result.loaded is False
    assert "source_ref" in result.failure_reason


# AL-3 ─────────────────────────────────────────────────────────
def test_al3_missing_adapter():
    """adapters={} 빈 딕셔너리 → adapter missing or mismatched"""
    target = _vps_target("/tmp/test.json")
    loader = AutoLoader(adapters={})
    result = loader.run(target)
    assert result.loaded is False
    assert "adapter" in result.failure_reason


# AL-4 ─────────────────────────────────────────────────────────
def test_al4_adapter_read_fails():
    """존재하지 않는 절대경로 → VpsFileAdapter.read loaded=False"""
    target = _vps_target("/nonexistent/path/no_such_file_arss.json")
    loader = AutoLoader()
    result = loader.run(target)
    assert result.loaded is False
    assert result.failure_reason is not None


# AL-5 ─────────────────────────────────────────────────────────
def test_al5_shadow_mode_no_index_path():
    """shadow_mode=True + index_path/delta_root 미설정 → INDEX_INTEGRITY_SHADOW_CHECK FAIL"""
    loader = AutoLoader(shadow_mode=True)   # index_path=None, delta_root=None
    target = _vps_target("/tmp/test.json")
    result = loader.run(target)
    assert result.loaded is False
    assert "INDEX_INTEGRITY_SHADOW_CHECK" in result.failure_reason


# AL-6 ─────────────────────────────────────────────────────────
def test_al6_shadow_mode_validate_index_fail(tmp_path):
    """shadow_mode=True + validate_index FAIL → INDEX_INTEGRITY_SHADOW_CHECK FAIL"""
    index_path = str(tmp_path / "index.json")
    delta_root = str(tmp_path)
    loader = AutoLoader(
        shadow_mode=True,
        index_path=index_path,
        delta_root=delta_root,
    )
    with patch(
        "tools.auto_loader.auto_loader.validate_index",
        return_value={"result": "FAIL", "reason": "hash mismatch"},
    ):
        result = loader.run(_vps_target("/tmp/test.json"))
    assert result.loaded is False
    assert "INDEX_INTEGRITY_SHADOW_CHECK" in result.failure_reason


# AL-7 ─────────────────────────────────────────────────────────
def test_al7_success(tmp_path):
    """정상 VPS 파일 로드 → loaded=True, hash 존재, failure_reason=None"""
    f = tmp_path / "session_context.json"
    f.write_bytes(b'{"status": "ok"}')
    target = _vps_target(str(f))
    loader = AutoLoader()
    result = loader.run(target)
    assert result.loaded is True
    assert result.hash is not None
    assert result.failure_reason is None

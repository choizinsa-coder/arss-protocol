"""
test_eag2_shadow_mode.py
========================
PT-S63-001 EAG-2 — Shadow Mode TC
대상: AutoLoader shadow_mode / ActivationRuntimeConfig 확장 필드
EAG-2 APPROVED by 비오(Joshua) — S65
"""

import json
import os
import shutil
import tempfile

import pytest

from tools.auto_loader.auto_loader import AutoLoader
from tools.auto_loader.activation_runner import ActivationRunner, ActivationRuntimeConfig
from tools.auto_loader.field_contract import LoadTarget, SourceType, LoadScope


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_delta(delta_id: str, seq: int, content_hash: str) -> dict:
    return {"delta_id": delta_id, "sequence_number": seq, "content_hash": content_hash}


def _setup_valid_index(n: int = 1):
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "INDEX.json")
    delta_root = os.path.join(tmpdir, "DELTA_LOG")
    domain_dir = os.path.join(delta_root, "config")
    os.makedirs(domain_dir, exist_ok=True)

    deltas = [_make_delta(f"d-{i:03d}", i, f"hash-{i:03d}") for i in range(1, n + 1)]
    for i, d in enumerate(deltas):
        with open(os.path.join(domain_dir, f"{i:04d}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f)

    index = {"domains": {"config": {
        "latest_delta_id": f"d-{n:03d}",
        "latest_content_hash": f"hash-{n:03d}",
        "delta_count": n,
    }}}
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    return tmpdir, index_path, delta_root


# ── SM-001: AutoLoader 기본값 — shadow_mode=False, 경로=None ──────────────────

def test_sm_001_auto_loader_defaults():
    loader = AutoLoader()
    assert loader._shadow_mode is False
    assert loader._index_path is None
    assert loader._delta_root is None


# ── SM-002: AutoLoader shadow_mode=True 명시 주입 ─────────────────────────────

def test_sm_002_auto_loader_shadow_mode_injection():
    loader = AutoLoader(
        shadow_mode=True,
        index_path="/opt/index.json",
        delta_root="/opt/delta/",
    )
    assert loader._shadow_mode is True
    assert loader._index_path == "/opt/index.json"
    assert loader._delta_root == "/opt/delta/"


# ── SM-003: ActivationRuntimeConfig 기본값 확인 ───────────────────────────────

def test_sm_003_activation_runtime_config_defaults():
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
    )
    assert config.shadow_mode is False
    assert config.index_path is None
    assert config.delta_root is None


# ── SM-004: ActivationRuntimeConfig shadow_mode 필드 확장 확인 ────────────────

def test_sm_004_activation_runtime_config_shadow_fields():
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
        shadow_mode=True,
        index_path="/opt/index.json",
        delta_root="/opt/delta/",
    )
    assert config.shadow_mode is True
    assert config.index_path == "/opt/index.json"
    assert config.delta_root == "/opt/delta/"


# ── SM-005: shadow_mode=True + 경로 없음 → _validate_config FAIL ─────────────

def test_sm_005_validate_config_shadow_mode_no_path_fail():
    from tools.auto_loader.activation_runner import ActivationRunner
    runner = ActivationRunner()
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
        shadow_mode=True,
        index_path=None,
        delta_root=None,
    )
    result = runner._validate_config(config)
    assert result is not None
    assert result.loaded is False
    assert "index_path" in result.failure_reason


# ── SM-006: shadow_mode=True + index_path만 없음 → _validate_config FAIL ──────

def test_sm_006_validate_config_shadow_mode_no_index_path_fail():
    runner = ActivationRunner()
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
        shadow_mode=True,
        index_path=None,
        delta_root="/opt/delta/",
    )
    result = runner._validate_config(config)
    assert result is not None
    assert "index_path" in result.failure_reason


# ── SM-007: shadow_mode=True + delta_root만 없음 → _validate_config FAIL ──────

def test_sm_007_validate_config_shadow_mode_no_delta_root_fail():
    runner = ActivationRunner()
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
        shadow_mode=True,
        index_path="/opt/index.json",
        delta_root=None,
    )
    result = runner._validate_config(config)
    assert result is not None
    assert "delta_root" in result.failure_reason


# ── SM-008: shadow_mode=False + 경로 없음 → _validate_config PASS (SKIP 허용) ─

def test_sm_008_validate_config_shadow_mode_false_no_path_pass():
    runner = ActivationRunner()
    config = ActivationRuntimeConfig(
        task_id="PT-S61-001",
        output_mode="load_result_only",
        apply_to_session_context=False,
        shadow_mode=False,
        index_path=None,
        delta_root=None,
    )
    result = runner._validate_config(config)
    assert result is None  # PASS


# ── SM-009: AutoLoader 기존 무인자 호출 하위 호환성 ───────────────────────────

def test_sm_009_auto_loader_backward_compatible_no_args():
    """AutoLoader() 무인자 호출 — 기존 TC 30개 영향 없음 확인."""
    loader = AutoLoader()
    # shadow_mode=False → run(None) 시 SKIP → LOAD_TARGET missing
    result = loader.run(None)
    assert result.failure_reason == "LOAD_TARGET missing"


# ── SM-010: shadow_mode=True + 정상 INDEX → CHECK PASS 후 정상 진행 ───────────

def test_sm_010_shadow_mode_true_valid_index_check_pass():
    tmpdir, ip, dr = _setup_valid_index(n=3)
    try:
        loader = AutoLoader(shadow_mode=True, index_path=ip, delta_root=dr)
        result = loader.run(None)
        # INDEX_INTEGRITY_SHADOW_CHECK PASS → _resolve 단계로 진입
        assert "INDEX_INTEGRITY_SHADOW_CHECK" not in (result.failure_reason or "")
        assert result.failure_reason == "LOAD_TARGET missing"
    finally:
        shutil.rmtree(tmpdir)

"""
test_eag2_fail_closed.py
========================
PT-S63-001 EAG-2 — FAIL-CLOSED 원칙 TC-FC-001~006
대상: AutoLoader (shadow_mode FAIL-CLOSED) + index_validator
EAG-2 APPROVED by 비오(Joshua) — S65
"""

import json
import os
import shutil
import tempfile

import pytest

from tools.auto_loader.auto_loader import AutoLoader
from tools.delta_context.index_validator import validate_index


def _make_delta(delta_id: str, seq: int, content_hash: str) -> dict:
    return {"delta_id": delta_id, "sequence_number": seq, "content_hash": content_hash}


def _setup_valid(n: int = 1):
    """정상 INDEX + DELTA_LOG 환경 구성."""
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


# ── TC-FC-001: shadow_mode=True + 경로 없음 → AutoLoader run() FAIL ──────────

def test_tc_fc_001_shadow_mode_true_no_path_fail():
    loader = AutoLoader(shadow_mode=True, index_path=None, delta_root=None)
    result = loader.run(None)
    assert result.loaded is False
    assert result.failure_reason is not None
    assert "INDEX_INTEGRITY_SHADOW_CHECK FAIL" in result.failure_reason


# ── TC-FC-002: shadow_mode=True + index_path만 없음 → FAIL ───────────────────

def test_tc_fc_002_shadow_mode_true_missing_index_path_fail():
    loader = AutoLoader(shadow_mode=True, index_path=None, delta_root="/some/delta")
    result = loader.run(None)
    assert result.loaded is False
    assert "INDEX_INTEGRITY_SHADOW_CHECK FAIL" in result.failure_reason


# ── TC-FC-003: shadow_mode=True + delta_root만 없음 → FAIL ───────────────────

def test_tc_fc_003_shadow_mode_true_missing_delta_root_fail():
    loader = AutoLoader(shadow_mode=True, index_path="/some/index.json", delta_root=None)
    result = loader.run(None)
    assert result.loaded is False
    assert "INDEX_INTEGRITY_SHADOW_CHECK FAIL" in result.failure_reason


# ── TC-FC-004: shadow_mode=True + 정상 경로 + INDEX 정상 → CHECK PASS 후 진행 ─

def test_tc_fc_004_shadow_mode_true_valid_index_proceeds():
    tmpdir, ip, dr = _setup_valid(n=2)
    try:
        loader = AutoLoader(shadow_mode=True, index_path=ip, delta_root=dr)
        # load_target=None → _resolve에서 LOAD_TARGET missing 반환
        # 단, INDEX_INTEGRITY_SHADOW_CHECK는 PASS 통과
        result = loader.run(None)
        # CHECK PASS 후 _resolve 단계 진입 → failure_reason은 LOAD_TARGET missing
        assert "INDEX_INTEGRITY_SHADOW_CHECK" not in (result.failure_reason or "")
        assert result.failure_reason == "LOAD_TARGET missing"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-FC-005: shadow_mode=True + INDEX FAIL → run() 즉시 FAIL (자동 복구 없음) ─

def test_tc_fc_005_shadow_mode_true_index_fail_hard_stop():
    tmpdir = tempfile.mkdtemp()
    ip = os.path.join(tmpdir, "INDEX.json")
    dr = os.path.join(tmpdir, "DELTA_LOG")
    domain_dir = os.path.join(dr, "config")
    os.makedirs(domain_dir, exist_ok=True)

    # delta_count 불일치로 INDEX FAIL 유발
    with open(os.path.join(domain_dir, "0000.json"), "w", encoding="utf-8") as f:
        json.dump(_make_delta("d-001", 1, "hash-aaa"), f)

    with open(ip, "w", encoding="utf-8") as f:
        json.dump({"domains": {"config": {
            "latest_delta_id": "d-001",
            "latest_content_hash": "hash-aaa",
            "delta_count": 99,  # 실제 1 → FAIL
        }}}, f)

    try:
        loader = AutoLoader(shadow_mode=True, index_path=ip, delta_root=dr)
        result = loader.run(None)
        assert result.loaded is False
        assert "INDEX_INTEGRITY_SHADOW_CHECK FAIL" in result.failure_reason
    finally:
        shutil.rmtree(tmpdir)


# ── TC-FC-006: shadow_mode=False → CHECK SKIP, 기존 동작 유지 ─────────────────

def test_tc_fc_006_shadow_mode_false_skip(capsys):
    loader = AutoLoader(shadow_mode=False)
    result = loader.run(None)
    captured = capsys.readouterr()
    assert "SKIP" in captured.out
    assert "shadow_mode=False" in captured.out
    # 기존 동작: LOAD_TARGET missing
    assert result.failure_reason == "LOAD_TARGET missing"

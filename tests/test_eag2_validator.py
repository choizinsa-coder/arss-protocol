"""
test_eag2_validator.py
======================
PT-S63-001 EAG-2 — index_validator.py TC-V-001~010
대상: tools/delta_context/index_validator.py
EAG-2 APPROVED by 비오(Joshua) — S65
"""

import json
import os
import shutil
import tempfile

import pytest

from tools.delta_context.index_validator import validate_index


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _make_delta(delta_id: str, seq: int, content_hash: str) -> dict:
    return {"delta_id": delta_id, "sequence_number": seq, "content_hash": content_hash}


def _setup(index_data: dict, domain_deltas: dict):
    """tmpdir에 INDEX.json + DELTA_LOG/<domain>/<n>.json 배치."""
    tmpdir = tempfile.mkdtemp()
    index_path = os.path.join(tmpdir, "INDEX.json")
    delta_root = os.path.join(tmpdir, "DELTA_LOG")
    os.makedirs(delta_root, exist_ok=True)

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f)

    for domain, deltas in domain_deltas.items():
        domain_dir = os.path.join(delta_root, domain)
        os.makedirs(domain_dir, exist_ok=True)
        for i, d in enumerate(deltas):
            with open(os.path.join(domain_dir, f"{i:04d}.json"), "w", encoding="utf-8") as f:
                json.dump(d, f)

    return tmpdir, index_path, delta_root


# ── TC-V-001: 정상 chain → PASS ───────────────────────────────────────────────

def test_tc_v_001_normal_chain_pass():
    deltas = [
        _make_delta("d-001", 1, "hash-aaa"),
        _make_delta("d-002", 2, "hash-bbb"),
    ]
    index = {"domains": {"config": {
        "latest_delta_id": "d-002",
        "latest_content_hash": "hash-bbb",
        "delta_count": 2,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-002: sequence gap → FAIL ─────────────────────────────────────────────

def test_tc_v_002_sequence_gap_fail():
    deltas = [
        _make_delta("d-001", 1, "hash-aaa"),
        _make_delta("d-003", 3, "hash-ccc"),  # seq 2 누락
    ]
    index = {"domains": {"config": {
        "latest_delta_id": "d-003",
        "latest_content_hash": "hash-ccc",
        "delta_count": 2,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
        assert "G1" in result["reason"]
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-003: duplicate sequence → FAIL ───────────────────────────────────────

def test_tc_v_003_duplicate_sequence_fail():
    deltas = [
        _make_delta("d-001", 1, "hash-aaa"),
        _make_delta("d-002", 1, "hash-bbb"),  # seq 1 중복
    ]
    index = {"domains": {"config": {
        "latest_delta_id": "d-002",
        "latest_content_hash": "hash-bbb",
        "delta_count": 2,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
        assert "G1" in result["reason"]
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-004: latest_delta_id mismatch → FAIL ─────────────────────────────────

def test_tc_v_004_latest_delta_id_mismatch_fail():
    deltas = [_make_delta("d-001", 1, "hash-aaa")]
    index = {"domains": {"config": {
        "latest_delta_id": "d-WRONG",
        "latest_content_hash": "hash-aaa",
        "delta_count": 1,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
        assert "G2" in result["reason"]
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-005: latest_content_hash mismatch → FAIL ─────────────────────────────

def test_tc_v_005_latest_content_hash_mismatch_fail():
    deltas = [_make_delta("d-001", 1, "hash-aaa")]
    index = {"domains": {"config": {
        "latest_delta_id": "d-001",
        "latest_content_hash": "hash-WRONG",
        "delta_count": 1,
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
        assert "G3" in result["reason"]
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-006: delta_count mismatch → FAIL ─────────────────────────────────────

def test_tc_v_006_delta_count_mismatch_fail():
    deltas = [_make_delta("d-001", 1, "hash-aaa")]
    index = {"domains": {"config": {
        "latest_delta_id": "d-001",
        "latest_content_hash": "hash-aaa",
        "delta_count": 99,  # 실제는 1
    }}}
    tmpdir, ip, dr = _setup(index, {"config": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
        assert "G4" in result["reason"]
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-007: INDEX missing field → FAIL ──────────────────────────────────────

def test_tc_v_007_index_missing_field_fail():
    index = {"domains": {"config": {
        "latest_delta_id": "d-001",
        # latest_content_hash, delta_count 누락
    }}}
    tmpdir, ip, dr = _setup(index, {"config": [_make_delta("d-001", 1, "hash-aaa")]})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-008: DELTA_LOG missing → FAIL ────────────────────────────────────────

def test_tc_v_008_delta_log_missing_fail():
    tmpdir = tempfile.mkdtemp()
    ip = os.path.join(tmpdir, "INDEX.json")
    dr = os.path.join(tmpdir, "DELTA_LOG")
    os.makedirs(dr, exist_ok=True)
    # domain 디렉터리 미생성 + delta_count != 0
    with open(ip, "w", encoding="utf-8") as f:
        json.dump({"domains": {"config": {
            "latest_delta_id": "d-001",
            "latest_content_hash": "hash-aaa",
            "delta_count": 1,
        }}}, f)
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-009: empty domain → PASS ─────────────────────────────────────────────

def test_tc_v_009_empty_domain_pass():
    index = {"domains": {"config": {
        "latest_delta_id": None,
        "latest_content_hash": None,
        "delta_count": 0,
    }}}
    tmpdir, ip, dr = _setup(index, {})  # delta 파일 없음
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-V-010: corrupted JSON → FAIL ───────────────────────────────────────────

def test_tc_v_010_corrupted_json_fail():
    tmpdir = tempfile.mkdtemp()
    ip = os.path.join(tmpdir, "INDEX.json")
    dr = os.path.join(tmpdir, "DELTA_LOG")
    os.makedirs(dr, exist_ok=True)
    with open(ip, "w", encoding="utf-8") as f:
        f.write("{invalid json !!!")
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)

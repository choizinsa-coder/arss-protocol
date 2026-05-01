"""
test_eag2_chain_integrity.py
============================
PT-S63-001 EAG-2 — chain 무결성 TC-CH-001~007
대상: tools/delta_context/index_validator.py (multi-domain / cross-domain)
EAG-2 APPROVED by 비오(Joshua) — S65
"""

import json
import os
import shutil
import tempfile

import pytest

from tools.delta_context.index_validator import validate_index


def _make_delta(delta_id: str, seq: int, content_hash: str) -> dict:
    return {"delta_id": delta_id, "sequence_number": seq, "content_hash": content_hash}


def _setup(index_data: dict, domain_deltas: dict):
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


# ── TC-CH-001: 다중 domain 정상 → PASS ───────────────────────────────────────

def test_tc_ch_001_multi_domain_pass():
    index = {"domains": {
        "config": {
            "latest_delta_id": "c-002",
            "latest_content_hash": "hash-c2",
            "delta_count": 2,
        },
        "state": {
            "latest_delta_id": "s-003",
            "latest_content_hash": "hash-s3",
            "delta_count": 3,
        },
    }}
    domain_deltas = {
        "config": [
            _make_delta("c-001", 1, "hash-c1"),
            _make_delta("c-002", 2, "hash-c2"),
        ],
        "state": [
            _make_delta("s-001", 1, "hash-s1"),
            _make_delta("s-002", 2, "hash-s2"),
            _make_delta("s-003", 3, "hash-s3"),
        ],
    }
    tmpdir, ip, dr = _setup(index, domain_deltas)
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-002: 한 domain FAIL → 전체 FAIL ────────────────────────────────────

def test_tc_ch_002_one_domain_fail_propagates():
    index = {"domains": {
        "config": {
            "latest_delta_id": "c-001",
            "latest_content_hash": "hash-c1",
            "delta_count": 1,
        },
        "state": {
            "latest_delta_id": "s-002",
            "latest_content_hash": "hash-s2",
            "delta_count": 2,
        },
    }}
    domain_deltas = {
        "config": [_make_delta("c-001", 1, "hash-c1")],
        "state": [
            _make_delta("s-001", 1, "hash-s1"),
            _make_delta("s-WRONG", 2, "hash-s2"),  # delta_id 불일치
        ],
    }
    # state domain: latest_delta_id = "s-002" vs 실제 "s-WRONG"
    index["domains"]["state"]["latest_delta_id"] = "s-002"
    tmpdir, ip, dr = _setup(index, domain_deltas)
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-003: domain 있으나 INDEX에 없음 → PASS (INDEX 기준 검증) ─────────────

def test_tc_ch_003_extra_domain_dir_not_in_index_pass():
    """DELTA_LOG에 domain 디렉터리가 있어도 INDEX에 없으면 검증 대상 아님."""
    index = {"domains": {"config": {
        "latest_delta_id": "c-001",
        "latest_content_hash": "hash-c1",
        "delta_count": 1,
    }}}
    domain_deltas = {
        "config": [_make_delta("c-001", 1, "hash-c1")],
        "orphan": [_make_delta("o-001", 1, "hash-o1")],  # INDEX에 없는 domain
    }
    tmpdir, ip, dr = _setup(index, domain_deltas)
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-004: INDEX domains가 빈 dict → PASS ─────────────────────────────────

def test_tc_ch_004_empty_domains_dict_pass():
    index = {"domains": {}}
    tmpdir, ip, dr = _setup(index, {})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-005: INDEX 최상위 domains 키 누락 → FAIL ────────────────────────────

def test_tc_ch_005_missing_domains_key_fail():
    index = {"meta": "no domains key"}
    tmpdir, ip, dr = _setup(index, {})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-006: domain 항목이 dict가 아님 → FAIL ──────────────────────────────

def test_tc_ch_006_domain_entry_not_dict_fail():
    index = {"domains": {"config": "invalid_not_dict"}}
    tmpdir, ip, dr = _setup(index, {})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "FAIL"
        assert result["hard_stop"] is True
    finally:
        shutil.rmtree(tmpdir)


# ── TC-CH-007: 대량 delta 정상 chain → PASS ──────────────────────────────────

def test_tc_ch_007_large_chain_pass():
    n = 50
    deltas = [_make_delta(f"d-{i:03d}", i, f"hash-{i:03d}") for i in range(1, n + 1)]
    index = {"domains": {"bulk": {
        "latest_delta_id": f"d-{n:03d}",
        "latest_content_hash": f"hash-{n:03d}",
        "delta_count": n,
    }}}
    tmpdir, ip, dr = _setup(index, {"bulk": deltas})
    try:
        result = validate_index(ip, dr)
        assert result["result"] == "PASS"
    finally:
        shutil.rmtree(tmpdir)

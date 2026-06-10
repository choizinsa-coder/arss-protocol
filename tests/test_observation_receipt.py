"""
test_observation_receipt.py
OI-P1-001 검증 구조 개선 — pytest TC
EAG: EAG-S219-OI-001
"""

import hashlib
import json
import pytest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

# 경로 설정
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "observation"))

from observation_receipt import (
    _sha256,
    build_receipt,
    save_receipt,
    verify_receipt,
    apply_verification,
    build_journal_entry,
    evaluate_oi_p1_001,
    VerificationResult,
)


# ── 픽스처 ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_observations():
    return [
        {
            "tool":    "read_file",
            "path":    "/opt/arss/engine/arss-protocol/tools/mcp/mcp_read_server.py",
            "purpose": "OBSERVATION",
            "content": "# mcp_read_server content sample",
        },
        {
            "tool":    "read_file",
            "path":    "/opt/arss/engine/arss-protocol/session_journal/session_journal.jsonl",
            "purpose": "OBSERVATION",
            "content": '{"event_type": "GENESIS"}',
        },
    ]


@pytest.fixture
def sample_snapshot():
    return {
        "snapshot_type": "READ_ONLY_PROJECTION",
        "generated_at":  1234567890.0,
        "services": {
            "aiba-mcp-bridge":    "active",
            "aiba-domi-runtime":  "active",
            "aiba-jeni-runtime":  "active",
            "nginx":              "active",
        },
        "metadata_files": ["SESSION_CONTEXT.json"],
    }


@pytest.fixture
def sample_receipt(sample_observations, sample_snapshot):
    return build_receipt(
        session_id="S219",
        agent="domi",
        prompt="3개 파일을 read_file로 직접 조회 후 평가해 주십시오.",
        context={"aiba_identity": "AI 협업 운영체제", "agent_role": "CSO"},
        observations=sample_observations,
        response="[DESIGN] session_journal chain 무결성 PASS...",
        runtime_snapshot=sample_snapshot,
    )


# ── TC-1: Receipt 기본 필드 ────────────────────────────────────────

def test_receipt_required_fields(sample_receipt):
    required = {
        "receipt_id", "schema_version", "session_id", "agent",
        "generated_at", "prompt_hash", "context_hash",
        "observations", "runtime_snapshot_hash", "response_hash",
        "verification_state", "eag_ref",
    }
    assert required.issubset(set(sample_receipt.keys()))


# ── TC-2: receipt_id 형식 ─────────────────────────────────────────

def test_receipt_id_format(sample_receipt):
    rid = sample_receipt["receipt_id"]
    assert rid.startswith("OR-S219-")
    assert len(rid) > len("OR-S219-")


# ── TC-3: UNVERIFIED 초기 상태 ────────────────────────────────────

def test_initial_verification_state(sample_receipt):
    assert sample_receipt["verification_state"] == "UNVERIFIED"


# ── TC-4: evidence_hash 계산 정확성 ──────────────────────────────

def test_evidence_hash_computation(sample_observations):
    receipt = build_receipt(
        session_id="S219",
        agent="domi",
        prompt="test",
        context={},
        observations=sample_observations,
        response="test response",
    )
    for i, obs in enumerate(receipt["observations"]):
        expected = _sha256(
            sample_observations[i]["path"] +
            sample_observations[i]["content"]
        )
        assert obs["evidence_hash"] == expected


# ── TC-5: 4-Step 검증 PASS ────────────────────────────────────────

def test_verify_receipt_pass(sample_receipt, sample_observations, sample_snapshot):
    vr = verify_receipt(
        receipt=sample_receipt,
        fresh_observations=sample_observations,
        fresh_snapshot=sample_snapshot,
    )
    assert vr.passed is True
    assert all(s["result"] == "PASS" for s in vr.steps)


# ── TC-6: evidence_hash 불일치 시 FAIL ───────────────────────────

def test_verify_receipt_fail_hash_mismatch(sample_receipt, sample_observations):
    tampered = [
        {**obs, "content": obs["content"] + "_TAMPERED"}
        for obs in sample_observations
    ]
    vr = verify_receipt(
        receipt=sample_receipt,
        fresh_observations=tampered,
    )
    assert vr.passed is False
    step3 = next(s for s in vr.steps if s["step"] == 3)
    assert step3["result"] == "FAIL"


# ── TC-7: observation 수 불일치 시 FAIL ──────────────────────────

def test_verify_receipt_fail_observation_count(sample_receipt, sample_observations):
    vr = verify_receipt(
        receipt=sample_receipt,
        fresh_observations=sample_observations[:1],  # 1개만 전달
    )
    assert vr.passed is False
    step2 = next(s for s in vr.steps if s["step"] == 2)
    assert step2["result"] == "FAIL"


# ── TC-8: runtime_snapshot 없을 때 Step4 SKIP ────────────────────

def test_verify_receipt_snapshot_skipped(sample_observations):
    receipt_no_snap = build_receipt(
        session_id="S219",
        agent="jeni",
        prompt="test",
        context={},
        observations=sample_observations,
        response="test",
        runtime_snapshot=None,
    )
    vr = verify_receipt(
        receipt=receipt_no_snap,
        fresh_observations=sample_observations,
        fresh_snapshot=None,
    )
    assert vr.passed is True
    step4 = next(s for s in vr.steps if s["step"] == 4)
    assert "SKIPPED" in step4["detail"]


# ── TC-9: apply_verification 상태 반영 ───────────────────────────

def test_apply_verification_verified(sample_receipt, sample_observations, sample_snapshot):
    vr = verify_receipt(sample_receipt, sample_observations, sample_snapshot)
    updated = apply_verification(sample_receipt, vr)
    assert updated["verification_state"] == "VERIFIED"
    assert "verification_detail" in updated


# ── TC-10: apply_verification FAIL 반영 ──────────────────────────

def test_apply_verification_fail(sample_receipt, sample_observations):
    tampered = [{**obs, "content": "TAMPERED"} for obs in sample_observations]
    vr = verify_receipt(sample_receipt, tampered)
    updated = apply_verification(sample_receipt, vr)
    assert updated["verification_state"] == "FAIL"


# ── TC-11: journal entry OI event_type ───────────────────────────

def test_build_journal_entry_oi_type():
    entry = build_journal_entry(
        session_id="S219",
        receipt_id="OR-S219-ABCD1234",
        agent="domi",
        verification_state="VERIFIED",
        prev_hash="abc123",
    )
    assert entry["event_type"] == "OI"
    assert entry["details"]["observation_receipt"] == "OR-S219-ABCD1234"
    assert entry["details"]["verification"] == "VERIFIED"
    assert "entry_hash" in entry
    assert entry["prev_hash"] == "abc123"


# ── TC-12: journal entry hash 무결성 ─────────────────────────────

def test_journal_entry_hash_integrity():
    entry = build_journal_entry(
        session_id="S219",
        receipt_id="OR-S219-TEST0001",
        agent="domi",
        verification_state="VERIFIED",
        prev_hash="0" * 64,
    )
    # entry_hash 재계산 검증
    entry_copy = {k: v for k, v in entry.items() if k != "entry_hash"}
    expected_hash = _sha256(json.dumps(entry_copy, sort_keys=True))
    assert entry["entry_hash"] == expected_hash


# ── TC-13: OI-P1-001 PASS 판정 ───────────────────────────────────

def test_evaluate_oi_p1_001_pass(sample_receipt, sample_observations, sample_snapshot):
    vr = verify_receipt(sample_receipt, sample_observations, sample_snapshot)
    assert evaluate_oi_p1_001(vr) == "PASS"


# ── TC-14: OI-P1-001 FAIL 판정 ───────────────────────────────────

def test_evaluate_oi_p1_001_fail(sample_receipt, sample_observations):
    tampered = [{**obs, "content": "TAMPERED"} for obs in sample_observations]
    vr = verify_receipt(sample_receipt, tampered)
    assert evaluate_oi_p1_001(vr) == "FAIL"


# ── TC-15: save_receipt 파일 생성 ────────────────────────────────

def test_save_receipt_creates_file(sample_receipt, tmp_path):
    import observation_receipt as _mod
    original_dir = _mod.RECEIPTS_DIR
    _mod.RECEIPTS_DIR = tmp_path / "receipts"
    try:
        saved_path = save_receipt(sample_receipt)
        assert saved_path.exists()
        loaded = json.loads(saved_path.read_text())
        assert loaded["receipt_id"] == sample_receipt["receipt_id"]
    finally:
        _mod.RECEIPTS_DIR = original_dir


# ── TC-16: _sha256 결정론적 계산 ─────────────────────────────────

def test_sha256_deterministic():
    assert _sha256("hello") == _sha256("hello")
    assert _sha256("hello") != _sha256("world")
    assert len(_sha256("test")) == 64

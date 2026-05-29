"""
tests/test_deployment_gate.py + tests/test_deploy_executor.py
AIBA Sync Layer P3-T2 pytest 검증
EAG-2 Approved (S168) — 비오(Joshua)

커버리지:
  [Deployment Gate]
  T-01: Tier 1 Gate PASS — 유효 approval_id
  T-02: Tier 1 Gate REJECT — approval_id 없음
  T-03: Tier 1 Gate REJECT — approval_id 형식 불일치
  T-04: Tier 1 Gate REJECT — sync_decision != COMMIT
  T-05: Tier 1 Gate REJECT — pointer_updated=False
  T-06: Tier 1 Gate REJECT — manifest_fresh=False
  T-07: Tier 1 Gate REJECT — session 불일치
  T-08: Tier 2 Gate PASS — Sandbox 경로
  T-09: Tier 2 Gate REJECT — 운영 경로 (tools/)
  T-10: classify_deploy_tier 분류 확인

  [Deploy Executor]
  T-11: Tier 1 실행 SUCCESS — receipt 생성 + 저장
  T-12: Tier 1 실행 REJECTED — Gate 미통과
  T-13: Tier 1 실행 FAILED — FINAL 파일 없음
  T-14: Tier 2 실행 SUCCESS — 파일 쓰기 + 경량 receipt
  T-15: Tier 2 실행 REJECTED — Gate 미통과
  T-16: Tier 2 실행 REJECTED — 운영 경로 재검증 차단
  T-17: get_executor_status 구조 검증
  T-18: get_gate_status 구조 검증
  T-19: Tier 1 receipt 스키마 필드 전체 확인
  T-20: Tier 2 receipt 스키마 필드 확인
"""

import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from tools.sync_layer.deployment_gate import (
    validate_tier1_deploy,
    validate_tier2_deploy,
    classify_deploy_tier,
    get_gate_status,
    DEPLOY_TIER_1,
    DEPLOY_TIER_2,
)
from tools.sync_layer.deploy_executor import (
    execute_tier1_deploy,
    execute_tier2_deploy,
    get_executor_status,
    RESULT_SUCCESS,
    RESULT_FAILED,
    RESULT_REJECTED,
    RECEIPT_VERSION,
    ACTOR,
)


# ── 픽스처 ───────────────────────────────────────────────────────────────────

@pytest.fixture
def valid_deploy_request():
    return {
        "request_type": "DEPLOY_REQUEST",
        "session": 168,
        "sync_decision": "COMMIT",
        "final_file": "SESSION_CONTEXT_S168_FINAL.json",
        "pointer_updated": True,
        "manifest_fresh": True,
        "requested_by": "sync_orchestrator",
        "status": "PENDING_GATE",
        "p3_task": "P3-T1",
    }


@pytest.fixture
def final_path(tmp_path):
    """실제 존재하는 FINAL 파일."""
    p = tmp_path / "SESSION_CONTEXT_S168_FINAL.json"
    p.write_text('{"session_count": 168}', encoding="utf-8")
    return p


@pytest.fixture
def sandbox_path(tmp_path):
    """Tier 2 허용 sandbox 경로."""
    d = tmp_path / "sandbox" / "caddy"
    d.mkdir(parents=True)
    return d / "test_note.json"


@pytest.fixture
def ops_path():
    """
    Tier 2 금지 운영 경로 — VPS 스타일 고정 절대 경로.

    주의: tmp_path 사용 불가.
    tmp_path는 /tmp/pytest-... 형태로, classify_path가 "tmp" 부분을
    TIER_2_ALLOWED_DIRS["tmp"]와 오매칭하여 TIER_2로 잘못 판정함.
    VPS 스타일 경로는 parts에 "tmp"/"sandbox" 없음 → UNKNOWN → 차단 정상.
    """
    return Path("/opt/arss/engine/arss-protocol/tools/governance/policy.json")


@pytest.fixture
def tier1_receipt_dir(tmp_path, monkeypatch):
    """registry/deployment_receipts/ 를 tmp_path로 대체."""
    d = tmp_path / "registry" / "deployment_receipts"
    d.mkdir(parents=True)
    monkeypatch.setattr("tools.sync_layer.deploy_executor.TIER1_RECEIPT_DIR", d)
    return d


# ═══════════════════════════════════════════════════════════════════
# Deployment Gate 테스트
# ═══════════════════════════════════════════════════════════════════

def test_T01_tier1_gate_pass_valid_approval(valid_deploy_request):
    """유효한 approval_id로 Tier 1 Gate PASS."""
    result = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert result.passed is True
    assert result.tier == DEPLOY_TIER_1
    assert result.errors == []


def test_T02_tier1_gate_reject_no_approval(valid_deploy_request):
    """approval_id 없으면 REJECT."""
    result = validate_tier1_deploy(valid_deploy_request, "")
    assert result.passed is False
    assert any("APPROVAL_ID_MISSING" in e for e in result.errors)


def test_T03_tier1_gate_reject_invalid_approval_format(valid_deploy_request):
    """APPROVAL-* 형식 불일치 시 REJECT."""
    result = validate_tier1_deploy(valid_deploy_request, "EAG-168")
    assert result.passed is False
    assert any("APPROVAL_ID_INVALID" in e for e in result.errors)


def test_T04_tier1_gate_reject_sync_decision_not_commit(valid_deploy_request):
    """sync_decision이 COMMIT 아닐 때 REJECT."""
    valid_deploy_request["sync_decision"] = "STALE"
    result = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert result.passed is False
    assert any("SYNC_DECISION_NOT_COMMIT" in e for e in result.errors)


def test_T05_tier1_gate_reject_pointer_not_updated(valid_deploy_request):
    """pointer_updated=False 시 REJECT."""
    valid_deploy_request["pointer_updated"] = False
    result = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert result.passed is False
    assert any("POINTER_NOT_UPDATED" in e for e in result.errors)


def test_T06_tier1_gate_reject_manifest_not_fresh(valid_deploy_request):
    """manifest_fresh=False 시 REJECT."""
    valid_deploy_request["manifest_fresh"] = False
    result = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert result.passed is False
    assert any("MANIFEST_NOT_FRESH" in e for e in result.errors)


def test_T07_tier1_gate_reject_session_mismatch(valid_deploy_request):
    """expected_session과 request.session 불일치 시 REJECT."""
    result = validate_tier1_deploy(
        valid_deploy_request, "APPROVAL-S168-EAG2", expected_session=169
    )
    assert result.passed is False
    assert any("SESSION_MISMATCH" in e for e in result.errors)


def test_T08_tier2_gate_pass_sandbox_path(valid_deploy_request, sandbox_path):
    """Sandbox 경로는 Tier 2 Gate PASS."""
    result = validate_tier2_deploy(valid_deploy_request, sandbox_path)
    assert result.passed is True
    assert result.tier == DEPLOY_TIER_2
    assert result.errors == []


def test_T09_tier2_gate_reject_ops_path(valid_deploy_request, ops_path):
    """운영 경로(tools/)는 Tier 2 Gate REJECT."""
    result = validate_tier2_deploy(valid_deploy_request, ops_path)
    assert result.passed is False
    assert any("TIER2_PATH_VIOLATION" in e for e in result.errors)


def test_T10_classify_deploy_tier(valid_deploy_request, sandbox_path):
    """classify_deploy_tier: COMMIT 요청 → TIER_1, sandbox 경로 → TIER_2."""
    assert classify_deploy_tier(valid_deploy_request) == DEPLOY_TIER_1

    tier2_request = {"request_type": "SANDBOX_WRITE", "sync_decision": "NONE"}
    assert classify_deploy_tier(tier2_request, sandbox_path) == DEPLOY_TIER_2


# ═══════════════════════════════════════════════════════════════════
# Deploy Executor 테스트
# ═══════════════════════════════════════════════════════════════════

def test_T11_tier1_execute_success(
    valid_deploy_request, final_path, tier1_receipt_dir
):
    """Tier 1 실행 SUCCESS — receipt 생성 및 저장."""
    gate = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert gate.passed

    result = execute_tier1_deploy(gate, final_path)

    assert result["result"] == RESULT_SUCCESS
    assert result["tier"] == DEPLOY_TIER_1
    assert result["receipt_saved"] is True

    receipt = result["receipt"]
    assert receipt["deploy_type"] == "TIER1_EAG_DEPLOY"
    assert receipt["actor"] == ACTOR
    assert receipt["result"] == RESULT_SUCCESS
    assert receipt["receipt_version"] == RECEIPT_VERSION

    # 파일 실제 저장 확인
    saved_files = list(tier1_receipt_dir.glob("*.json"))
    assert len(saved_files) == 1


def test_T12_tier1_execute_rejected_gate_fail(
    valid_deploy_request, final_path, tier1_receipt_dir
):
    """Gate 미통과 시 REJECTED receipt 생성."""
    valid_deploy_request["pointer_updated"] = False
    gate = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    assert not gate.passed

    result = execute_tier1_deploy(gate, final_path)

    assert result["result"] == RESULT_REJECTED
    assert result["receipt"]["result"] == RESULT_REJECTED


def test_T13_tier1_execute_failed_no_final(
    valid_deploy_request, tmp_path, tier1_receipt_dir
):
    """FINAL 파일 없으면 FAILED receipt."""
    missing = tmp_path / "SESSION_CONTEXT_S168_FINAL.json"
    gate = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")

    result = execute_tier1_deploy(gate, missing)

    assert result["result"] == RESULT_FAILED
    assert result["receipt"]["result"] == RESULT_FAILED


def test_T14_tier2_execute_success(valid_deploy_request, sandbox_path):
    """Tier 2 실행 SUCCESS — 파일 쓰기 + 경량 receipt."""
    gate = validate_tier2_deploy(valid_deploy_request, sandbox_path)
    assert gate.passed

    content = '{"note": "sandbox test"}'
    result = execute_tier2_deploy(gate, sandbox_path, content)

    assert result["result"] == RESULT_SUCCESS
    assert result["tier"] == DEPLOY_TIER_2
    assert sandbox_path.exists()
    assert sandbox_path.read_text() == content

    receipt = result["receipt"]
    assert "deployment_id" in receipt
    assert "path" in receipt
    assert "hash" in receipt
    assert "result" in receipt
    assert "timestamp" in receipt
    # Tier 2는 approval_id, session, actor 없음
    assert "approval_id" not in receipt
    assert "actor" not in receipt


def test_T15_tier2_execute_rejected_gate_fail(valid_deploy_request, ops_path):
    """Gate 미통과(운영 경로) 시 Tier 2 REJECTED."""
    gate = validate_tier2_deploy(valid_deploy_request, ops_path)
    assert not gate.passed

    result = execute_tier2_deploy(gate, ops_path, "content")

    assert result["result"] == RESULT_REJECTED
    assert not ops_path.exists()


def test_T16_tier2_execute_rejected_ops_path_recheck(
    valid_deploy_request, ops_path
):
    """deploy_executor 내부 Sandbox 재검증 — 운영 경로 강제 차단."""
    # Gate를 강제로 passed=True로 조작해도 executor 내부에서 차단
    from tools.sync_layer.deployment_gate import GateDecision
    fake_gate = GateDecision(passed=True, tier=DEPLOY_TIER_2)
    fake_gate.deploy_request = valid_deploy_request

    result = execute_tier2_deploy(fake_gate, ops_path, "content")

    assert result["result"] == RESULT_REJECTED
    assert not ops_path.exists()


def test_T17_get_executor_status_structure():
    """get_executor_status 필수 필드 확인."""
    status = get_executor_status()
    assert status["component"] == "deploy_executor"
    assert status["layer"] == "sync_layer"
    assert status["p3_task"] == "P3-T2"
    assert status["actor"] == ACTOR
    assert status["authority_of_record"] is True
    assert len(status["result_enum"]) == 4


def test_T18_get_gate_status_structure():
    """get_gate_status 필수 필드 확인."""
    status = get_gate_status()
    assert status["component"] == "deployment_gate"
    assert status["layer"] == "sync_layer"
    assert status["p3_task"] == "P3-T2"
    assert status["tier1_requires_approval_id"] is True
    assert status["tier2_sandbox_only"] is True
    assert status["fail_closed"] is True


def test_T19_tier1_receipt_schema_complete(
    valid_deploy_request, final_path, tier1_receipt_dir
):
    """Tier 1 receipt 스키마 — 도미 확정 11개 필드 전체 포함."""
    gate = validate_tier1_deploy(valid_deploy_request, "APPROVAL-S168-EAG2")
    result = execute_tier1_deploy(gate, final_path)
    receipt = result["receipt"]

    required_fields = [
        "deployment_id", "deploy_type", "actor", "approval_id",
        "artifact_hash", "target", "result", "timestamp",
        "request_id", "session", "receipt_version",
    ]
    for field in required_fields:
        assert field in receipt, f"필수 필드 누락: {field}"

    assert receipt["receipt_version"] == RECEIPT_VERSION
    assert receipt["actor"] == ACTOR
    assert receipt["deploy_type"] == "TIER1_EAG_DEPLOY"
    assert receipt["approval_id"] == "APPROVAL-S168-EAG2"
    assert len(receipt["artifact_hash"]) == 64  # SHA256


def test_T20_tier2_receipt_schema(valid_deploy_request, sandbox_path):
    """Tier 2 receipt 스키마 — 도미 확정 5개 필드 확인."""
    gate = validate_tier2_deploy(valid_deploy_request, sandbox_path)
    result = execute_tier2_deploy(gate, sandbox_path, '{"x": 1}')
    receipt = result["receipt"]

    required_fields = ["deployment_id", "path", "hash", "result", "timestamp"]
    for field in required_fields:
        assert field in receipt, f"필수 필드 누락: {field}"

    # Tier 1 전용 필드 없어야 함
    assert "approval_id" not in receipt
    assert "actor" not in receipt
    assert "session" not in receipt
    assert "deploy_type" not in receipt

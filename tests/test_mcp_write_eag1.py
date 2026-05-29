"""
test_mcp_write_eag1.py — MCP Write Plane EAG-1 pytest
CONTRACT-01~10 검증

CONTRACT-01: Tier2 approval 없이 통과
CONTRACT-02: Tier2 sandbox 외부 접근 거부
CONTRACT-03: Tier2 .py write 거부
CONTRACT-04: Tier1 approval 없으면 FAIL
CONTRACT-05: TTL 만료 approval FAIL
CONTRACT-06: content_hash 불일치 FAIL
CONTRACT-07: single-use 재사용 FAIL
CONTRACT-08: receipt 생성 실패 → write 실패 (Fail-Closed)
CONTRACT-09: audit 기록 실패 → write 실패 (Fail-Closed)
CONTRACT-10: LOCKED_TIER1 → Tier1 FAIL, Tier2 PASS
"""

import json
import os
import sys
import pytest
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.mcp_write.issuer import issue_approval, load_approval, APPROVALS_DIR
from tools.mcp_write.lifecycle_manager import mark_used, LifecycleError
from tools.mcp_write.tier_router import (
    classify_tier,
    route_request,
    get_write_plane_state,
    set_write_plane_state,
    WritePlaneState,
    WritePlaneLockedError,
    TierClassification,
)
from tools.mcp_write.tier1_handler import handle_tier1_write, Tier1DenyError
from tools.mcp_write.tier2_handler import handle_tier2_write, Tier2DenyError


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path):
    sb = tmp_path / "sandbox"
    sb.mkdir()
    return sb


@pytest.fixture
def registry(tmp_path):
    reg = tmp_path / "registry"
    for d in ["approvals", "receipts", "audit", "state"]:
        (reg / d).mkdir(parents=True)
    return reg


@pytest.fixture
def state_file(tmp_path, registry):
    return str(registry / "state" / "plane_state.json")


@pytest.fixture(autouse=True)
def reset_state(tmp_path, registry, state_file):
    """각 테스트 전 상태 파일 초기화 (NORMAL)."""
    import tools.mcp_write.tier_router as tr
    _orig_state_file = tr.STATE_FILE
    tr.STATE_FILE = state_file
    yield
    tr.STATE_FILE = _orig_state_file


@pytest.fixture
def approval_fixture(tmp_path, sandbox, registry):
    """Tier1용 ACTIVE approval artifact 생성."""
    target = str(sandbox / "test.md")
    content = "# EAG-1 테스트 콘텐츠"
    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content)
    iss.APPROVALS_DIR = _orig_dir
    return artifact, target, content, str(registry / "approvals")


# ── CONTRACT-01: Tier2 approval 없이 통과 ─────────────────────────────

def test_contract_01_tier2_no_approval_required(tmp_path, sandbox, registry):
    """CONTRACT-01: Tier2는 approval 없이 write 가능."""
    target = str(sandbox / "note.txt")
    result = handle_tier2_write(
        target_path=target,
        content="sandbox note",
        audit_file=str(registry / "audit" / "audit.jsonl"),
        sandbox_paths=[str(sandbox)],
    )
    assert result["ok"] is True
    assert result["tier"] == "TIER2"
    assert os.path.exists(target)
    assert open(target).read() == "sandbox note"


# ── CONTRACT-02: Tier2 sandbox 외부 접근 거부 ──────────────────────────

def test_contract_02_tier2_sandbox_escape_denied(tmp_path, sandbox, registry):
    """CONTRACT-02: sandbox 외부 경로 거부."""
    outside = str(tmp_path / "outside.txt")
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=outside,
            content="unauthorized",
            audit_file=str(registry / "audit" / "audit.jsonl"),
            sandbox_paths=[str(sandbox)],
        )
    assert "CONTRACT-02" in exc.value.contract


def test_contract_02_symlink_escape_denied(tmp_path, sandbox, registry):
    """CONTRACT-02: symlink를 통한 sandbox 탈출 차단 (realpath 검증)."""
    # sandbox 내부에 외부를 가리키는 symlink 생성
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    link = sandbox / "escape_link"
    try:
        os.symlink(str(outside_dir), str(link))
    except OSError:
        pytest.skip("symlink 생성 불가 환경")

    target = str(link / "evil.txt")
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=target,
            content="escape attempt",
            audit_file=str(registry / "audit" / "audit.jsonl"),
            sandbox_paths=[str(sandbox)],
        )
    assert "CONTRACT-02" in exc.value.contract


def test_contract_02_dotdot_escape_denied(tmp_path, sandbox, registry):
    """CONTRACT-02: ..를 이용한 sandbox 탈출 차단."""
    target = str(sandbox / ".." / "escape.txt")
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=target,
            content="escape",
            audit_file=str(registry / "audit" / "audit.jsonl"),
            sandbox_paths=[str(sandbox)],
        )
    assert "CONTRACT-02" in exc.value.contract


# ── CONTRACT-03: Tier2 .py write 거부 ─────────────────────────────────

def test_contract_03_tier2_py_extension_denied(tmp_path, sandbox, registry):
    """CONTRACT-03: Tier2에서 .py 확장자 거부."""
    target = str(sandbox / "malicious.py")
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=target,
            content="import os; os.system('rm -rf /')",
            audit_file=str(registry / "audit" / "audit.jsonl"),
            sandbox_paths=[str(sandbox)],
        )
    assert "CONTRACT-03" in exc.value.contract


@pytest.mark.parametrize("ext", [".sh", ".env", ".key", ".pem", ".service", ".conf"])
def test_contract_03_forbidden_extensions(tmp_path, sandbox, registry, ext):
    """CONTRACT-03: 모든 금지 확장자 거부."""
    target = str(sandbox / f"file{ext}")
    with pytest.raises(Tier2DenyError) as exc:
        handle_tier2_write(
            target_path=target,
            content="forbidden",
            audit_file=str(registry / "audit" / "audit.jsonl"),
            sandbox_paths=[str(sandbox)],
        )
    assert "CONTRACT-03" in exc.value.contract


# ── CONTRACT-04: Tier1 approval 없으면 FAIL ──────────────────────────

def test_contract_04_tier1_missing_approval_denied(tmp_path, sandbox, registry):
    """CONTRACT-04: approval artifact 없으면 Tier1 거부."""
    target = str(tmp_path / "important.json")
    with pytest.raises(FileNotFoundError):
        handle_tier1_write(
            approval_id="NONEXISTENT-APPROVAL",
            target_path=target,
            content="some content",
            approvals_dir=str(registry / "approvals"),
            receipts_dir=str(registry / "receipts"),
            audit_file=str(registry / "audit" / "audit.jsonl"),
        )


# ── CONTRACT-05: TTL 만료 approval FAIL ──────────────────────────────

def test_contract_05_expired_approval_denied(tmp_path, sandbox, registry):
    """CONTRACT-05: TTL 만료된 approval 거부."""
    target = str(sandbox / "expired.md")
    content = "# 만료 테스트"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content, ttl_seconds=600)
    iss.APPROVALS_DIR = _orig_dir

    # expires_at을 과거로 조작 + artifact_hash 재계산 (무결성 유지)
    from tools.mcp_write.issuer import compute_artifact_hash
    artifact["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=10)
    ).isoformat()
    artifact["artifact_hash"] = compute_artifact_hash(artifact)
    artifact_path = os.path.join(
        str(registry / "approvals"), f"{artifact['approval_id']}.json"
    )
    with open(artifact_path, "w") as f:
        json.dump(artifact, f)

    with pytest.raises(Tier1DenyError) as exc:
        handle_tier1_write(
            approval_id=artifact["approval_id"],
            target_path=target,
            content=content,
            approvals_dir=str(registry / "approvals"),
            receipts_dir=str(registry / "receipts"),
            audit_file=str(registry / "audit" / "audit.jsonl"),
        )
    assert "CONTRACT-05" in exc.value.contract


# ── CONTRACT-06: content_hash 불일치 FAIL ─────────────────────────────

def test_contract_06_content_hash_mismatch_denied(tmp_path, sandbox, registry):
    """CONTRACT-06: approval scope의 content_hash와 실제 content 불일치 거부."""
    target = str(sandbox / "hash_test.md")
    approved_content = "# 승인된 콘텐츠"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, approved_content)
    iss.APPROVALS_DIR = _orig_dir

    with pytest.raises(Tier1DenyError) as exc:
        handle_tier1_write(
            approval_id=artifact["approval_id"],
            target_path=target,
            content="# 승인되지 않은 다른 콘텐츠!!!",
            approvals_dir=str(registry / "approvals"),
            receipts_dir=str(registry / "receipts"),
            audit_file=str(registry / "audit" / "audit.jsonl"),
        )
    assert "CONTRACT-06" in exc.value.contract


# ── CONTRACT-07: single-use 재사용 FAIL ──────────────────────────────

def test_contract_07_single_use_reuse_denied(tmp_path, sandbox, registry):
    """CONTRACT-07: 이미 USED 상태인 approval 재사용 거부."""
    target = str(sandbox / "single_use.md")
    content = "# 단일 사용 테스트"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content)
    iss.APPROVALS_DIR = _orig_dir

    # 1차 write 성공
    handle_tier1_write(
        approval_id=artifact["approval_id"],
        target_path=target,
        content=content,
        approvals_dir=str(registry / "approvals"),
        receipts_dir=str(registry / "receipts"),
        audit_file=str(registry / "audit" / "audit.jsonl"),
    )

    # 2차 write 시도 — USED 상태이므로 거부
    with pytest.raises(Tier1DenyError) as exc:
        handle_tier1_write(
            approval_id=artifact["approval_id"],
            target_path=target,
            content=content,
            approvals_dir=str(registry / "approvals"),
            receipts_dir=str(registry / "receipts"),
            audit_file=str(registry / "audit" / "audit.jsonl"),
        )
    assert "CONTRACT-07" in exc.value.contract


# ── CONTRACT-08: receipt 생성 실패 → write 실패 (Fail-Closed) ─────────

def test_contract_08_receipt_failure_blocks_write(tmp_path, sandbox, registry):
    """CONTRACT-08: receipt 생성 실패 시 write FAIL (Fail-Closed)."""
    target = str(sandbox / "receipt_test.md")
    content = "# receipt 테스트"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content)
    iss.APPROVALS_DIR = _orig_dir

    # receipts_dir를 존재하지 않는 읽기전용 경로로 override
    with mock.patch("tools.mcp_write.tier1_handler._create_receipt") as mock_receipt:
        mock_receipt.side_effect = Tier1DenyError(
            "FAIL-CLOSED: receipt 생성 실패", contract="CONTRACT-08"
        )
        with pytest.raises(Tier1DenyError) as exc:
            handle_tier1_write(
                approval_id=artifact["approval_id"],
                target_path=target,
                content=content,
                approvals_dir=str(registry / "approvals"),
                receipts_dir=str(registry / "receipts"),
                audit_file=str(registry / "audit" / "audit.jsonl"),
            )
    assert "CONTRACT-08" in exc.value.contract


# ── CONTRACT-09: audit 기록 실패 → write 실패 (Fail-Closed) ──────────

def test_contract_09_audit_failure_blocks_write(tmp_path, sandbox, registry):
    """CONTRACT-09: audit 기록 실패 시 write FAIL (Fail-Closed)."""
    target = str(sandbox / "audit_test.md")
    content = "# audit 테스트"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content)
    iss.APPROVALS_DIR = _orig_dir

    # _append_audit를 실패로 패치
    with mock.patch("tools.mcp_write.tier1_handler._append_audit") as mock_audit:
        mock_audit.side_effect = Tier1DenyError(
            "FAIL-CLOSED: audit 기록 실패", contract="CONTRACT-09"
        )
        with pytest.raises(Tier1DenyError) as exc:
            handle_tier1_write(
                approval_id=artifact["approval_id"],
                target_path=target,
                content=content,
                approvals_dir=str(registry / "approvals"),
                receipts_dir=str(registry / "receipts"),
                audit_file=str(registry / "audit" / "audit.jsonl"),
            )
    assert "CONTRACT-09" in exc.value.contract


# ── CONTRACT-10: LOCKED_TIER1 → Tier1 FAIL, Tier2 PASS ──────────────

def test_contract_10_locked_tier1_blocks_tier1_allows_tier2(
    tmp_path, sandbox, registry, state_file
):
    """CONTRACT-10: LOCKED_TIER1 상태에서 Tier1 차단, Tier2 허용."""
    import tools.mcp_write.tier_router as tr
    tr.STATE_FILE = state_file

    # LOCKED_TIER1 상태 설정
    set_write_plane_state(WritePlaneState.LOCKED_TIER1, reason="test")

    # Tier1 경로 (sandbox 외부) → LOCKED_TIER1으로 차단
    tier1_target = str(tmp_path / "blocked.json")
    with pytest.raises(WritePlaneLockedError) as exc:
        route_request(tier1_target)
    assert "LOCKED_TIER1" in exc.value.state

    # Tier2 경로 (sandbox 내부) → LOCKED_TIER1에서도 허용
    tier2_target = str(sandbox / "allowed.txt")
    result = handle_tier2_write(
        target_path=tier2_target,
        content="sandbox write during LOCKED_TIER1",
        audit_file=str(registry / "audit" / "audit.jsonl"),
        sandbox_paths=[str(sandbox)],
    )
    assert result["ok"] is True
    assert result["tier"] == "TIER2"


# ── 정상 흐름 통합 테스트 ─────────────────────────────────────────────

def test_tier1_full_happy_path(tmp_path, sandbox, registry):
    """Tier1 정상 흐름: approval 발급 → write → receipt → mark_used → audit."""
    target = str(sandbox / "full_flow.md")
    content = "# Full Flow Test"

    import tools.mcp_write.issuer as iss
    _orig_dir = iss.APPROVALS_DIR
    iss.APPROVALS_DIR = str(registry / "approvals")
    artifact = issue_approval("Beo", target, content)
    iss.APPROVALS_DIR = _orig_dir

    result = handle_tier1_write(
        approval_id=artifact["approval_id"],
        target_path=target,
        content=content,
        approvals_dir=str(registry / "approvals"),
        receipts_dir=str(registry / "receipts"),
        audit_file=str(registry / "audit" / "audit.jsonl"),
    )

    assert result["ok"] is True
    assert result["tier"] == "TIER1"
    assert os.path.exists(target)
    assert open(target).read() == content

    # receipt 생성 확인
    receipts = os.listdir(str(registry / "receipts"))
    assert len(receipts) == 1
    receipt = json.load(open(str(registry / "receipts" / receipts[0])))
    assert receipt["result"] == "PASS"
    assert receipt["status"] == "PENDING_BEO_REVIEW"

    # approval status USED 확인
    updated_artifact = json.load(
        open(str(registry / "approvals" / f"{artifact['approval_id']}.json"))
    )
    assert updated_artifact["status"] == "USED"

    # audit 기록 확인
    audit_lines = open(str(registry / "audit" / "audit.jsonl")).readlines()
    assert len(audit_lines) >= 1
    event = json.loads(audit_lines[-1])
    assert event["result"] == "PASS"
    assert event["tier"] == "TIER1"

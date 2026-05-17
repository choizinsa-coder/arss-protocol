"""
test_mcp_write_gatekeeper.py — MCP Write Gatekeeper pytest 테스트
PT-S136-MCP-WRITE-GATEKEEPER v1.0.0

TC-01 ~ TC-20: 20개 테스트
"""

import hashlib
import json
import os
import sys
import time
import pytest

# Path injection
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "mcp"))

from mcp_write_gatekeeper import (
    MCP_WriteGatekeeper,
    WritePlaneState,
    FailClosedError,
    ALLOWED_EXTENSIONS,
)
from mcp_approval_authority import generate_approval, validate_path, validate_extension
from mcp_write_config import ALLOWED_SANDBOX_PATHS


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path):
    """테스트용 sandbox 디렉토리."""
    sb = tmp_path / "sandbox"
    sb.mkdir()
    return sb


@pytest.fixture
def registry(tmp_path):
    """테스트용 registry 디렉토리 (approvals/audit/snapshots)."""
    reg = tmp_path / "registry"
    (reg / "approvals").mkdir(parents=True)
    (reg / "audit").mkdir(parents=True)
    (reg / "snapshots").mkdir(parents=True)
    return reg


@pytest.fixture
def gk(tmp_path, sandbox, registry):
    """테스트용 Gatekeeper (tmp_path 기반 경로 주입)."""
    return MCP_WriteGatekeeper(
        allowed_paths=[str(sandbox) + "/"],
        forbidden_prefixes=[str(tmp_path / "registry") + "/"],
        approvals_dir=str(registry / "approvals"),
        audit_dir=str(registry / "audit"),
        snapshots_dir=str(registry / "snapshots"),
    )


@pytest.fixture
def approval(sandbox):
    """유효한 approval artifact (sandbox 경로 기반)."""
    target = str(sandbox / "test.md")
    return generate_approval(target, ".md", allowed_paths=[str(sandbox) + "/"])


@pytest.fixture
def stored_approval(gk, approval, registry):
    """Registry에 저장된 approval."""
    approval_file = os.path.join(
        str(registry / "approvals"), f"{approval['approval_id']}.json"
    )
    with open(approval_file, "w") as f:
        json.dump(approval, f)
    return approval


# ── TC-01: sandbox 경로 whitelist 통과 ───────────────────────────────

def test_tc01_sandbox_path_allowed(gk, sandbox):
    """TC-01: sandbox zone 경로는 _validate_path 통과."""
    path = str(sandbox / "test.md")
    assert gk._validate_path(path) is True


# ── TC-02: registry 경로 차단 ─────────────────────────────────────────

def test_tc02_registry_path_blocked(gk, registry):
    """TC-02: registry zone 경로는 _validate_path 차단."""
    path = str(registry / "audit" / "test.md")
    assert gk._validate_path(path) is False


# ── TC-03: sandbox 외부 경로 차단 ────────────────────────────────────

def test_tc03_outside_sandbox_blocked(gk, tmp_path):
    """TC-03: sandbox 외부 임의 경로 차단."""
    path = str(tmp_path / "outside.md")
    assert gk._validate_path(path) is False


# ── TC-04: 허용 확장자 통과 ──────────────────────────────────────────

def test_tc04_allowed_extensions_pass(gk):
    """TC-04: .md .json .txt 허용."""
    for ext in [".md", ".json", ".txt"]:
        assert gk._validate_extension(f"file{ext}") is True


# ── TC-05: 금지 확장자 차단 ──────────────────────────────────────────

def test_tc05_forbidden_extensions_blocked(gk):
    """TC-05: .py .sh .env .yaml .yml .service 차단."""
    for ext in [".py", ".sh", ".env", ".yaml", ".yml", ".service"]:
        assert gk._validate_extension(f"file{ext}") is False


# ── TC-06: approval_hash 무결성 검증 ─────────────────────────────────

def test_tc06_approval_hash_integrity(approval):
    """TC-06: approval_hash가 올바르게 계산됨."""
    stored_hash = approval["approval_hash"]
    body = {k: v for k, v in approval.items() if k != "approval_hash"}
    computed = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert computed == stored_hash


# ── TC-07: approval_hash 변조 시 FC-T4 ───────────────────────────────

def test_tc07_tampered_approval_hash_rejected(gk, approval, sandbox):
    """TC-07: approval_hash 변조 시 FC-T4."""
    approval["approval_hash"] = "deadbeef" * 8
    target = str(sandbox / "test.md")
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, target, ".md")
    assert exc.value.tier == "T4"


# ── TC-08: 만료된 approval FC-T4 ─────────────────────────────────────

def test_tc08_expired_approval_rejected(gk, sandbox):
    """TC-08: TTL 초과 approval은 FC-T4."""
    import datetime
    target = str(sandbox / "test.md")
    approval = generate_approval(target, ".md", allowed_paths=[str(sandbox) + "/"])
    old_time = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=700)
    ).isoformat()
    approval["approved_at"] = old_time
    body = {k: v for k, v in approval.items() if k != "approval_hash"}
    approval["approval_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True).encode()
    ).hexdigest()
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, target, ".md")
    assert exc.value.tier == "T4"


# ── TC-09: approval scope target_path 불일치 FC-T4 ───────────────────

def test_tc09_approval_path_mismatch_rejected(gk, approval, sandbox):
    """TC-09: approval scope의 target_path와 실제 경로 불일치 시 FC-T4."""
    wrong_path = str(sandbox / "other.md")
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, wrong_path, ".md")
    assert exc.value.tier == "T4"


# ── TC-10: approval 재사용 차단 FC-T4 ────────────────────────────────

def test_tc10_approval_reuse_blocked(gk, approval, sandbox):
    """TC-10: 동일 approval_id 재사용 시 FC-T4."""
    gk._used_approvals.add(approval["approval_id"])
    target = str(sandbox / "test.md")
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, target, ".md")
    assert exc.value.tier == "T4"


# ── TC-11: token single-use 보장 ─────────────────────────────────────

def test_tc11_token_single_use(gk, sandbox):
    """TC-11: token은 1회만 사용 가능."""
    target = str(sandbox / "test.md")
    token_id = gk._issue_token("appr-001", target, ".md")
    gk._consume_token(token_id, target)
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(token_id, target)
    assert exc.value.tier == "T4"


# ── TC-12: token TTL 만료 FC-T4 ──────────────────────────────────────

def test_tc12_token_ttl_expired(gk, sandbox):
    """TC-12: TTL 만료된 token은 FC-T4."""
    target = str(sandbox / "test.md")
    token_id = gk._issue_token("appr-002", target, ".md")
    with gk._token_lock:
        gk._token_store[token_id]["ttl"] = -1
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(token_id, target)
    assert exc.value.tier == "T4"


# ── TC-13: token 경로 불일치 FC-T4 ──────────────────────────────────

def test_tc13_token_path_mismatch(gk, sandbox):
    """TC-13: token 경로와 실제 경로 불일치 시 FC-T4."""
    target1 = str(sandbox / "a.md")
    target2 = str(sandbox / "b.md")
    token_id = gk._issue_token("appr-003", target1, ".md")
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(token_id, target2)
    assert exc.value.tier == "T4"


# ── TC-14: LOCKED 상태 쓰기 차단 ────────────────────────────────────

def test_tc14_write_blocked_when_locked(gk, sandbox):
    """TC-14: Write Plane LOCKED 상태에서 execute_write FC-T3."""
    gk._set_state(WritePlaneState.LOCKED)
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write("any", str(sandbox / "test.md"), "content")
    assert exc.value.tier == "T3"


# ── TC-15: HOLD 상태 쓰기 차단 ──────────────────────────────────────

def test_tc15_write_blocked_when_hold(gk, sandbox):
    """TC-15: Write Plane HOLD 상태에서 execute_write FC-T2."""
    gk._set_state(WritePlaneState.HOLD)
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write("any", str(sandbox / "test.md"), "content")
    assert exc.value.tier == "T2"


# ── TC-16: RECOVERY_MODE 1회 소진 후 차단 ────────────────────────────

def test_tc16_recovery_mode_single_write_exhausted(gk):
    """TC-16: RECOVERY_MODE에서 1회 write 소진 후 추가 write FC-T3."""
    gk._set_state(WritePlaneState.RECOVERY_MODE)
    gk._recovery_write_used = True
    with pytest.raises(FailClosedError) as exc:
        gk._assert_writable()
    assert exc.value.tier == "T3"


# ── TC-17: beo_recovery_close → NORMAL 전이 ─────────────────────────

def test_tc17_recovery_close_returns_normal(gk):
    """TC-17: beo_recovery_close() 후 Write Plane NORMAL 복귀."""
    gk._set_state(WritePlaneState.RECOVERY_MODE)
    gk.beo_recovery_close()
    assert gk.get_state() == WritePlaneState.NORMAL


# ── TC-18: SHA-256 hash 정확성 ──────────────────────────────────────

def test_tc18_sha256_hash_correctness(gk, tmp_path):
    """TC-18: _sha256_file()이 올바른 SHA-256 반환."""
    test_file = tmp_path / "check.txt"
    test_file.write_bytes(b"hello AIBA")
    expected = hashlib.sha256(b"hello AIBA").hexdigest()
    assert gk._sha256_file(str(test_file)) == expected


# ── TC-19: 존재하지 않는 파일 hash → None ───────────────────────────

def test_tc19_hash_nonexistent_returns_none(gk, tmp_path):
    """TC-19: 존재하지 않는 파일 _sha256_file() → None."""
    assert gk._sha256_file(str(tmp_path / "ghost.md")) is None


# ── TC-20: 정상 execute_write 전체 플로우 ───────────────────────────

def test_tc20_full_write_flow_pass(gk, stored_approval, sandbox, registry):
    """TC-20: approval 저장 후 execute_write 정상 완료."""
    target = stored_approval["scope"]["target_path"]
    result = gk.execute_write(stored_approval["approval_id"], target, "# AIBA Write Test")
    assert result["result"] == "PASS"
    assert os.path.exists(target)
    # audit 기록 확인
    audit_file = str(registry / "audit" / "mcp_write_audit.jsonl")
    assert os.path.exists(audit_file)
    with open(audit_file) as f:
        lines = f.readlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["result"] == "PASS"
    assert event["actor"] == "caddy"
    # snapshot 확인
    snap_files = os.listdir(str(registry / "snapshots"))
    assert len(snap_files) == 1

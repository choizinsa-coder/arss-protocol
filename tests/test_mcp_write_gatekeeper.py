"""
test_mcp_write_gatekeeper.py — MCP Write Gatekeeper pytest v1.1.0
TC-01~20: 기존 테스트 (하위 호환)
TC-21~29: 강제 장치 P0~P3 테스트
"""

import hashlib
import json
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "mcp"))

from mcp_write_gatekeeper import MCP_WriteGatekeeper, WritePlaneState, FailClosedError, ALLOWED_EXTENSIONS
from mcp_approval_authority import generate_approval, validate_path, validate_extension, compute_receipt_hash
from mcp_write_config import ALLOWED_SANDBOX_PATHS, SOFT_TOKEN_TTL


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def sandbox(tmp_path):
    sb = tmp_path / "sandbox"
    sb.mkdir()
    return sb


@pytest.fixture
def registry(tmp_path):
    reg = tmp_path / "registry"
    for d in ["approvals", "audit", "snapshots", "receipts", "baselines"]:
        (reg / d).mkdir(parents=True)
    return reg


@pytest.fixture
def gk(tmp_path, sandbox, registry):
    return MCP_WriteGatekeeper(
        allowed_paths=[str(sandbox) + "/"],
        forbidden_prefixes=[str(tmp_path / "registry") + "/"],
        approvals_dir=str(registry / "approvals"),
        audit_dir=str(registry / "audit"),
        snapshots_dir=str(registry / "snapshots"),
        receipts_dir=str(registry / "receipts"),
        baselines_dir=str(registry / "baselines"),
    )


@pytest.fixture
def content_bytes():
    return b"# AIBA Write Test v1.1"


@pytest.fixture
def approval(sandbox, content_bytes):
    target = str(sandbox / "test.md")
    return generate_approval(target, ".md",
                             allowed_paths=[str(sandbox) + "/"],
                             content_bytes=content_bytes)


@pytest.fixture
def stored_approval(gk, approval, registry):
    f = os.path.join(str(registry / "approvals"), f"{approval['approval_id']}.json")
    with open(f, "w") as fp:
        json.dump(approval, fp)
    return approval


# ── TC-01~TC-19: 기존 테스트 (하위 호환) ─────────────────────────────

def test_tc01_sandbox_path_allowed(gk, sandbox):
    assert gk._validate_path(str(sandbox / "test.md")) is True

def test_tc02_registry_path_blocked(gk, registry):
    assert gk._validate_path(str(registry / "audit" / "test.md")) is False

def test_tc03_outside_sandbox_blocked(gk, tmp_path):
    assert gk._validate_path(str(tmp_path / "outside.md")) is False

def test_tc04_allowed_extensions_pass(gk):
    for ext in [".md", ".json", ".txt"]:
        assert gk._validate_extension(f"file{ext}") is True

def test_tc05_forbidden_extensions_blocked(gk):
    for ext in [".py", ".sh", ".env", ".yaml", ".yml", ".service"]:
        assert gk._validate_extension(f"file{ext}") is False

def test_tc06_approval_hash_integrity(approval):
    from mcp_approval_authority import compute_approval_hash
    stored = approval["approval_hash"]
    assert compute_approval_hash(approval) == stored

def test_tc07_tampered_approval_hash_rejected(gk, approval, sandbox):
    approval["approval_hash"] = "deadbeef" * 8
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, str(sandbox / "test.md"), ".md")
    assert exc.value.tier == "T4"

def test_tc08_expired_approval_rejected(gk, sandbox, content_bytes):
    import datetime
    target = str(sandbox / "test.md")
    a = generate_approval(target, ".md", allowed_paths=[str(sandbox) + "/"], content_bytes=content_bytes)
    old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=700)).isoformat()
    a["approved_at"] = old_time
    from mcp_approval_authority import compute_approval_hash
    body = {k: v for k, v in a.items() if k != "approval_hash"}
    a["approval_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(a, target, ".md")
    assert exc.value.tier == "T4"

def test_tc09_approval_path_mismatch_rejected(gk, approval, sandbox):
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, str(sandbox / "other.md"), ".md")
    assert exc.value.tier == "T4"

def test_tc10_approval_reuse_blocked(gk, approval, sandbox):
    gk._used_approvals.add(approval["approval_id"])
    with pytest.raises(FailClosedError) as exc:
        gk._verify_approval(approval, str(sandbox / "test.md"), ".md")
    assert exc.value.tier == "T4"

def test_tc11_token_single_use(gk, sandbox):
    target = str(sandbox / "test.md")
    tid = gk._issue_token("appr-001", target, ".md")
    gk._consume_token(tid, target)
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(tid, target)
    assert exc.value.tier == "T4"

def test_tc12_token_ttl_expired(gk, sandbox):
    target = str(sandbox / "test.md")
    tid = gk._issue_token("appr-002", target, ".md")
    with gk._token_lock:
        gk._token_store[tid]["ttl"] = -1
        gk._token_store[tid]["soft_ttl"] = -1
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(tid, target)
    assert exc.value.tier == "T4"

def test_tc13_token_path_mismatch(gk, sandbox):
    t1, t2 = str(sandbox / "a.md"), str(sandbox / "b.md")
    tid = gk._issue_token("appr-003", t1, ".md")
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(tid, t2)
    assert exc.value.tier == "T4"

def test_tc14_write_blocked_when_locked(gk, sandbox):
    gk._set_state(WritePlaneState.LOCKED)
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write("any", str(sandbox / "test.md"), "content")
    assert exc.value.tier == "T3"

def test_tc15_write_blocked_when_hold(gk, sandbox):
    gk._set_state(WritePlaneState.HOLD)
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write("any", str(sandbox / "test.md"), "content")
    assert exc.value.tier == "T2"

def test_tc16_recovery_mode_single_write_exhausted(gk):
    gk._set_state(WritePlaneState.RECOVERY_MODE)
    gk._recovery_write_used = True
    with pytest.raises(FailClosedError) as exc:
        gk._assert_writable()
    assert exc.value.tier == "T3"

def test_tc17_recovery_close_returns_normal(gk):
    gk._set_state(WritePlaneState.RECOVERY_MODE)
    gk.beo_recovery_close()
    assert gk.get_state() == WritePlaneState.NORMAL

def test_tc18_sha256_hash_correctness(gk, tmp_path):
    f = tmp_path / "check.txt"
    f.write_bytes(b"hello AIBA")
    assert gk._sha256_file(str(f)) == hashlib.sha256(b"hello AIBA").hexdigest()

def test_tc19_hash_nonexistent_returns_none(gk, tmp_path):
    assert gk._sha256_file(str(tmp_path / "ghost.md")) is None


# ── TC-20: 정상 플로우 (content_bytes 포함) ───────────────────────────

def test_tc20_full_write_flow_pass(gk, stored_approval, sandbox, registry, content_bytes):
    target = stored_approval["scope"]["target_path"]
    content_str = content_bytes.decode("utf-8")
    result = gk.execute_write(stored_approval["approval_id"], target, content_str)
    assert result["result"] == "PASS"
    assert os.path.exists(target)
    # audit 확인
    audit_file = str(registry / "audit" / "mcp_write_audit.jsonl")
    assert os.path.exists(audit_file)
    event = json.loads(open(audit_file).readlines()[0])
    assert event["result"] == "PASS"
    # receipt 확인
    receipts = os.listdir(str(registry / "receipts"))
    assert len(receipts) == 1
    receipt = json.load(open(str(registry / "receipts" / receipts[0])))
    assert receipt["status"] == "PENDING_BEO_REVIEW"
    assert receipt["result"] == "PASS"


# ── TC-21: P0 — content hash 일치 시 통과 ────────────────────────────

def test_tc21_content_hash_match_passes(gk, stored_approval, sandbox, content_bytes):
    target = stored_approval["scope"]["target_path"]
    content_str = content_bytes.decode("utf-8")
    result = gk.execute_write(stored_approval["approval_id"], target, content_str)
    assert result["result"] == "PASS"


# ── TC-22: P0 — content hash 불일치 시 FC-T4 ─────────────────────────

def test_tc22_content_hash_mismatch_fc_t4(gk, stored_approval, sandbox):
    target = stored_approval["scope"]["target_path"]
    # 다른 content 쓰기 시도
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write(stored_approval["approval_id"], target, "DIFFERENT CONTENT NOT APPROVED")
    assert exc.value.tier == "T4"
    assert "content hash mismatch" in exc.value.reason


# ── TC-23: P0 — expected_content_hash 없는 approval FC-T4 ────────────

def test_tc23_missing_expected_hash_fc_t4(gk, sandbox, registry):
    target = str(sandbox / "test.md")
    # expected_content_hash 없는 approval 생성
    a = generate_approval(target, ".md", allowed_paths=[str(sandbox) + "/"])
    # scope에서 expected_content_hash 제거 (None으로 유지 — 기본값)
    f = os.path.join(str(registry / "approvals"), f"{a['approval_id']}.json")
    with open(f, "w") as fp:
        json.dump(a, fp)
    with pytest.raises(FailClosedError) as exc:
        gk.execute_write(a["approval_id"], target, "any content")
    assert exc.value.tier == "T4"


# ── TC-24: P1 — unconfirmed receipt 시 FC-T2 ─────────────────────────

def test_tc24_unconfirmed_receipt_blocks_write(gk, stored_approval, sandbox, registry, content_bytes):
    # 먼저 정상 write → receipt 생성
    target = stored_approval["scope"]["target_path"]
    gk.execute_write(stored_approval["approval_id"], target, content_bytes.decode())

    # 두 번째 approval (unconfirmed receipt 있음 + confirmation 없음)
    content2 = b"second write"
    a2 = generate_approval(target, ".md", allowed_paths=[str(sandbox) + "/"], content_bytes=content2)
    f2 = os.path.join(str(registry / "approvals"), f"{a2['approval_id']}.json")
    with open(f2, "w") as fp:
        json.dump(a2, fp)

    with pytest.raises(FailClosedError) as exc:
        gk.execute_write(a2["approval_id"], target, content2.decode())
    assert exc.value.tier == "T2"
    assert "unconfirmed receipt" in exc.value.reason


# ── TC-25: P1 — previous_receipt_confirmation 포함 시 통과 ───────────

def test_tc25_confirmed_receipt_unlocks_next_write(gk, stored_approval, sandbox, registry, content_bytes):
    # 1차 write
    target = stored_approval["scope"]["target_path"]
    gk.execute_write(stored_approval["approval_id"], target, content_bytes.decode())

    # receipt 파일 찾기
    receipts_dir = str(registry / "receipts")
    receipt_files = os.listdir(receipts_dir)
    receipt_path = os.path.join(receipts_dir, receipt_files[0])
    receipt = json.load(open(receipt_path))
    receipt_id = receipt["receipt_id"]
    receipt_hash = compute_receipt_hash(receipt_path)

    # 2차 approval — confirmation 포함
    content2 = b"confirmed second write"
    a2 = generate_approval(
        target, ".md",
        allowed_paths=[str(sandbox) + "/"],
        content_bytes=content2,
        previous_receipt_id=receipt_id,
        receipts_dir=receipts_dir,
    )
    f2 = os.path.join(str(registry / "approvals"), f"{a2['approval_id']}.json")
    with open(f2, "w") as fp:
        json.dump(a2, fp)

    result = gk.execute_write(a2["approval_id"], target, content2.decode())
    assert result["result"] == "PASS"


# ── TC-26: P2 — TOKEN_SOFT_EXPIRED FC-T1 ─────────────────────────────

def test_tc26_token_soft_expired_fc_t1(gk, sandbox):
    target = str(sandbox / "test.md")
    tid = gk._issue_token("appr-soft", target, ".md")
    with gk._token_lock:
        # soft_ttl만 초과 (ttl는 초과 안 함)
        gk._token_store[tid]["soft_ttl"] = -1
        gk._token_store[tid]["ttl"] = 9999
    with pytest.raises(FailClosedError) as exc:
        gk._consume_token(tid, target)
    assert exc.value.tier == "T1"
    assert "TOKEN_SOFT_EXPIRED" in exc.value.reason
    # FC-T1: Write Plane LOCK 없어야 함
    assert gk.get_state() == WritePlaneState.NORMAL


# ── TC-27: P3 — baseline 최초 생성 ───────────────────────────────────

def test_tc27_baseline_created_on_first_write(gk, stored_approval, sandbox, registry, content_bytes):
    target = stored_approval["scope"]["target_path"]
    assert len(os.listdir(str(registry / "baselines"))) == 0
    gk.execute_write(stored_approval["approval_id"], target, content_bytes.decode())
    # write 후 baseline 생성됨
    baselines = os.listdir(str(registry / "baselines"))
    assert len(baselines) >= 1


# ── TC-28: P3 — baseline drift 탐지 FC-T3 ────────────────────────────

def test_tc28_baseline_drift_fc_t3(gk, sandbox, registry, content_bytes):
    """
    TC-28: sandbox 파일이 외부에서 변조되면 baseline drift FC-T3 발생.
    receipt 개입 없이 _create_baseline() 직접 사용.
    """
    # 파일 생성 후 baseline 확정
    target = str(sandbox / "baseline_test.md")
    with open(target, "w") as f:
        f.write("original content")
    gk._create_baseline()

    # 외부 변조 시뮬레이션 (MCP 외부 SSH 접근 등)
    with open(target, "w") as f:
        f.write("UNAUTHORIZED MODIFICATION")

    # write 시도 → drift 탐지 FC-T3
    content2 = b"new approved content"
    target2 = str(sandbox / "new_file.md")
    a2 = generate_approval(target2, ".md", allowed_paths=[str(sandbox) + "/"], content_bytes=content2)
    f2 = os.path.join(str(registry / "approvals"), f"{a2['approval_id']}.json")
    with open(f2, "w") as fp:
        json.dump(a2, fp)

    with pytest.raises(FailClosedError) as exc:
        gk.execute_write(a2["approval_id"], target2, content2.decode())
    assert exc.value.tier == "T3"
    assert "drift" in exc.value.reason


# ── TC-29: P1 — receipt status PENDING_BEO_REVIEW 확인 ───────────────

def test_tc29_receipt_always_pending_beo_review(gk, stored_approval, sandbox, registry, content_bytes):
    target = stored_approval["scope"]["target_path"]
    gk.execute_write(stored_approval["approval_id"], target, content_bytes.decode())
    receipts_dir = str(registry / "receipts")
    receipt_files = os.listdir(receipts_dir)
    assert len(receipt_files) == 1
    receipt = json.load(open(os.path.join(receipts_dir, receipt_files[0])))
    assert receipt["status"] == "PENDING_BEO_REVIEW"
    assert receipt["hash_match"] is True
    assert receipt["schema"] == "MCP_WRITE_RESULT_RECEIPT_v1"

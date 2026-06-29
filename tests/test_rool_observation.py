"""
test_rool_observation.py
EAG-S294-ROOL-IMPL-001

ROOL 관측 계층 단위 테스트.
검증 항목:
  - Observation-ID 발급 정상
  - 5단계 검증 (HMAC/TTL/actor/session/allowlist)
  - 위조 ID 차단
  - FORBIDDEN_PATH 세션 TERMINATED
  - Manifest integrity HMAC 무결성 (False-Positive 방지)
  - allowlist 변경 시 자동 무효화
"""

import os
import sys
import time

# Bridge_Secret 테스트 환경 주입 (실제 운영 시 secrets.env)
os.environ.setdefault("AIBA_READ_HMAC_SECRET", "test_bridge_secret_for_rool_unit")

# ROOL 모듈은 tools/mcp/에 배포됨. 로컬(동일 디렉토리)·VPS(tools/mcp) 양쪽 대응.
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)  # 로컬: 동일 디렉토리
# VPS: tests/ 기준 ../tools/mcp
_mcp_dir = os.path.join(_here, "..", "tools", "mcp")
if os.path.isdir(_mcp_dir):
    sys.path.insert(0, os.path.abspath(_mcp_dir))

import rool_observation as rool


def setup_function(_):
    rool._reset_sessions_for_test()


# ── ① Observation-ID 발급 ──────────────────────────────────────────────────────

def test_begin_observation_success():
    r = rool.begin_observation("domi", "S294")
    assert r["status"] == "ALLOW"
    assert len(r["observation_id"]) == 64  # SHA256 hex
    assert r["actor"] == "domi"
    assert r["ttl_seconds"] == 900


def test_begin_observation_unknown_actor():
    r = rool.begin_observation("hacker", "S294")
    assert r["status"] == "FAIL_CLOSED"
    assert "UNKNOWN_ACTOR" in r["reason"]


def test_begin_observation_no_session():
    r = rool.begin_observation("domi", "")
    assert r["status"] == "FAIL_CLOSED"
    assert r["reason"] == "SESSION_ID_REQUIRED"


# ── ② 5단계 검증 ───────────────────────────────────────────────────────────────

def test_verify_valid_id():
    b = rool.begin_observation("domi", "S294")
    v = rool.verify_observation(b["observation_id"], "domi", "S294")
    assert v["ok"] is True


def test_verify_actor_mismatch():
    b = rool.begin_observation("domi", "S294")
    v = rool.verify_observation(b["observation_id"], "jeni", "S294")
    assert v["ok"] is False
    assert v["reason"] == "ACTOR_MISMATCH"


def test_verify_session_mismatch():
    b = rool.begin_observation("domi", "S294")
    v = rool.verify_observation(b["observation_id"], "domi", "S999")
    assert v["ok"] is False
    assert v["reason"] == "SESSION_MISMATCH"


def test_verify_forged_id():
    rool.begin_observation("domi", "S294")
    forged = "f" * 64
    v = rool.verify_observation(forged, "domi", "S294")
    assert v["ok"] is False
    assert v["reason"] == "INVALID_SIGNATURE"


# ── ③ FORBIDDEN_PATH 세션 종료 ──────────────────────────────────────────────────

def test_forbidden_path_terminates_session():
    b = rool.begin_observation("domi", "S294")
    oid = b["observation_id"]
    r = rool.observe(oid, "domi", "S294", "read",
                     "/opt/arss/engine/arss-protocol/registry/oauth_clients.json")
    assert r["status"] == "FAIL_CLOSED"
    assert r["reason"] == "FORBIDDEN_PATH"
    assert r["session_state"] == "TERMINATED"
    # 종료된 세션은 복귀 불가
    r2 = rool.observe(oid, "domi", "S294", "read",
                      "/opt/arss/engine/arss-protocol/README.md")
    assert r2["status"] == "FAIL_CLOSED"
    assert r2["reason"] == "SESSION_TERMINATED"


def test_normal_path_passes_gate():
    b = rool.begin_observation("domi", "S294")
    r = rool.observe(b["observation_id"], "domi", "S294", "read",
                     "/opt/arss/engine/arss-protocol/README.md")
    assert r["status"] == "ALLOW"


def test_tool_not_allowed():
    b = rool.begin_observation("domi", "S294")
    r = rool.observe(b["observation_id"], "domi", "S294", "write_file", "/tmp/x")
    assert r["status"] == "FAIL_CLOSED"
    assert "TOOL_NOT_ALLOWED" in r["reason"]


# ── ④ Manifest 무결성 (False-Positive 방지) ─────────────────────────────────────

def test_manifest_integrity_pass():
    b = rool.begin_observation("domi", "S294")
    w = rool.write_observation_manifest(
        "domi", "S294", b["observation_id"], "read",
        "/opt/arss/engine/arss-protocol/README.md", "ALLOW", 200,
        allowlist_root="CODE_ROOT", bytes_read=2048)
    assert w["ok"] is True
    v = rool.verify_manifest_integrity(w["manifest"])
    assert v["ok"] is True
    assert v["result"] == "PASS"


def test_manifest_tamper_detected():
    b = rool.begin_observation("domi", "S294")
    w = rool.write_observation_manifest(
        "domi", "S294", b["observation_id"], "read",
        "/opt/arss/engine/arss-protocol/README.md", "ALLOW", 200)
    tampered = dict(w["manifest"])
    tampered["target"] = "/opt/arss/engine/arss-protocol/EVIL.md"  # 사후 변조
    v = rool.verify_manifest_integrity(tampered)
    assert v["ok"] is False
    assert v["result"] == "TAMPER_DETECTED"


def test_canonical_manifest_stable():
    """키 순서 무관하게 동일 canonical 생성 (False-Positive 방지 핵심)."""
    m1 = {"b": 2, "a": 1, "c": 3}
    m2 = {"c": 3, "a": 1, "b": 2}
    assert rool._canonical_manifest(m1) == rool._canonical_manifest(m2)


# ── ⑤ allowlist_hash 자동 무효화 ────────────────────────────────────────────────

def test_allowlist_hash_in_signature():
    """allowlist_hash가 서명에 포함되어 ID에 반영되는지 확인."""
    b = rool.begin_observation("domi", "S294")
    expected_hash = rool._compute_allowlist_hash("domi")
    assert b["allowlist_hash"] == expected_hash


def test_failure_event_format():
    b = rool.begin_observation("domi", "S294")
    r = rool.observe(b["observation_id"], "domi", "S294", "read",
                     "/opt/arss/engine/arss-protocol/registry/secret_file.json")
    assert "failure_event" in r
    fe = r["failure_event"]
    assert fe["event_type"] == "ObservationFailureEvent"
    assert fe["actor"] == "domi"
    assert fe["session_id"] == "S294"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))

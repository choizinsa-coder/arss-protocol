"""
test_aics_token.py
AICS Governance Token 검증 — TC-01 ~ TC-05
EAG-S271-AICS-001
"""

from datetime import timedelta

from tools.aics.identity_registry import IdentityRegistry
from tools.aics.governance_token import GovernanceTokenManager
from tools.aics.schemas import AICSReason, utc_now


SESSION = 271
CHAIN_TIP = "69bb3e7"


def _mgr():
    return GovernanceTokenManager(registry=IdentityRegistry())


def test_tc01_valid_token_passes():
    """TC-01: 정상 발급 → 검증 PASS."""
    mgr = _mgr()
    tok = mgr.issue_token("domi", SESSION, CHAIN_TIP)
    assert tok is not None
    res = mgr.validate_token(tok.token_id, "domi", SESSION, CHAIN_TIP)
    assert res.ok is True
    assert res.reason == AICSReason.OK


def test_tc02_expired_token_fails():
    """TC-02: 만료 토큰 → FAIL."""
    mgr = _mgr()
    tok = mgr.issue_token("domi", SESSION, CHAIN_TIP, ttl_sec=1)
    # 강제로 만료 시각을 과거로 설정
    tok.expires_at = (utc_now() - timedelta(seconds=10)).isoformat()
    res = mgr.validate_token(tok.token_id, "domi", SESSION, CHAIN_TIP)
    assert res.ok is False
    assert res.reason == AICSReason.TOKEN_EXPIRED


def test_tc03_actor_forgery_fails():
    """TC-03: actor_id 위조 (domi 토큰을 hermes 로 사용) → FAIL."""
    mgr = _mgr()
    tok = mgr.issue_token("domi", SESSION, CHAIN_TIP)
    res = mgr.validate_token(tok.token_id, "hermes", SESSION, CHAIN_TIP)
    assert res.ok is False
    assert res.reason == AICSReason.ACTOR_MISMATCH


def test_tc04_session_mismatch_fails():
    """TC-04: session 불일치 (270 토큰을 271 에서 사용) → FAIL."""
    mgr = _mgr()
    tok = mgr.issue_token("domi", 270, CHAIN_TIP)
    res = mgr.validate_token(tok.token_id, "domi", 271, CHAIN_TIP)
    assert res.ok is False
    assert res.reason == AICSReason.SESSION_MISMATCH


def test_tc05_chain_tip_mismatch_fails():
    """TC-05: chain.tip 불일치 → FAIL."""
    mgr = _mgr()
    tok = mgr.issue_token("domi", SESSION, "old1234")
    res = mgr.validate_token(tok.token_id, "domi", SESSION, "69bb3e7")
    assert res.ok is False
    assert res.reason == AICSReason.CHAIN_TIP_MISMATCH


def test_unregistered_actor_cannot_issue():
    """미등록 에이전트는 토큰 발급 불가 (None)."""
    mgr = _mgr()
    tok = mgr.issue_token("hermes_child", SESSION, CHAIN_TIP)
    assert tok is None


def test_token_not_found_fails():
    mgr = _mgr()
    res = mgr.validate_token("nonexistent-id", "domi", SESSION, CHAIN_TIP)
    assert res.ok is False
    assert res.reason == AICSReason.TOKEN_NOT_FOUND


def test_chain_change_auto_revoke():
    """chain.tip 변경 시 불일치 토큰 자동 폐기."""
    mgr = _mgr()
    mgr.issue_token("domi", SESSION, "old1234")
    mgr.issue_token("jeni", SESSION, "69bb3e7")
    revoked = mgr.revoke_on_chain_change("69bb3e7")
    assert revoked == 1
    assert mgr.active_count() == 1

# tests/test_observation_server.py
# RULE-8 Batch-13C — S182
# 설계: 도미 BRIEFING-CADDY-S182-BATCH13-DOMI-DESIGN-1 (D-2: 순수 함수 범위 한정)
# EAG: EAG-S182-BATCH13C (비오 승인)
# 제니 TRUST-ADVISORY: engage_fail_closed ↔ is_observation_locked 인과 관계 연계 assertion 배치
# 대상: tools/observation_server.py — 순수 함수 5개
#
# 검증 대상: register_token / revoke_token / validate_token / engage_fail_closed / is_observation_locked
# 제외 범위: ObservationHandler / HTTP / Socket / Threading (도미 D-2 / 통합 테스트 이관)
# Assertion 우선순위: Guard Condition → Contract Integrity → State Result → Happy Path

import sys
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools")

from observation_server import (
    register_token,
    revoke_token,
    validate_token,
    engage_fail_closed,
    is_observation_locked,
    _system_state,
    _token_store,
    _fail_closed_lock,
    _token_lock,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    """각 테스트 전후 전역 상태 초기화 — 테스트 간 격리 보장"""
    with _fail_closed_lock:
        _system_state["observation_locked"] = False
        _system_state["lock_reason"] = None
        _system_state["lock_time"] = None
        _system_state["incident_id"] = None
    with _token_lock:
        _token_store.clear()
    yield
    with _fail_closed_lock:
        _system_state["observation_locked"] = False
        _system_state["lock_reason"] = None
        _system_state["lock_time"] = None
        _system_state["incident_id"] = None
    with _token_lock:
        _token_store.clear()


# ── P1: Guard Condition — validate_token ──────────────────────────────────

def test_validate_token_unregistered_returns_token_required():
    """미등록 agent → (False, TOKEN_REQUIRED)"""
    ok, reason = validate_token("domi", "any_token")
    assert ok is False
    assert reason == "TOKEN_REQUIRED"


def test_validate_token_revoked_returns_token_revoked():
    """revoke 후 validate → (False, TOKEN_REVOKED)"""
    register_token("domi", "test_token_value")
    revoke_token("domi")
    ok, reason = validate_token("domi", "test_token_value")
    assert ok is False
    assert reason == "TOKEN_REVOKED"


def test_validate_token_hash_mismatch_returns_token_agent_mismatch():
    """등록된 토큰과 다른 값 → (False, TOKEN_AGENT_MISMATCH)"""
    register_token("domi", "correct_token")
    ok, reason = validate_token("domi", "wrong_token")
    assert ok is False
    assert reason == "TOKEN_AGENT_MISMATCH"


# ── P2: Contract Integrity — register_token + validate_token ──────────────

def test_register_token_then_validate_succeeds():
    """register 후 validate → (True, OK)"""
    register_token("jeni", "valid_token_jeni")
    ok, reason = validate_token("jeni", "valid_token_jeni")
    assert ok is True
    assert reason == "OK"


def test_register_token_returns_hash_prefix():
    """register_token → token_hash_prefix 16자 반환"""
    meta = register_token("domi", "some_token")
    assert "token_hash_prefix" in meta
    assert len(meta["token_hash_prefix"]) == 16
    assert "expires_at" in meta


# ── P3: State Result — engage_fail_closed ↔ is_observation_locked 인과 관계
# [제니 TRUST-ADVISORY] 두 상태 전이의 인과 관계 연계 assertion

def test_initial_state_not_locked():
    """초기 상태 → is_observation_locked() = False"""
    assert is_observation_locked() is False


def test_engage_fail_closed_sets_locked_true():
    """engage_fail_closed 호출 → is_observation_locked() = True (인과 관계 검증)"""
    assert is_observation_locked() is False  # 사전 상태 확인
    engage_fail_closed("TEST_REASON", incident_id="INC-TEST-001")
    assert is_observation_locked() is True   # 인과 결과 확인


def test_engage_fail_closed_lock_reason_persisted():
    """engage_fail_closed 호출 후 lock_reason 내부 상태 기록 확인"""
    engage_fail_closed("SANDBOX_ESCAPE_DETECTED", incident_id="INC-TEST-002")
    with _fail_closed_lock:
        assert _system_state["lock_reason"] == "SANDBOX_ESCAPE_DETECTED"
        assert _system_state["incident_id"] == "INC-TEST-002"
        assert _system_state["observation_locked"] is True

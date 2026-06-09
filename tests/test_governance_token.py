# tests/test_governance_token.py
"""
EAG-S210-TOKEN-001: Beo 관리자 토큰 저장소 강화 검증
TC-01: 미등록 토큰 거부 (TOKEN_NOT_FOUND)
TC-02: 정상 등록 토큰 통과
TC-03: revoked 토큰 거부 (TOKEN_REVOKED)
TC-04: issuer 위조 거부 (TOKEN_ISSUER_INVALID)
TC-05: registry 읽기 실패 Fail-Closed (TOKEN_REGISTRY_UNAVAILABLE)
"""
import json
import sys
import os
import pytest

sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/ledger")


# ── 픽스처 ─────────────────────────────────────────────────────────────────

@pytest.fixture
def token_registry_patch(tmp_path, monkeypatch):
    """
    _load_token_registry를 tmp_path 기반 레지스트리로 교체.
    반환값: (registry_dict, set_registry_fn)
    """
    registry = {}
    registry_path = tmp_path / "ledger_tokens.json"

    def _mock_load():
        if not registry_path.exists():
            return {}
        with open(registry_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _set_registry(data):
        with open(registry_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    import governance_manager as gm
    monkeypatch.setattr(gm, "_load_token_registry", _mock_load)
    return _set_registry


@pytest.fixture
def fail_registry(monkeypatch):
    """_load_token_registry가 None 반환 (읽기 실패 시뮬레이션)"""
    import governance_manager as gm
    monkeypatch.setattr(gm, "_load_token_registry", lambda: None)


# ── TC-01: 미등록 토큰 거부 ────────────────────────────────────────────────

def test_tc01_unregistered_token_rejected(token_registry_patch):
    """미등록 토큰은 TOKEN_NOT_FOUND 반환"""
    token_registry_patch({})  # 빈 레지스트리

    import governance_manager as gm
    valid, reason = gm.validate_beo_token("unknown-token-xyz")

    assert valid is False
    assert reason == "TOKEN_NOT_FOUND"


# ── TC-02: 정상 등록 토큰 통과 ────────────────────────────────────────────

def test_tc02_valid_token_passes(token_registry_patch):
    """issuer=beo_loopback + scope=governance_release + revoked=False → 통과"""
    token_registry_patch({
        "beo-test-token": {
            "token_id": "beo-test-token",
            "actor": "caddy",
            "session": "S210",
            "scope": "governance_release",
            "issuer": "beo_loopback",
            "revoked": False,
            "revoked_reason": None,
            "revoked_at": None,
        }
    })

    import governance_manager as gm
    valid, reason = gm.validate_beo_token("beo-test-token")

    assert valid is True
    assert reason == "OK"


# ── TC-03: revoked 토큰 거부 ──────────────────────────────────────────────

def test_tc03_revoked_token_rejected(token_registry_patch):
    """revoked=True 토큰은 TOKEN_REVOKED 반환"""
    token_registry_patch({
        "beo-revoked-token": {
            "token_id": "beo-revoked-token",
            "actor": "caddy",
            "session": "S210",
            "scope": "governance_release",
            "issuer": "beo_loopback",
            "revoked": True,
            "revoked_reason": "SESSION_FREEZE",
            "revoked_at": "2026-06-09T00:00:00+09:00",
        }
    })

    import governance_manager as gm
    valid, reason = gm.validate_beo_token("beo-revoked-token")

    assert valid is False
    assert reason == "TOKEN_REVOKED"


# ── TC-04: issuer 위조 거부 ────────────────────────────────────────────────

def test_tc04_forged_issuer_rejected(token_registry_patch):
    """issuer != beo_loopback 토큰은 TOKEN_ISSUER_INVALID 반환"""
    token_registry_patch({
        "forged-token": {
            "token_id": "forged-token",
            "actor": "caddy",
            "session": "S210",
            "scope": "governance_release",
            "issuer": "external",          # 위조
            "revoked": False,
            "revoked_reason": None,
            "revoked_at": None,
        }
    })

    import governance_manager as gm
    valid, reason = gm.validate_beo_token("forged-token")

    assert valid is False
    assert reason == "TOKEN_ISSUER_INVALID"


# ── TC-05: registry 읽기 실패 Fail-Closed ─────────────────────────────────

def test_tc05_registry_unavailable_fail_closed(fail_registry):
    """registry 읽기 실패 시 TOKEN_REGISTRY_UNAVAILABLE (Fail-Closed)"""
    import governance_manager as gm
    valid, reason = gm.validate_beo_token("any-token")

    assert valid is False
    assert reason == "TOKEN_REGISTRY_UNAVAILABLE"

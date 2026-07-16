"""
test_aics_safe_mode.py
AICS Safe Mode 검증 — TC-06 + 복구 권한 통제 (advisory ②)
EAG-S271-AICS-001
"""

from tools.aics.aics_runtime import AICSRuntime
from tools.aics.schemas import AICSReason


SESSION = 271
CHAIN_TIP = "69bb3e7"


def _runtime(tmp_path):
    return AICSRuntime(
        active_tokens_path=str(tmp_path / "active_tokens.json"),
        identity_registry_path=str(tmp_path / "identity_registry.json"),
        safe_mode_flag_path=str(tmp_path / "safe_mode.flag"),
    )


def test_tc06_safe_mode_revokes_all_tokens(tmp_path):
    """TC-06: Safe Mode 진입 → 모든 토큰 무효화 → 검증 FAIL."""
    rt = _runtime(tmp_path)
    tok = rt.issue("domi", SESSION, CHAIN_TIP)
    assert tok is not None
    # Safe Mode 진입 전: 정상
    assert rt.admit(tok.token_id, "domi", SESSION, CHAIN_TIP).ok is True
    # Safe Mode 진입
    assert rt.enable_safe_mode(reason="TEST") is True
    # 모든 토큰 무효화 → 검증 실패
    res = rt.admit(tok.token_id, "domi", SESSION, CHAIN_TIP)
    assert res.ok is False
    assert res.reason == AICSReason.SAFE_MODE_ACTIVE


def test_safe_mode_blocks_new_issue(tmp_path):
    """Safe Mode 중 신규 발급 거부."""
    rt = _runtime(tmp_path)
    rt.enable_safe_mode(reason="TEST")
    tok = rt.issue("domi", SESSION, CHAIN_TIP)
    assert tok is None


def test_recovery_denied_without_authority(tmp_path):
    """advisory ②: EAG/technical_match 없으면 복구 거부."""
    rt = _runtime(tmp_path)
    rt.enable_safe_mode(reason="TEST")
    ok, reason = rt.disable_safe_mode()  # 권한 없음
    assert ok is False
    assert reason == AICSReason.RECOVERY_DENIED
    assert rt.safe_mode.is_active() is True


def test_recovery_with_eag(tmp_path):
    """advisory ②: EAG 서명으로 복구 허용."""
    rt = _runtime(tmp_path)
    rt.enable_safe_mode(reason="TEST")
    ok, reason = rt.disable_safe_mode(eag_approval="EAG-S271-RECOVER-001")
    assert ok is True
    assert reason == AICSReason.OK
    assert rt.safe_mode.is_active() is False


def test_recovery_with_technical_match(tmp_path):
    """advisory ②: TECHNICAL_MATCH 로 복구 허용."""
    rt = _runtime(tmp_path)
    rt.enable_safe_mode(reason="TEST")
    ok, reason = rt.disable_safe_mode(technical_match=True)
    assert ok is True
    assert reason == AICSReason.OK


def test_recovery_requires_fresh_token(tmp_path):
    """복구 후 기존 토큰 재사용 금지 — 신규 발급 필요."""
    rt = _runtime(tmp_path)
    tok = rt.issue("domi", SESSION, CHAIN_TIP)
    rt.enable_safe_mode(reason="TEST")
    rt.disable_safe_mode(eag_approval="EAG-S271-RECOVER-001")
    # 기존 토큰은 무효화됨
    res = rt.admit(tok.token_id, "domi", SESSION, CHAIN_TIP)
    assert res.ok is False
    # 신규 발급은 정상
    tok2 = rt.issue("domi", SESSION, CHAIN_TIP)
    assert tok2 is not None
    assert rt.admit(tok2.token_id, "domi", SESSION, CHAIN_TIP).ok is True


def test_enable_rejects_unauthorized_caller(tmp_path):
    """EAG-S420-SAFEMODE-ENABLE-CALLER-001: enable()은 신뢰된 소유 런타임 경유만.
    직접 호출 및 신분 위장 시도는 거부(fail-closed)."""
    rt = _runtime(tmp_path)
    assert rt.enable_safe_mode(reason="TEST") is True
    rt.disable_safe_mode(eag_approval="EAG-S271-RECOVER-001")
    assert rt.safe_mode.is_active() is False
    # 직접 호출(caller 미제공): 거부
    assert rt.safe_mode.enable(reason="ATTACK") is False
    # 신분 위장 시도(다른 객체): 거부
    assert rt.safe_mode.enable(reason="ATTACK", caller=object()) is False
    assert rt.safe_mode.is_active() is False

"""
test_direct_channel.py
영역 8 Direct Channel (J2-8) 검증 — TC-01 ~ TC-10
EAG-S271-DIRECTCH-001 / 1차 스코프

MiniMax 의존 항목 제외. advisory ①(고영향 제한) / ②(replay) 포함.
"""

import pytest

from tools.aics.aics_runtime import AICSRuntime
from tools.direct_channel.cross_sign import CrossSigner
from tools.direct_channel.transaction_registry import TransactionRegistry
from tools.direct_channel.direct_channel import DirectChannel
from tools.direct_channel.schemas import Transaction, DCReason, sha256_hex


SESSION = 271
CHAIN_TIP = "6fd565b"
SIGNER_KEYS = {"domi": "domi-secret-key", "jeni": "jeni-secret-key",
               "caddy": "caddy-secret-key"}


def _channel(tmp_path, minimax_enabled=False):
    aics = AICSRuntime(
        active_tokens_path=str(tmp_path / "active_tokens.json"),
        identity_registry_path=str(tmp_path / "identity_registry.json"),
        safe_mode_flag_path=str(tmp_path / "safe_mode.flag"),
    )
    signer = CrossSigner(SIGNER_KEYS)
    registry = TransactionRegistry(persist_path=str(tmp_path / "tx_registry.json"))
    ch = DirectChannel(aics_runtime=aics, signer=signer, registry=registry,
                       transport_fn=None, minimax_enabled=minimax_enabled)
    return aics, ch


def test_tc01_valid_token_valid_cross_sign(tmp_path):
    """TC-01: 정상 토큰 + 정상 Cross-Sign → PASS."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "payload-A")
    assert res.ok is True
    assert res.reason == DCReason.OK
    assert res.domi_signature
    assert res.jeni_signature


def test_tc02_expired_token_fails(tmp_path):
    """TC-02: 만료/무효 토큰 → FAIL (AICS 게이트)."""
    aics, ch = _channel(tmp_path)
    res = ch.send("nonexistent-token", "domi", "jeni", SESSION, CHAIN_TIP, "p")
    assert res.ok is False
    assert res.reason == DCReason.TOKEN_INVALID


def test_tc03_domi_signature_tamper_fails(tmp_path):
    """TC-03: 도미 서명 위조 → 재검증 FAIL."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p")
    tx = Transaction(tx_id=res.tx_id, sender="domi", receiver="jeni",
                     session=SESSION, chain_tip=CHAIN_TIP,
                     payload_hash=sha256_hex("p"))
    bad = ch.verify_cross_sign(tx, "deadbeef", res.jeni_signature)
    assert bad.ok is False
    assert bad.reason == DCReason.DOMI_SIG_INVALID


def test_tc04_jeni_signature_tamper_fails(tmp_path):
    """TC-04: 제니 서명 위조 → 재검증 FAIL."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p")
    tx = Transaction(tx_id=res.tx_id, sender="domi", receiver="jeni",
                     session=SESSION, chain_tip=CHAIN_TIP,
                     payload_hash=sha256_hex("p"))
    bad = ch.verify_cross_sign(tx, res.domi_signature, "cafebabe")
    assert bad.ok is False
    assert bad.reason == DCReason.JENI_SIG_INVALID


def test_tc05_tx_id_tamper_fails(tmp_path):
    """TC-05: tx_id 위조 → 서명 canonical 불일치로 FAIL."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p")
    # tx_id 를 다른 값으로 위조
    tx_forged = Transaction(tx_id="forged-tx-id", sender="domi", receiver="jeni",
                            session=SESSION, chain_tip=CHAIN_TIP,
                            payload_hash=sha256_hex("p"))
    bad = ch.verify_cross_sign(tx_forged, res.domi_signature, res.jeni_signature)
    assert bad.ok is False
    assert bad.reason == DCReason.DOMI_SIG_INVALID


def test_tc06_chain_tip_mismatch_fails(tmp_path):
    """TC-06: chain_tip 불일치 토큰 → AICS FAIL."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, "old1234")
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, "6fd565b", "p")
    assert res.ok is False
    assert res.reason == DCReason.TOKEN_INVALID


def test_tc07_safe_mode_fails(tmp_path):
    """TC-07: Safe Mode 활성 → 채널 차단."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    aics.enable_safe_mode(reason="TEST")
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p")
    assert res.ok is False
    assert res.reason == DCReason.TOKEN_INVALID


def test_tc08_hermes_request_denied(tmp_path):
    """TC-08: 미등록 발신자(hermes) → 토큰 발급 불가 → 차단."""
    aics, ch = _channel(tmp_path)
    # hermes 는 Registry 미등록 → 토큰 발급 None
    tok = aics.issue("hermes", SESSION, CHAIN_TIP)
    assert tok is None
    # 위조 토큰 id 로 시도해도 AICS 차단
    res = ch.send("fake-token", "hermes", "jeni", SESSION, CHAIN_TIP, "p")
    assert res.ok is False
    assert res.reason == DCReason.TOKEN_INVALID


def test_tc09_replay_attack_blocked(tmp_path):
    """TC-09 (advisory ②): 동일 tx_id 재주입 → REPLAY_DETECTED."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p")
    assert res.ok is True
    # 이미 등록된 tx_id 를 registry 에 강제 재등록 시도
    second = ch._registry.register(res.tx_id)
    assert second is False  # 중복 차단


def test_tc10_constitutional_decision_restricted(tmp_path):
    """TC-10 (advisory ①): MiniMax 2차 전 Constitutional 결정 → 제한."""
    aics, ch = _channel(tmp_path, minimax_enabled=False)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p",
                  decision_class="Constitutional")
    assert res.ok is False
    assert res.reason == DCReason.CONSENSUS_RESTRICTED


def test_minimax_enabled_allows_governance(tmp_path):
    """2차(minimax_enabled=True) 시 Governance 결정 허용 (회귀 대비)."""
    aics, ch = _channel(tmp_path, minimax_enabled=True)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "p",
                  decision_class="Governance")
    assert res.ok is True


def test_valid_cross_sign_roundtrip(tmp_path):
    """정상 서명은 재검증을 통과 (verify_cross_sign 양성 경로)."""
    aics, ch = _channel(tmp_path)
    tok = aics.issue("domi", SESSION, CHAIN_TIP)
    res = ch.send(tok.token_id, "domi", "jeni", SESSION, CHAIN_TIP, "payload-X")
    tx = Transaction(tx_id=res.tx_id, sender="domi", receiver="jeni",
                     session=SESSION, chain_tip=CHAIN_TIP,
                     payload_hash=sha256_hex("payload-X"))
    ok = ch.verify_cross_sign(tx, res.domi_signature, res.jeni_signature)
    assert ok.ok is True

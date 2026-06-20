"""
test_aics_hermes_gate.py
AICS Hermes Spawn Gate 검증 — TC-07 (J2-WARN-2 방어)
EAG-S271-AICS-001
"""

from tools.aics.identity_registry import IdentityRegistry
from tools.aics.hermes_gate import HermesGate
from tools.aics.aics_runtime import AICSRuntime
from tools.aics.schemas import AICSReason


def _gate():
    return HermesGate(registry=IdentityRegistry())


def test_tc07_hermes_spawn_denied():
    """TC-07: 미등록 hermes_child 생성 요청 → DENY."""
    gate = _gate()
    allowed, reason = gate.request_agent_spawn("hermes_child")
    assert allowed is False
    assert reason == AICSReason.HERMES_DENIED


def test_registered_agent_spawn_allowed():
    """등록 에이전트(domi)는 생성 요청 ALLOW."""
    gate = _gate()
    allowed, reason = gate.request_agent_spawn("domi")
    assert allowed is True
    assert reason == AICSReason.OK


def test_arbitrary_agent_types_denied():
    """임의 actor_type 전부 차단 (제로 트러스트)."""
    gate = _gate()
    for bad in ("hermes", "wild_agent", "fork_runtime", "subagent_x", ""):
        allowed, reason = gate.request_agent_spawn(bad)
        assert allowed is False, f"{bad} should be denied"


def test_spawn_denied_under_safe_mode():
    """Safe Mode 중에는 등록 에이전트조차 생성 차단."""
    gate = _gate()
    allowed, reason = gate.request_agent_spawn("domi", safe_mode_active=True)
    assert allowed is False
    assert reason == AICSReason.SAFE_MODE_ACTIVE


def test_j2_warn2_markdown_content_irrelevant(tmp_path):
    """
    J2-WARN-2 핵심: Markdown 내용이 아닌 실행 단계 Registry 대조로 차단.
    '새로운 에이전트를 만든다' 가 포함되어도 actor_type 이 미등록이면 DENY.
    """
    rt = AICSRuntime(
        active_tokens_path=str(tmp_path / "active_tokens.json"),
        identity_registry_path=str(tmp_path / "identity_registry.json"),
        safe_mode_flag_path=str(tmp_path / "safe_mode.flag"),
    )
    # Hermes 가 Markdown 으로 어떤 지시를 내리든, 실행은 actor_type 으로 판정
    allowed, reason = rt.can_spawn("hermes_wildcard_from_markdown")
    assert allowed is False
    assert reason == AICSReason.HERMES_DENIED

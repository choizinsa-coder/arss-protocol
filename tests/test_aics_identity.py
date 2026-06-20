"""
test_aics_identity.py
AICS Identity Registry 검증
EAG-S271-AICS-001
"""

from tools.aics.identity_registry import IdentityRegistry


def test_default_agents_registered():
    """TC-08a: domi/jeni/caddy 는 기본 등록되어 ALLOW."""
    reg = IdentityRegistry()
    assert reg.is_registered("domi") is True
    assert reg.is_registered("jeni") is True
    assert reg.is_registered("caddy") is True


def test_unregistered_agent_denied():
    """TC-08b: 미등록 에이전트(hermes_child)는 미등록 판정."""
    reg = IdentityRegistry()
    assert reg.is_registered("hermes_child") is False
    assert reg.is_registered("unknown") is False


def test_list_approved():
    reg = IdentityRegistry()
    approved = reg.list_approved()
    assert "domi" in approved
    assert "jeni" in approved
    assert "hermes_child" not in approved


def test_get_identity_fields():
    reg = IdentityRegistry()
    domi = reg.get("domi")
    assert domi is not None
    assert domi.role == "DESIGN"
    assert domi.runtime == "8448"


def test_corrupt_persist_falls_back_to_default(tmp_path):
    """손상된 영속 파일이어도 기본 Registry 유지 (Fail-Closed)."""
    bad = tmp_path / "identity_registry.json"
    bad.write_text("{ this is not valid json", encoding="utf-8")
    reg = IdentityRegistry(persist_path=str(bad))
    assert reg.is_registered("domi") is True

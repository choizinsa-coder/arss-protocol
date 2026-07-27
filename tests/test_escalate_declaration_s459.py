# EAG-S459-ESCALATE-DECL-001
# S443 conditional-5 stage 1 contracts.
# Reads the real bridge source and loads the real module - no mock data.
import importlib.util
import os
import sys

import pytest

BRIDGE_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/mcp_http_bridge.py"
MCP_DIR = os.path.dirname(BRIDGE_PATH)


def _source():
    with open(BRIDGE_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def bridge():
    if MCP_DIR not in sys.path:
        sys.path.insert(0, MCP_DIR)
    spec = importlib.util.spec_from_file_location("mcp_http_bridge_s459", BRIDGE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_c1_helper_defined():
    assert _source().count("def _record_escalate_declaration(") == 1


def test_c2_called_for_domi():
    assert _source().count('_record_escalate_declaration("ask_domi"') == 1


def test_c3_called_for_jeni():
    assert _source().count('_record_escalate_declaration("ask_jeni"') == 1


def test_c4_missing_key_records_warn(bridge, monkeypatch):
    captured = []
    monkeypatch.setattr(bridge, "write_audit", lambda **kw: captured.append(kw))
    declared = bridge._record_escalate_declaration("ask_jeni", {"actor_id": "caddy"}, "S459")
    assert declared is False
    assert len(captured) == 1
    assert captured[0]["decision"] == "WARN"
    assert "ESCALATE_MISSING" in captured[0]["reason"]
    assert captured[0]["agent_id"] == "caddy"
    assert captured[0]["returned_scope"] == "escalate_declaration"


def test_c5_explicit_false_is_not_missing(bridge, monkeypatch):
    captured = []
    monkeypatch.setattr(bridge, "write_audit", lambda **kw: captured.append(kw))
    declared = bridge._record_escalate_declaration(
        "ask_jeni", {"actor_id": "caddy", "escalate": False}, "S459")
    assert declared is True
    assert captured == []


def test_c6_explicit_true_is_not_missing(bridge, monkeypatch):
    captured = []
    monkeypatch.setattr(bridge, "write_audit", lambda **kw: captured.append(kw))
    declared = bridge._record_escalate_declaration(
        "ask_domi", {"actor_id": "caddy", "escalate": True}, "S459")
    assert declared is True
    assert captured == []


def test_c7_audit_failure_does_not_raise(bridge, monkeypatch):
    def _boom(**kw):
        raise OSError("audit backend down")
    monkeypatch.setattr(bridge, "write_audit", _boom)
    assert bridge._record_escalate_declaration(
        "ask_jeni", {"actor_id": "caddy"}, "S459") is False


def test_c8_forward_contract_unchanged():
    src = _source()
    assert src.count('"escalate": escalate') == 2
    assert src.count('escalate = bool(arguments.get("escalate", False))') == 2


def test_c9_stage1_does_not_reject():
    src = _source()
    assert "ESCALATE_MISSING" in src
    assert "DENY: escalate" not in src

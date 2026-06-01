# RULE-8 ASSERTION — S181 Batch-12B
# Module: mcp_http_bridge (Bridge Input Validation Layer)
# Task: P4-C4 Phase-beta Batch-12B
# 범위: _handle_write_tool 입력 검증 레이어 한정
#        HTTP forwarding / containment / payload size → Batch-13+ hardening track
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest


def _call_write_tool(tool_name, arguments):
    from tools.mcp.mcp_http_bridge import _handle_write_tool
    return _handle_write_tool(tool_name, arguments)


def test_hb_write_file_wrong_actor_denied():
    """HB-1: write_file actor_id != 'caddy' → isError=True / DENY."""
    result = _call_write_tool("write_file", {
        "actor_id": "domi",
        "approval_id": "appr-001",
        "target_path": "/opt/arss/engine/arss-protocol/tools/sandbox/test.md",
        "content": "hello",
    })
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "DENY" in text


def test_hb_write_file_missing_approval_id_denied():
    """HB-2: write_file approval_id 없음 → isError=True / DENY."""
    result = _call_write_tool("write_file", {
        "actor_id": "caddy",
        "target_path": "/opt/arss/engine/arss-protocol/tools/sandbox/test.md",
        "content": "hello",
    })
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "DENY" in text


def test_hb_write_file_missing_target_path_denied():
    """HB-3: write_file target_path 없음 → isError=True / DENY."""
    result = _call_write_tool("write_file", {
        "actor_id": "caddy",
        "approval_id": "appr-001",
        "content": "hello",
    })
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "DENY" in text


def test_hb_write_file_unknown_field_denied():
    """HB-4: write_file unknown field 포함 → isError=True / DENY."""
    result = _call_write_tool("write_file", {
        "actor_id": "caddy",
        "approval_id": "appr-001",
        "target_path": "/opt/arss/engine/arss-protocol/tools/sandbox/test.md",
        "content": "hello",
        "unknown_extra_field": "INJECTED",
    })
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "DENY" in text


def test_hb_unknown_tool_not_permitted():
    """HB-5: ALLOWED_TOOLS 외 tool 호출 → isError=True / not permitted."""
    from tools.mcp.mcp_http_bridge import _handle_tool_call
    result = _handle_tool_call("totally_unknown_tool_xyz", {})
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert "not permitted" in text or "DENY" in text or "not" in text.lower()

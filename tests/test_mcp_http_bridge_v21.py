"""
test_mcp_http_bridge_v21.py
PT-S134-VPS-OBS-001 Phase 1 — Bridge v2.1.0 통합 테스트
"""

import sys
import json
import time
import unittest.mock as mock
from pathlib import Path
from unittest.mock import patch, MagicMock

# 다른 테스트 파일의 mock 오염 방지 — 관련 모듈 재로드
for _k in list(sys.modules.keys()):
    if _k in ('mcp_http_bridge', 'mcp_audit_broker', 'mcp_containment_state'):
        del sys.modules[_k]

sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "mcp"))

# mcp_audit_broker mock
audit_mock = MagicMock()
audit_mock.write_audit = MagicMock()
audit_mock.write_deny_audit = MagicMock()
sys.modules['mcp_audit_broker'] = audit_mock

# mcp_containment_state mock
containment_mock = MagicMock()
containment_mock.is_active = MagicMock(return_value=False)
sys.modules['mcp_containment_state'] = containment_mock

# 실제 mcp_read_server + mcp_http_bridge 임포트
import mcp_read_server  # noqa: F401 (실제 모듈 사용)
import importlib
import mcp_http_bridge
importlib.reload(mcp_http_bridge)

from mcp_http_bridge import (
    _handle_tool_list,
    _handle_tool_call,
    _handle_jsonrpc,
    _build_governance_context,
    ALLOWED_TOOLS,
    READ_TOOLS,
)

# ── TC-B01: ALLOWED_TOOLS에 READ 9종 포함 확인 ────────────────────
def test_tcb01_allowed_tools_contains_read():
    expected = {
        "read_file", "list_dir", "grep_scoped", "read_log",
        "check_service_state", "read_pytest_result",
        "read_audit_event", "read_metadata", "get_runtime_snapshot",
    }
    assert expected.issubset(ALLOWED_TOOLS)

# ── TC-B02: tool_list에 READ 도구 9종 노출 ────────────────────────
def test_tcb02_tool_list_includes_read_tools():
    result = _handle_tool_list()
    names = {t['name'] for t in result['tools']}
    assert "read_file" in names
    assert "get_runtime_snapshot" in names
    assert len([t for t in result['tools'] if t['name'] in READ_TOOLS]) == 9

# ── TC-B03: ping 여전히 동작 ──────────────────────────────────────
def test_tcb03_ping_still_works():
    result = _handle_tool_call("ping", {})
    assert not result.get("isError")
    assert "pong" in result['content'][0]['text']

# ── TC-B04: READ_HMAC_SECRET 미설정 시 DENY ──────────────────────
def test_tcb04_no_hmac_secret_deny():
    with patch('mcp_http_bridge.READ_HMAC_SECRET', ''):
        result = _handle_tool_call("read_file", {
            "path": "/some/path",
            "actor_id": "caddy",
            "purpose": "OBSERVATION",
        })
    assert result['isError']
    assert "READ_HMAC_SECRET" in result['content'][0]['text']

# ── TC-B05: unknown actor_id DENY ────────────────────────────────
def test_tcb05_unknown_actor_deny():
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'):
        result = _handle_tool_call("read_file", {
            "path": "/some/path",
            "actor_id": "hacker",
            "purpose": "OBSERVATION",
        })
    assert result['isError']
    assert "unknown actor_id" in result['content'][0]['text']

# ── TC-B06: ReadOnlyServer 호출 위임 확인 ────────────────────────
def test_tcb06_read_server_delegation():
    mock_instance = MagicMock()
    mock_instance.read_file.return_value = {"status": "ALLOW", "content": "hello"}
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'), \
         patch('mcp_http_bridge._read_server', mock_instance):
        result = _handle_tool_call("read_file", {
            "path": "/opt/arss/engine/arss-protocol/some.py",
            "actor_id": "caddy",
            "purpose": "OBSERVATION",
        })
    assert mock_instance.read_file.called

# ── TC-B07: READ 도구 DENY 결과 → isError=True ───────────────────
def test_tcb07_read_deny_maps_to_error():
    mock_instance = MagicMock()
    mock_instance.read_file.return_value = {"status": "DENY", "reason": "PATH_NOT_IN_WHITELIST"}
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'), \
         patch('mcp_http_bridge._read_server', mock_instance):
        result = _handle_tool_call("read_file", {
            "path": "/etc/passwd",
            "actor_id": "caddy",
            "purpose": "OBSERVATION",
        })
    assert result['isError']

# ── TC-B08: containment 시 READ 도구도 차단 ──────────────────────
def test_tcb08_containment_blocks_read():
    with patch('mcp_http_bridge.containment_is_active', return_value=True):
        gov_ctx = _build_governance_context({})
        body = {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": {
                "path": "/opt/arss/engine/arss-protocol/x.py",
                "actor_id": "caddy",
                "purpose": "OBSERVATION",
            }},
        }
        result = _handle_jsonrpc(body, gov_ctx)
    assert "error" in result
    assert result["error"]["code"] == -32000

# ── TC-B09: tools/list JSON-RPC 정상 ─────────────────────────────
def test_tcb09_jsonrpc_tools_list():
    gov_ctx = _build_governance_context({})
    body = {"jsonrpc": "2.0", "id": "1", "method": "tools/list", "params": {}}
    result = _handle_jsonrpc(body, gov_ctx)
    assert result["result"]["tools"]
    names = {t['name'] for t in result["result"]["tools"]}
    assert "read_file" in names

# ── TC-B10: unknown tool DENY ────────────────────────────────────
def test_tcb10_unknown_tool_deny():
    result = _handle_tool_call("shell_exec", {"cmd": "rm -rf /"})
    assert result['isError']
    assert "not permitted" in result['content'][0]['text']

# ── TC-B11: get_runtime_snapshot 위임 ────────────────────────────
def test_tcb11_runtime_snapshot_delegation():
    mock_instance = MagicMock()
    mock_instance.get_runtime_snapshot.return_value = {
        "status": "ALLOW", "snapshot": {"services": {}}
    }
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'), \
         patch('mcp_http_bridge._read_server', mock_instance):
        result = _handle_tool_call("get_runtime_snapshot", {
            "actor_id": "domi",
            "purpose": "OBSERVATION",
        })
    assert mock_instance.get_runtime_snapshot.called

# ── TC-B12: domi actor_id 허용 ───────────────────────────────────
def test_tcb12_domi_actor_allowed():
    mock_instance = MagicMock()
    mock_instance.read_file.return_value = {"status": "ALLOW", "content": "design"}
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'), \
         patch('mcp_http_bridge._read_server', mock_instance):
        result = _handle_tool_call("read_file", {
            "path": "/opt/arss/engine/arss-protocol/design.md",
            "actor_id": "domi",
            "purpose": "CONSISTENCY_CHECK",
        })
    assert mock_instance.read_file.called

# ── TC-B13: jeni actor_id 허용 ───────────────────────────────────
def test_tcb13_jeni_actor_allowed():
    mock_instance = MagicMock()
    mock_instance.read_audit_event.return_value = {"status": "ALLOW", "events": []}
    with patch('mcp_http_bridge.READ_HMAC_SECRET', 'test-secret'), \
         patch('mcp_http_bridge._read_server', mock_instance):
        result = _handle_tool_call("read_audit_event", {
            "log_path": "/opt/arss/engine/arss-protocol/tools/mcp/audit.log",
            "event_range": 10,
            "actor_id": "jeni",
            "purpose": "AUDIT_INSPECTION",
        })
    assert mock_instance.read_audit_event.called

# ── TC-B14: initialize 정상 ───────────────────────────────────────
def test_tcb14_initialize():
    gov_ctx = _build_governance_context({})
    body = {
        "jsonrpc": "2.0", "id": "1",
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }
    result = _handle_jsonrpc(body, gov_ctx)
    assert result["result"]["serverInfo"]["version"] == "2.1.0"

# ── TC-B15: notification (id=None) → None 반환 ───────────────────
def test_tcb15_notification_returns_none():
    gov_ctx = _build_governance_context({})
    body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    result = _handle_jsonrpc(body, gov_ctx)
    assert result is None

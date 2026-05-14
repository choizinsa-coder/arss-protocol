"""
test_mcp_server_poc.py
Task: PT-S125-BOOT-ONDEMAND-001
EAG: EAG-2 비오(Joshua) 승인 (S126)

검증 항목:
- TC-1: ping 응답 구조 검증
- TC-2: get_server_status 반환값 검증
- TC-3: get_current_epoch 반환값 검증
- TC-4: tools/list JSON-RPC 응답 검증
- TC-5: tools/call ping JSON-RPC 응답 검증
- TC-6: tools/call 미등록 도구 → error 반환 검증
- TC-7: Audit Trail 로깅 호출 확인
- TC-8: get_all_context 류 도구 미존재 확인 (금지 규칙 준수)
"""

import json
import sys
import io
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# 경로 조정
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/mcp")

import mcp_server_poc as poc


# ---------------------------------------------------------------------------
# TC-1: ping
# ---------------------------------------------------------------------------

def test_tc1_ping_structure():
    result = poc.ping()
    assert result["status"] == "ok"
    assert "message" in result
    assert result["server"] == poc.SERVER_NAME
    assert result["version"] == poc.SERVER_VERSION
    assert "timestamp" in result


# ---------------------------------------------------------------------------
# TC-2: get_server_status
# ---------------------------------------------------------------------------

def test_tc2_get_server_status():
    result = poc.get_server_status()
    assert result["server_name"] == poc.SERVER_NAME
    assert result["aiba_system"] == poc.AIBA_SYSTEM
    assert result["aiba_version"] == poc.AIBA_VERSION
    assert result["status"] == "operational"
    assert result["mcp_poc_task"] == "PT-S125-BOOT-ONDEMAND-001"
    assert "timestamp" in result


# ---------------------------------------------------------------------------
# TC-3: get_current_epoch
# ---------------------------------------------------------------------------

def test_tc3_get_current_epoch():
    before = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = poc.get_current_epoch()
    after = int(datetime.now(timezone.utc).timestamp() * 1000)

    assert "epoch_ms" in result
    assert "epoch_s" in result
    assert "utc_iso" in result
    assert before <= result["epoch_ms"] <= after
    assert result["source"] == "vps_system_clock"


# ---------------------------------------------------------------------------
# TC-4: tools/list JSON-RPC
# ---------------------------------------------------------------------------

def test_tc4_tools_list():
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    outputs = []

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        poc._handle(request)
        output = mock_stdout.getvalue().strip()

    response = json.loads(output)
    assert response["id"] == 1
    tool_names = [t["name"] for t in response["result"]["tools"]]
    assert "ping" in tool_names
    assert "get_server_status" in tool_names
    assert "get_current_epoch" in tool_names


# ---------------------------------------------------------------------------
# TC-5: tools/call ping JSON-RPC
# ---------------------------------------------------------------------------

def test_tc5_tools_call_ping():
    request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "ping", "arguments": {}},
    }

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        poc._handle(request)
        output = mock_stdout.getvalue().strip()

    response = json.loads(output)
    assert response["id"] == 2
    assert response["result"]["isError"] is False
    content_text = response["result"]["content"][0]["text"]
    content = json.loads(content_text)
    assert content["status"] == "ok"


# ---------------------------------------------------------------------------
# TC-6: 미등록 도구 → error 반환
# ---------------------------------------------------------------------------

def test_tc6_unknown_tool_error():
    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "get_all_context", "arguments": {}},
    }

    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        poc._handle(request)
        output = mock_stdout.getvalue().strip()

    response = json.loads(output)
    assert "error" in response
    assert response["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# TC-7: Audit Trail 로깅 호출 확인
# ---------------------------------------------------------------------------

def test_tc7_audit_trail_logging():
    with patch.object(poc.logger, "info") as mock_log:
        poc.ping()
        mock_log.assert_called_once()
        call_args = mock_log.call_args[0]
        assert "TOOL_CALL" in call_args[0]
        assert "ping" in str(call_args)


# ---------------------------------------------------------------------------
# TC-8: get_all_context 류 금지 도구 미존재 확인
# ---------------------------------------------------------------------------

def test_tc8_forbidden_tools_absent():
    forbidden = ["get_all_context", "load_full_session", "preload_all", "get_full_boot"]
    for name in forbidden:
        assert name not in poc.TOOLS, f"금지 도구 {name}이 TOOLS에 등록되어 있음"

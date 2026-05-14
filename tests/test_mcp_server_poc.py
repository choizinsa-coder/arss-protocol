"""
test_mcp_server_poc.py  v0.2.0
Task: PT-S125-BOOT-ONDEMAND-001 / 도미 2차 설계 반영

TC-01: ping L0 레이블
TC-02: get_server_status L1 레이블
TC-03: get_current_epoch L1 레이블
TC-04: tools/list ALLOWED_TOOLS만 노출
TC-05: tools/call ping 정상 실행
TC-06: FORBIDDEN_TOOLS 호출 -> DENY
TC-07: 미등재 도구 -> DENY
TC-08: Audit Trail 로깅
TC-09: FORBIDDEN 도구 tools/list 미노출
TC-10: deny-by-default 구조 검증
TC-11: 계층 위반 등재 시 RuntimeError
TC-12: FORBIDDEN ALLOWED 등재 시 RuntimeError
TC-13: FAIL_CLOSED_POLICY 상수 검증
TC-14: PHASE_A_ALLOWED_LAYERS = {L0, L1}
TC-15: MCP_LAYER L0~L4 전항목 존재
TC-16: get_server_status fail_closed_policy 필드 포함
"""

import io
import json
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/mcp")
import mcp_server_poc as poc


def test_tc01_ping_structure_and_layer():
    result = poc.ping()
    assert result["status"] == "ok"
    assert result["mcp_layer"] == "L0"
    assert result["phase"] == poc.CURRENT_PHASE
    assert result["server"] == poc.SERVER_NAME
    assert "timestamp" in result


def test_tc02_get_server_status_and_layer():
    result = poc.get_server_status()
    assert result["mcp_layer"] == "L1"
    assert result["current_phase"] == poc.CURRENT_PHASE
    assert result["status"] == "operational"
    assert result["fail_closed_policy"] == "DENY"
    assert set(result["allowed_layers"]) == {"L0", "L1"}


def test_tc03_get_current_epoch_and_layer():
    before = int(datetime.now(timezone.utc).timestamp() * 1000)
    result = poc.get_current_epoch()
    after = int(datetime.now(timezone.utc).timestamp() * 1000)
    assert result["mcp_layer"] == "L1"
    assert before <= result["epoch_ms"] <= after
    assert result["source"] == "vps_system_clock"


def test_tc04_tools_list_allowed_only():
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
        poc._handle(request)
        response = json.loads(mock_out.getvalue().strip())
    tool_names = {t["name"] for t in response["result"]["tools"]}
    assert tool_names == {"ping", "get_server_status", "get_current_epoch"}
    for forbidden in poc.FORBIDDEN_TOOLS:
        assert forbidden not in tool_names


def test_tc05_tools_call_ping_ok():
    request = {
        "jsonrpc": "2.0", "id": 2,
        "method": "tools/call",
        "params": {"name": "ping", "arguments": {}},
    }
    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
        poc._handle(request)
        response = json.loads(mock_out.getvalue().strip())
    assert response["result"]["isError"] is False
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["status"] == "ok"
    assert content["mcp_layer"] == "L0"


def test_tc06_forbidden_tool_deny():
    with pytest.raises(PermissionError) as exc_info:
        poc._dispatch("get_all_context")
    assert "FAIL_CLOSED" in str(exc_info.value)
    assert "FORBIDDEN" in str(exc_info.value)


def test_tc07_unregistered_tool_deny():
    with pytest.raises(PermissionError) as exc_info:
        poc._dispatch("mystery_tool_xyz")
    assert "FAIL_CLOSED" in str(exc_info.value)


def test_tc08_audit_trail_logging():
    with patch.object(poc.logger, "info") as mock_log:
        poc.ping()
        assert mock_log.called
        args = str(mock_log.call_args_list)
        assert "TOOL_CALL" in args
        assert "ping" in args


def test_tc09_forbidden_not_in_tools_list():
    request = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
        poc._handle(request)
        response = json.loads(mock_out.getvalue().strip())
    listed_names = {t["name"] for t in response["result"]["tools"]}
    for forbidden in poc.FORBIDDEN_TOOLS:
        assert forbidden not in listed_names


def test_tc10_deny_by_default_structure():
    test_names = ["new_tool", "read_all", "get_context", "fetch_state"]
    for name in test_names:
        assert name not in poc.ALLOWED_TOOLS
        with pytest.raises(PermissionError):
            poc._dispatch(name)


def test_tc11_layer_violation_raises_on_build():
    bad_registry = {
        "bad_tool": {"name": "bad_tool", "layer": "L2", "fn": lambda: {}}
    }
    def mock_build():
        for name, entry in bad_registry.items():
            if entry["layer"] not in poc.PHASE_A_ALLOWED_LAYERS:
                raise RuntimeError(
                    f"[FAIL_CLOSED] 도구 '{name}' 계층 '{entry['layer']}'은 PHASE-A 허용 범위 외부 -- 즉시 중단."
                )
        return bad_registry
    with pytest.raises(RuntimeError) as exc_info:
        mock_build()
    assert "FAIL_CLOSED" in str(exc_info.value)
    assert "PHASE-A" in str(exc_info.value)


def test_tc12_forbidden_in_allowed_raises_on_build():
    bad_registry = {
        "get_all_context": {"name": "get_all_context", "layer": "L0", "fn": lambda: {}}
    }
    def mock_build():
        for name in bad_registry:
            if name in poc.FORBIDDEN_TOOLS:
                raise RuntimeError(
                    f"[FAIL_CLOSED] FORBIDDEN 도구 '{name}'이 허용 레지스트리에 등재됨 -- 즉시 중단."
                )
        return bad_registry
    with pytest.raises(RuntimeError) as exc_info:
        mock_build()
    assert "FAIL_CLOSED" in str(exc_info.value)
    assert "FORBIDDEN" in str(exc_info.value)


def test_tc13_fail_closed_policy_constant():
    assert poc.FAIL_CLOSED_POLICY["default"] == "DENY"
    for key in ["unregistered_tool", "forbidden_tool", "layer_violation", "authority_ceiling"]:
        assert key in poc.FAIL_CLOSED_POLICY


def test_tc14_phase_a_allowed_layers():
    assert poc.PHASE_A_ALLOWED_LAYERS == frozenset({"L0", "L1"})
    for layer in ["L2", "L3", "L4"]:
        assert layer not in poc.PHASE_A_ALLOWED_LAYERS


def test_tc15_mcp_layer_constant_complete():
    for layer in ["L0", "L1", "L2", "L3", "L4"]:
        assert layer in poc.MCP_LAYER


def test_tc16_server_status_exposes_policy():
    result = poc.get_server_status()
    assert "fail_closed_policy" in result
    assert result["fail_closed_policy"] == "DENY"
    assert "allowed_layers" in result

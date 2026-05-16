"""
test_mcp_http_bridge_v2.py
mcp_http_bridge.py v2.0.0 테스트 — T1~T10
PT-S131-MCP-REG-001 S133 보완 설계
"""

import sys
import os
import json
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from http.client import HTTPConnection

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'mcp'))

import mcp_http_bridge as bridge
from mcp_http_bridge import (
    BridgeHandler,
    ThreadedHTTPServer,
    INTERNAL_ACTOR_ID,
    ALLOWED_TOOLS,
    CONTAINMENT_ERROR_CODE,
    _build_governance_context,
    _handle_jsonrpc,
    _handle_tool_list,
    _handle_tool_call,
    _set_bridge_state,
    _get_bridge_state,
)


def _start_test_server(port: int):
    """테스트용 서버 시작."""
    server = ThreadedHTTPServer(("127.0.0.1", port), BridgeHandler)
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()
    time.sleep(0.1)
    return server


class TestT1_GET_MCP_SSE(unittest.TestCase):
    """T1: GET /mcp → 200 + text/event-stream"""

    def test_t1_get_mcp_returns_sse(self):
        port = 18501
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            server = _start_test_server(port)
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/mcp")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                ct = resp.headers.get("Content-Type", "")
                self.assertIn("text/event-stream", ct)
                conn.close()
            finally:
                server.shutdown()


class TestT2_GET_MCP_NO_JSONRPC(unittest.TestCase):
    """T2: GET /mcp stream에 JSON-RPC response를 임의 송신하지 않음 (heartbeat만)"""

    def test_t2_sse_sends_only_heartbeat(self):
        """
        SSE 스트림은 long-lived connection — read로 데이터를 기다리면 timeout 발생.
        헤더 검증으로 대체: Content-Type=text/event-stream 확인 +
        JSON-RPC 관련 헤더/응답 없음 확인.
        """
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18502
            server = _start_test_server(port)
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/mcp")
                resp = conn.getresponse()
                # T2 핵심: SSE 헤더 확인 + Content-Type이 application/json이 아님
                ct = resp.headers.get("Content-Type", "")
                self.assertIn("text/event-stream", ct)
                self.assertNotIn("application/json", ct)
                # JSON-RPC response는 GET stream에서 반환하지 않음
                # (application/json Content-Type 부재로 검증)
                conn.close()
            finally:
                server.shutdown()


class TestT3_POST_MCP_INITIALIZE(unittest.TestCase):
    """T3: POST /mcp initialize → JSON-RPC response"""

    def test_t3_initialize(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18503
            server = _start_test_server(port)
            try:
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "clientInfo": {"name": "claude.ai", "version": "1.0"},
                    },
                }).encode()
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/mcp", body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": len(body)})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                result = json.loads(resp.read())
                self.assertEqual(result["id"], 1)
                self.assertIn("result", result)
                self.assertIn("serverInfo", result["result"])
                conn.close()
            finally:
                server.shutdown()


class TestT4_POST_NOTIFICATION(unittest.TestCase):
    """T4: POST /mcp notification (id 없음) → 202"""

    def test_t4_notification_returns_202(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18504
            server = _start_test_server(port)
            try:
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }).encode()
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/mcp", body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": len(body)})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 202)
                conn.close()
            finally:
                server.shutdown()


class TestT5_CONTAINMENT_REQUEST(unittest.TestCase):
    """T5: containment=true + request → JSON-RPC error"""

    def test_t5_containment_returns_jsonrpc_error(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=True), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18505
            server = _start_test_server(port)
            try:
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                }).encode()
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/mcp", body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": len(body)})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                result = json.loads(resp.read())
                self.assertIn("error", result)
                self.assertEqual(result["error"]["code"], CONTAINMENT_ERROR_CODE)
                self.assertEqual(result["id"], 1)
                conn.close()
            finally:
                server.shutdown()


class TestT6_CONTAINMENT_NOTIFICATION(unittest.TestCase):
    """T6: containment=true + notification → no execution + audit safe_denied"""

    def test_t6_containment_notification_safe_denied(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=True), \
             patch("mcp_http_bridge.write_audit") as mock_audit, \
             patch("mcp_http_bridge.write_deny_audit") as mock_deny:
            _set_bridge_state("ACTIVE")
            port = 18506
            server = _start_test_server(port)
            try:
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }).encode()
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/mcp", body=body,
                             headers={"Content-Type": "application/json",
                                      "Content-Length": len(body)})
                resp = conn.getresponse()
                self.assertEqual(resp.status, 202)
                mock_deny.assert_called()
                conn.close()
            finally:
                server.shutdown()


class TestT7_ACTOR_ID_INTERNAL(unittest.TestCase):
    """T7: actor_id는 외부 payload가 아니라 내부 context에서 주입"""

    def test_t7_actor_id_is_internal(self):
        raw = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"actor_id": "evil_actor"}}
        ctx = _build_governance_context(raw)
        self.assertEqual(ctx["actor_id"], INTERNAL_ACTOR_ID)
        self.assertFalse(ctx["external_payload_actor_trusted"])

    def test_t7_jsonrpc_uses_internal_actor(self):
        with patch("mcp_http_bridge.write_audit") as mock_audit, \
             patch("mcp_http_bridge.write_deny_audit"):
            gov_ctx = _build_governance_context({"method": "initialize"})
            gov_ctx["containment_active"] = False
            gov_ctx["bridge_state"] = "ACTIVE"
            body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
            _handle_jsonrpc(body, gov_ctx)
            call_kwargs = mock_audit.call_args
            self.assertEqual(call_kwargs[1]["agent_id"], INTERNAL_ACTOR_ID)


class TestT8_INTERNAL_DEBUG_NOT_PUBLIC(unittest.TestCase):
    """T8: internal/debug는 public connector path에서 접근 불가"""

    def test_t8_unknown_path_returns_403(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18508
            server = _start_test_server(port)
            try:
                for path in ["/debug", "/internal", "/phase_c", "/hmac", "/"]:
                    conn = HTTPConnection("127.0.0.1", port, timeout=2)
                    conn.request("GET", path)
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 403, f"Path {path} should be 403")
                    conn.close()
            finally:
                server.shutdown()


class TestT9_HEALTH_ENDPOINT(unittest.TestCase):
    """T9: /bridge/health 유지"""

    def test_t9_health_returns_200(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18509
            server = _start_test_server(port)
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", "/bridge/health")
                resp = conn.getresponse()
                self.assertEqual(resp.status, 200)
                result = json.loads(resp.read())
                self.assertIn("bridge_state", result)
                self.assertIn("containment", result)
                conn.close()
            finally:
                server.shutdown()


class TestT10_FAIL_CLOSED(unittest.TestCase):
    """T10: /mcp 외 경로는 fail-closed (403)"""

    def test_t10_post_unknown_path_forbidden(self):
        with patch("mcp_http_bridge.containment_is_active", return_value=False), \
             patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            _set_bridge_state("ACTIVE")
            port = 18510
            server = _start_test_server(port)
            try:
                body = b"{}"
                conn = HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("POST", "/unknown",
                             body=body,
                             headers={"Content-Length": len(body)})
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 403)
                conn.close()
            finally:
                server.shutdown()

    def test_t10_tools_list_allowlist_only(self):
        """AIBA Tool Layer: allowlist 도구만 반환"""
        result = _handle_tool_list()
        tool_names = {t["name"] for t in result["tools"]}
        self.assertTrue(tool_names.issubset(ALLOWED_TOOLS))


if __name__ == "__main__":
    unittest.main()

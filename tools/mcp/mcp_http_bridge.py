"""
mcp_http_bridge.py v2.0.0
MCP Streamable HTTP Bridge — PT-S131-MCP-REG-001
설계: 도미 BRIEFING-DOMI-S131-002 Rev.1 + S133 GAP-A~D 보완
EAG-1: 비오(Joshua) 승인 (S133)
제니 TRUST_READY: PASS (S133)

계층 구조:
  Transport Layer     — GET /mcp (SSE), POST /mcp (JSON-RPC)
  Governance Adapter  — actor_id 내부 주입, containment 판단, audit
  AIBA Tool Layer     — allowlist 도구만 노출, full context retrieval 금지

공개 경로:
  /mcp            canonical MCP endpoint (GET SSE + POST JSON-RPC)
  /bridge/health  health check only

내부 전용:
  기존 Phase-C HMAC/nonce/shard 직접 경로 — external 노출 금지

변경 이력:
  v1.0.1 (S131): 최초 배포 — HTTP forwarding bridge
  v2.0.0 (S133): MCP Streamable HTTP endpoint 재정의
                 Transport/Governance/AIBA Tool 3계층 신설
                 GET /mcp SSE 지원, POST /mcp JSON-RPC 수신
                 actor_id 내부 고정 주입
                 containment JSON-RPC safe denial
                 ThreadingMixIn 적용 (SSE 블로킹 방지)
"""

from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional

PHASE_C_DIR = "/opt/arss/engine/arss-protocol/tools/mcp"
if PHASE_C_DIR not in sys.path:
    sys.path.insert(0, PHASE_C_DIR)

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_containment_state import is_active as containment_is_active

# ── 상수 ──────────────────────────────────────────────────────────────────────

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8443
BRIDGE_VERSION = "2.0.0"

# Governance Adapter: 내부 고정 actor (GAP-B)
INTERNAL_ACTOR_ID = "claude_ai_remote_connector"
INTERNAL_ACTOR_SOURCE = "claude.ai"
INTERNAL_CONNECTOR_NAME = "ARSS Protocol"
EXTERNAL_PAYLOAD_ACTOR_TRUSTED = False

# allowlist 도구 (AIBA Tool Layer)
ALLOWED_TOOLS = frozenset({
    "ping",
    "get_load_state",
})

# JSON-RPC containment error (GAP-D)
CONTAINMENT_ERROR_CODE = -32000
CONTAINMENT_ERROR_MESSAGE = "AIBA containment active"
CONTAINMENT_ERROR_REASON = "CONTAINMENT_ACTIVE"

# SSE heartbeat 간격 (초)
SSE_HEARTBEAT_INTERVAL = 15

# ── Bridge 상태 ────────────────────────────────────────────────────────────────

_bridge_state = "INACTIVE"
_bridge_state_lock = threading.Lock()
_sse_clients: list = []
_sse_clients_lock = threading.Lock()


def _get_bridge_state() -> str:
    with _bridge_state_lock:
        return _bridge_state


def _set_bridge_state(state: str) -> None:
    with _bridge_state_lock:
        global _bridge_state
        _bridge_state = state


# ── Governance Adapter ────────────────────────────────────────────────────────

def _build_governance_context(raw_request: dict) -> dict:
    """GAP-B: actor_id 내부 고정 주입. 외부 payload 원형 보존."""
    return {
        "actor_id": INTERNAL_ACTOR_ID,
        "source": INTERNAL_ACTOR_SOURCE,
        "connector_name": INTERNAL_CONNECTOR_NAME,
        "external_payload_actor_trusted": EXTERNAL_PAYLOAD_ACTOR_TRUSTED,
        "raw_request": raw_request,
        "bridge_state": _get_bridge_state(),
        "containment_active": containment_is_active(),
    }


def _containment_jsonrpc_error(request_id) -> dict:
    """GAP-D: containment=true POST request → JSON-RPC error."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": CONTAINMENT_ERROR_CODE,
            "message": CONTAINMENT_ERROR_MESSAGE,
            "data": {"reason": CONTAINMENT_ERROR_REASON},
        },
    }


def _audit_allow(gov_ctx: dict, returned_scope: str, reason: str) -> None:
    write_audit(
        agent_id=gov_ctx["actor_id"],
        requested_shard="mcp_endpoint",
        returned_scope=returned_scope,
        decision="ALLOW",
        reason=reason,
        load_state=gov_ctx["bridge_state"],
        retrieval_class="CLASS-B",
    )


def _audit_deny(gov_ctx: dict, reason: str) -> None:
    write_deny_audit(
        agent_id=gov_ctx["actor_id"],
        requested_shard="mcp_endpoint",
        returned_scope="NONE",
        decision="DENY",
        reason=reason,
        load_state=gov_ctx["bridge_state"],
        retrieval_class="CLASS-D",
    )


# ── AIBA Tool Layer ───────────────────────────────────────────────────────────

def _handle_tool_list() -> dict:
    """allowlist 도구만 반환. full context retrieval 금지."""
    tools = []
    if "ping" in ALLOWED_TOOLS:
        tools.append({
            "name": "ping",
            "description": "AIBA bridge connectivity check",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        })
    if "get_load_state" in ALLOWED_TOOLS:
        tools.append({
            "name": "get_load_state",
            "description": "Returns bridge load state (visibility only)",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        })
    return {"tools": tools}


def _handle_tool_call(tool_name: str, arguments: dict) -> dict:
    """허용된 도구만 실행."""
    if tool_name not in ALLOWED_TOOLS:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not permitted"}],
        }
    if tool_name == "ping":
        return {
            "content": [{"type": "text", "text": "pong"}],
        }
    if tool_name == "get_load_state":
        return {
            "content": [{"type": "text", "text": json.dumps({
                "bridge_state": _get_bridge_state(),
                "containment": containment_is_active(),
                "version": BRIDGE_VERSION,
            })}],
        }
    return {
        "isError": True,
        "content": [{"type": "text", "text": "Unknown tool"}],
    }


def _handle_jsonrpc(body: dict, gov_ctx: dict) -> Optional[dict]:
    """
    JSON-RPC 처리.
    id 없는 notification은 None 반환 (202 Accepted).
    """
    method = body.get("method", "")
    request_id = body.get("id")
    params = body.get("params", {})

    # notification (id 없음)
    if request_id is None:
        # containment 상태에서 safe_denied 기록
        if gov_ctx["containment_active"]:
            _audit_deny(gov_ctx, f"CONTAINMENT_NOTIFICATION_DENIED:{method}")
        return None

    # containment=true → JSON-RPC error (GAP-D)
    if gov_ctx["containment_active"]:
        _audit_deny(gov_ctx, f"CONTAINMENT_REQUEST_DENIED:{method}")
        return _containment_jsonrpc_error(request_id)

    # initialize
    if method == "initialize":
        _audit_allow(gov_ctx, "initialize", "MCP_INITIALIZE")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "ARSS Protocol MCP Bridge",
                    "version": BRIDGE_VERSION,
                },
            },
        }

    # tools/list
    if method == "tools/list":
        _audit_allow(gov_ctx, "tools/list", "MCP_TOOLS_LIST")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": _handle_tool_list(),
        }

    # tools/call
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in ALLOWED_TOOLS:
            _audit_deny(gov_ctx, f"TOOL_NOT_PERMITTED:{tool_name}")
        else:
            _audit_allow(gov_ctx, f"tool:{tool_name}", "MCP_TOOL_CALL")
        result = _handle_tool_call(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }

    # 미지원 method
    _audit_deny(gov_ctx, f"UNKNOWN_METHOD:{method}")
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "Method not found"},
    }


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _fail_closed(self, reason: str) -> None:
        gov_ctx = {
            "actor_id": INTERNAL_ACTOR_ID,
            "bridge_state": _get_bridge_state(),
            "containment_active": True,
        }
        _audit_deny(gov_ctx, reason)
        self._send_json(503, {"error": "bridge_unavailable"})

    # ── GET ──────────────────────────────────────────────────────────────────

    def do_GET(self):
        # /bridge/health
        if self.path == "/bridge/health":
            self._send_json(200, {
                "bridge_state": _get_bridge_state(),
                "containment": containment_is_active(),
                "version": BRIDGE_VERSION,
            })
            return

        # /mcp → SSE stream (GAP-C, T1)
        if self.path == "/mcp":
            bridge_state = _get_bridge_state()
            if bridge_state in ("INACTIVE", "ROLLED_BACK"):
                self._fail_closed(f"BRIDGE_STATE:{bridge_state}")
                return

            gov_ctx = _build_governance_context({})
            _audit_allow(gov_ctx, "sse_stream", "SSE_STREAM_OPEN")

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            # SSE 연결 등록
            with _sse_clients_lock:
                _sse_clients.append(self)

            try:
                # 초기 heartbeat
                self._sse_send_heartbeat()
                while True:
                    time.sleep(SSE_HEARTBEAT_INTERVAL)
                    self._sse_send_heartbeat()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with _sse_clients_lock:
                    if self in _sse_clients:
                        _sse_clients.remove(self)
                _audit_allow(gov_ctx, "sse_stream", "SSE_STREAM_CLOSE")
            return

        # 그 외 모든 GET — fail-closed (T10)
        self._send_json(403, {"error": "forbidden"})

    def _sse_send_heartbeat(self) -> None:
        """SSE heartbeat — 빈 data로 stream 유지."""
        event_id = str(uuid.uuid4())
        msg = f"id: {event_id}\ndata: \n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()

    # ── POST ─────────────────────────────────────────────────────────────────

    def do_POST(self):
        # /mcp → JSON-RPC endpoint
        if self.path == "/mcp":
            bridge_state = _get_bridge_state()
            if bridge_state in ("INACTIVE", "ROLLED_BACK"):
                self._fail_closed(f"BRIDGE_STATE:{bridge_state}")
                return

            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"

            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
                return

            gov_ctx = _build_governance_context(body)
            result = _handle_jsonrpc(body, gov_ctx)

            # notification (id 없음) → 202 Accepted (T4, T6)
            if result is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            self._send_json(200, result)
            return

        # 그 외 모든 POST — fail-closed (T10)
        self._send_json(403, {"error": "forbidden"})


# ── Threading Server ───────────────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """SSE 블로킹 방지 — 제니 주의 권고 반영."""
    daemon_threads = True


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    import signal

    def _handle_shutdown(signum, frame):
        _set_bridge_state("ROLLED_BACK")
        sys.exit(0)

    _set_bridge_state("ACTIVE")
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    gov_ctx = {
        "actor_id": "SYSTEM",
        "bridge_state": "ACTIVE",
        "containment_active": False,
    }
    _audit_allow(gov_ctx, "NONE", "BRIDGE_STARTUP")

    server = ThreadedHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

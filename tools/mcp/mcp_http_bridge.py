"""
mcp_http_bridge.py v2.2.0
MCP Streamable HTTP Bridge — PT-S131-MCP-REG-001 + PT-S134-VPS-OBS-001 + PT-S139-MCP-WRITE-BRIDGE-001

변경 이력:
  v2.0.0 (S133): MCP Streamable HTTP endpoint 재정의
  v2.1.0 (S134): PT-S134-VPS-OBS-001 Phase 1 READ ONLY OBSERVABILITY 통합
                 ReadOnlyServer 9종 도구 추가
                 Bridge 내부 HMAC 생성 → ReadOnlyServer 3요소 인증 유지
                 actor_id arguments 경유 수신 (domi/jeni/caddy 차등 권한)
  v2.2.0 (S139): PT-S139-MCP-WRITE-BRIDGE-001 Write Plane 브릿지 연결
                 write_file / get_write_plane_state 추가
                 Bridge = FORWARD_ONLY (approval 검증은 Write Server 단독 책임)
                 actor 제한: caddy only
                 payload size 상한: 65536 bytes
                 timeout: 30초 NO_RETRY FAIL_CLOSED
"""

from __future__ import annotations
import logging as _logging

import hashlib
import hmac as hmac_lib
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional

PHASE_C_DIR = "/opt/arss/engine/arss-protocol/tools/mcp"
if PHASE_C_DIR not in sys.path:
    sys.path.insert(0, PHASE_C_DIR)

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_containment_state import is_active as containment_is_active
from mcp_read_server import ReadOnlyServer, AGENT_ROOT_ALLOWLIST

# ── 상수 ──────────────────────────────────────────────────────────────────────

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8443
BRIDGE_VERSION = "2.2.0"

INTERNAL_ACTOR_ID = "claude_ai_remote_connector"
INTERNAL_ACTOR_SOURCE = "claude.ai"
INTERNAL_CONNECTOR_NAME = "ARSS Protocol"
EXTERNAL_PAYLOAD_ACTOR_TRUSTED = False

# Bridge 내부 HMAC secret (환경변수 필수)
READ_HMAC_SECRET = os.environ.get("AIBA_READ_HMAC_SECRET", "")
INTERNAL_CONNECTOR_IDENTITY = "claude.ai-arss-protocol"

# 허용 actor_id (READ 도구용)
READ_ALLOWED_ACTORS = frozenset(AGENT_ROOT_ALLOWLIST.keys())  # domi, jeni, caddy

# Write Plane 상수 (PT-S139-MCP-WRITE-BRIDGE-001)
WRITE_ALLOWED_ACTOR = "caddy"
WRITE_SERVER_URL = "http://127.0.0.1:8444/mcp/write"
WRITE_SERVER_TIMEOUT = 30       # seconds, NO_RETRY
WRITE_MAX_PAYLOAD_BYTES = 65536 # Write Server MAX_REQUEST_BODY_BYTES와 동일

WRITE_TOOLS = frozenset({"write_file", "get_write_plane_state"})

# ALLOWED_TOOLS — 기존 2종 + READ 9종 + WRITE 2종
ALLOWED_TOOLS = frozenset({
    "ping",
    "get_load_state",
    # Phase 1 READ ONLY OBSERVABILITY
    "read_file",
    "list_dir",
    "grep_scoped",
    "read_log",
    "check_service_state",
    "read_pytest_result",
    "read_audit_event",
    "read_metadata",
    "get_runtime_snapshot",
    # Write Plane (v2.2.0)
    "write_file",
    "get_write_plane_state",
})

READ_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "grep_scoped",
    "read_log",
    "check_service_state",
    "read_pytest_result",
    "read_audit_event",
    "read_metadata",
    "get_runtime_snapshot",
})

CONTAINMENT_ERROR_CODE = -32000
CONTAINMENT_ERROR_MESSAGE = "AIBA containment active"
CONTAINMENT_ERROR_REASON = "CONTAINMENT_ACTIVE"
SSE_HEARTBEAT_INTERVAL = 15

# ReadOnlyServer 인스턴스 (싱글턴)
_read_server = ReadOnlyServer()

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


# ── READ 도구 내부 HMAC 생성 ──────────────────────────────────────────────────

def _make_internal_hmac(actor_id: str, nonce: str, ts: float, payload: str) -> str:
    """Bridge 내부 HMAC 생성 — ReadOnlyServer 3요소 인증용."""
    msg = f"{actor_id}:{INTERNAL_CONNECTOR_IDENTITY}:{nonce}:{ts}:{payload}"
    return hmac_lib.new(
        READ_HMAC_SECRET.encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()


def _build_read_kwargs(actor_id: str, payload: str) -> dict:
    """ReadOnlyServer 호출용 공통 kwargs 생성."""
    ts = time.time()
    nonce = str(uuid.uuid4())
    return dict(
        actor_id=actor_id,
        connector_identity=INTERNAL_CONNECTOR_IDENTITY,
        hmac_value=_make_internal_hmac(actor_id, nonce, ts, payload),
        nonce=nonce,
        timestamp=ts,
        hmac_secret=READ_HMAC_SECRET,
    )


# ── Write 도구 중계 핸들러 (v2.2.0) ──────────────────────────────────────────

# write_file 허용 필드 화이트리스트
_WRITE_FILE_ALLOWED_FIELDS = frozenset({"approval_id", "target_path", "content"})

def _handle_write_tool(tool_name: str, arguments: dict) -> dict:
    """
    Write 도구 실행 — Write Server FORWARD_ONLY.
    브릿지 책임: actor 확인 + 형식 제한 + 전달 + audit
    approval 검증: Write Server 단독 책임
    """

    # actor 검증 (caddy only)
    actor_id = arguments.get("actor_id", "")
    if actor_id != WRITE_ALLOWED_ACTOR:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"DENY: write tool actor must be '{WRITE_ALLOWED_ACTOR}', got '{actor_id}'"}],
        }

    if tool_name == "write_file":
        # 필수 필드 존재 확인
        approval_id = arguments.get("approval_id")
        target_path = arguments.get("target_path")
        content = arguments.get("content", "")

        if not approval_id:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "DENY: approval_id required"}],
            }
        if not target_path:
            return {
                "isError": True,
                "content": [{"type": "text", "text": "DENY: target_path required"}],
            }

        # unknown_field → DENY
        unknown = set(arguments.keys()) - _WRITE_FILE_ALLOWED_FIELDS - {"actor_id"}
        if unknown:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"DENY: unknown fields: {sorted(unknown)}"}],
            }

        forward_params = {
            "approval_id": approval_id,
            "target_path": target_path,
            "content": content,
        }

    elif tool_name == "get_write_plane_state":
        forward_params = {}

    else:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"DENY: unknown write tool: {tool_name}"}],
        }

    # payload size 검증
    forward_body = json.dumps({"tool": tool_name, "params": forward_params}).encode("utf-8")
    if len(forward_body) > WRITE_MAX_PAYLOAD_BYTES:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"DENY: payload size {len(forward_body)} exceeds limit {WRITE_MAX_PAYLOAD_BYTES}"}],
        }

    # Write Server HTTP 포워딩 (NO_RETRY, FAIL_CLOSED)
    try:
        req = urllib.request.Request(
            WRITE_SERVER_URL,
            data=forward_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(forward_body))},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=WRITE_SERVER_TIMEOUT) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            is_error = not result.get("ok", False)
            return {
                "isError": is_error,
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
            }

    except urllib.error.URLError as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"FAIL_CLOSED: write server unreachable — {e}"}],
        }
    except TimeoutError:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"FAIL_CLOSED: write server timeout ({WRITE_SERVER_TIMEOUT}s)"}],
        }
    except Exception as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"FAIL_CLOSED: unexpected error — {e}"}],
        }


# ── AIBA Tool Layer ───────────────────────────────────────────────────────────

def _build_base_tool_entries() -> list:
    """ping/get_load_state 기본 도구 목록 반환."""
    return [
        {
            "name": "ping",
            "description": "AIBA bridge connectivity check",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_load_state",
            "description": "Returns bridge load state (visibility only)",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    ]


def _build_read_tool_entries_fs() -> list:
    """파일시스템/서비스 계열 READ 도구 (read_file~check_service_state) 반환."""
    return [
        {
            "name": "read_file",
            "description": "[READ] 단일 파일 읽기 (whitelist 경로 전용)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["path", "actor_id", "purpose"],
            },
        },
        {
            "name": "list_dir",
            "description": "[READ] 디렉토리 목록 (depth=1, recursive 금지)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["path", "actor_id", "purpose"],
            },
        },
        {
            "name": "grep_scoped",
            "description": "[READ] 허용 경로 내 텍스트 검색 (depth=2)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "pattern": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["path", "pattern", "actor_id", "purpose"],
            },
        },
        {
            "name": "read_log",
            "description": "[READ] 로그 파일 tail 읽기 (최대 200줄)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "tail_lines": {"type": "integer"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["path", "tail_lines", "actor_id", "purpose"],
            },
        },
        {
            "name": "check_service_state",
            "description": "[READ] 허용 서비스 상태 확인 (상태 조회만, 제어 금지)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "service_name": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["service_name", "actor_id", "purpose"],
            },
        },
    ]


def _build_read_tool_entries_meta() -> list:
    """메타데이터/감사 계열 READ 도구 (read_pytest_result~get_runtime_snapshot) 반환."""
    return [
        {
            "name": "read_pytest_result",
            "description": "[READ] pytest result artifact 읽기 (실행 아님)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "artifact_path": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["artifact_path", "actor_id", "purpose"],
            },
        },
        {
            "name": "read_audit_event",
            "description": "[READ] audit event 읽기 (최대 100건, bulk dump 금지)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log_path": {"type": "string"},
                    "event_range": {"type": "integer"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["log_path", "event_range", "actor_id", "purpose"],
            },
        },
        {
            "name": "read_metadata",
            "description": "[READ] SESSION_CONTEXT / SESSION_BOOT / sync metadata 읽기",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["path", "actor_id", "purpose"],
            },
        },
        {
            "name": "get_runtime_snapshot",
            "description": "[READ] 사전 정의된 read-only snapshot projection",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)},
                    "purpose": {"type": "string"},
                },
                "required": ["actor_id", "purpose"],
            },
        },
    ]


def _build_write_tool_entries() -> list:
    """Write Plane 도구 목록 반환 (v2.2.0)."""
    return [
        {
            "name": "write_file",
            "description": "[WRITE] EAG approval 기반 sandbox 파일 쓰기 (caddy only)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "actor_id": {"type": "string", "enum": [WRITE_ALLOWED_ACTOR]},
                    "approval_id": {"type": "string"},
                    "target_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["actor_id", "approval_id", "target_path", "content"],
            },
        },
        {
            "name": "get_write_plane_state",
            "description": "[WRITE] Write Plane 현재 상태 조회 (caddy only)",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "actor_id": {"type": "string", "enum": [WRITE_ALLOWED_ACTOR]},
                },
                "required": ["actor_id"],
            },
        },
    ]


def _build_read_tool_entries() -> list:
    """READ ONLY OBSERVABILITY 전체 도구 목록 반환 (FS계열 + 메타계열)."""
    return _build_read_tool_entries_fs() + _build_read_tool_entries_meta()


def _handle_tool_list() -> dict:
    """BASE + READ + WRITE 도구 목록 조합 반환."""
    tools = _build_base_tool_entries() + _build_read_tool_entries() + _build_write_tool_entries()
    return {"tools": tools}


def _handle_read_tool(tool_name: str, arguments: dict) -> dict:
    """READ 도구 실행 — ReadOnlyServer 위임."""
    if not READ_HMAC_SECRET:
        return {
            "isError": True,
            "content": [{"type": "text", "text": "DENY: READ_HMAC_SECRET not configured"}],
        }

    actor_id = arguments.get("actor_id", "")
    purpose = arguments.get("purpose", "")

    if actor_id not in READ_ALLOWED_ACTORS:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"DENY: unknown actor_id={actor_id}"}],
        }

    try:
        if tool_name == "read_file":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_file(path, purpose=purpose, **kwargs)

        elif tool_name == "list_dir":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.list_dir(path, purpose=purpose, **kwargs)

        elif tool_name == "grep_scoped":
            path = arguments.get("path", "")
            pattern = arguments.get("pattern", "")
            max_results = arguments.get("max_results", 50)
            kwargs = _build_read_kwargs(actor_id, f"{path}:{pattern}")
            result = _read_server.grep_scoped(
                path, pattern, purpose=purpose,
                max_results=max_results, **kwargs
            )

        elif tool_name == "read_log":
            path = arguments.get("path", "")
            tail_lines = arguments.get("tail_lines", 50)
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_log(
                path, tail_lines=tail_lines, purpose=purpose, **kwargs
            )

        elif tool_name == "check_service_state":
            service_name = arguments.get("service_name", "")
            kwargs = _build_read_kwargs(actor_id, service_name)
            result = _read_server.check_service_state(
                service_name, purpose=purpose, **kwargs
            )

        elif tool_name == "read_pytest_result":
            artifact_path = arguments.get("artifact_path", "")
            kwargs = _build_read_kwargs(actor_id, artifact_path)
            result = _read_server.read_pytest_result(
                artifact_path, purpose=purpose, **kwargs
            )

        elif tool_name == "read_audit_event":
            log_path = arguments.get("log_path", "")
            event_range = arguments.get("event_range", 10)
            kwargs = _build_read_kwargs(actor_id, log_path)
            result = _read_server.read_audit_event(
                log_path, event_range=event_range, purpose=purpose, **kwargs
            )

        elif tool_name == "read_metadata":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_metadata(path, purpose=purpose, **kwargs)

        elif tool_name == "get_runtime_snapshot":
            kwargs = _build_read_kwargs(actor_id, "runtime_snapshot")
            result = _read_server.get_runtime_snapshot(purpose=purpose, **kwargs)

        else:
            return {
                "isError": True,
                "content": [{"type": "text", "text": f"DENY: unknown read tool={tool_name}"}],
            }

        is_error = result.get("status") == "DENY"
        return {
            "isError": is_error,
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        }

    except Exception as e:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"DENY: internal error={str(e)}"}],
        }


def _handle_tool_call(tool_name: str, arguments: dict) -> dict:
    if tool_name not in ALLOWED_TOOLS:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"Tool '{tool_name}' not permitted"}],
        }
    if tool_name == "ping":
        return {"content": [{"type": "text", "text": "pong"}]}
    if tool_name == "get_load_state":
        return {
            "content": [{"type": "text", "text": json.dumps({
                "bridge_state": _get_bridge_state(),
                "containment": containment_is_active(),
                "version": BRIDGE_VERSION,
            })}],
        }
    if tool_name in READ_TOOLS:
        return _handle_read_tool(tool_name, arguments)
    if tool_name in WRITE_TOOLS:
        return _handle_write_tool(tool_name, arguments)
    return {
        "isError": True,
        "content": [{"type": "text", "text": "Unknown tool"}],
    }


def _handle_jsonrpc(body: dict, gov_ctx: dict) -> Optional[dict]:
    method = body.get("method", "")
    request_id = body.get("id")
    params = body.get("params", {})

    if request_id is None:
        if gov_ctx["containment_active"]:
            _audit_deny(gov_ctx, f"CONTAINMENT_NOTIFICATION_DENIED:{method}")
        return None

    if gov_ctx["containment_active"]:
        _audit_deny(gov_ctx, f"CONTAINMENT_REQUEST_DENIED:{method}")
        return _containment_jsonrpc_error(request_id)

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

    if method == "tools/list":
        _audit_allow(gov_ctx, "tools/list", "MCP_TOOLS_LIST")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": _handle_tool_list(),
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in ALLOWED_TOOLS:
            _audit_deny(gov_ctx, f"TOOL_NOT_PERMITTED:{tool_name}")
        else:
            _audit_allow(gov_ctx, f"tool:{tool_name}", "MCP_TOOL_CALL")
        result = _handle_tool_call(tool_name, arguments)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

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

    def do_GET(self):
        if self.path == "/bridge/health":
            self._send_json(200, {
                "bridge_state": _get_bridge_state(),
                "containment": containment_is_active(),
                "version": BRIDGE_VERSION,
            })
            return

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

            with _sse_clients_lock:
                _sse_clients.append(self)

            try:
                self._sse_send_heartbeat()
                while True:
                    time.sleep(SSE_HEARTBEAT_INTERVAL)
                    self._sse_send_heartbeat()
            except (BrokenPipeError, ConnectionResetError) as _rule6_e:
                _logging.debug("RULE6 mcp_http_bridge: %s", _rule6_e)
            finally:
                with _sse_clients_lock:
                    if self in _sse_clients:
                        _sse_clients.remove(self)
                _audit_allow(gov_ctx, "sse_stream", "SSE_STREAM_CLOSE")
            return

        self._send_json(403, {"error": "forbidden"})

    def _sse_send_heartbeat(self) -> None:
        event_id = str(uuid.uuid4())
        msg = f"id: {event_id}\ndata: \n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()

    def do_POST(self):
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

            if result is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            self._send_json(200, result)
            return

        self._send_json(403, {"error": "forbidden"})


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


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

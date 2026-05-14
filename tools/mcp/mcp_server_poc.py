"""
AIBA MCP Server POC
Task: PT-S125-BOOT-ONDEMAND-001
EAG: EAG-2 비오(Joshua) 승인 (S126)

목적: claude.ai MCP Remote Connector 연결 가능성 검증
도구: ping / get_server_status / get_current_epoch (화이트리스트형 고정 반환)

제약:
- 인자로 조회 범위 확장 방식 금지
- 화이트리스트형 고정 반환만 허용
- 모든 호출 Audit Trail 로깅 필수
- get_all_context() 류 full preload 도구 절대 금지
"""

import json
import time
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Logging — Audit Trail (모든 호출 기록)
# ---------------------------------------------------------------------------

_AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/audit_trail.log"
_LOG_FORMAT = "%(asctime)s [AUDIT] %(message)s"

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
try:
    import os
    os.makedirs(os.path.dirname(_AUDIT_LOG_PATH), exist_ok=True)
    _handlers.append(logging.FileHandler(_AUDIT_LOG_PATH))
except OSError:
    pass  # VPS 경로 없는 로컬 테스트 환경 — stderr만 사용

logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=_handlers)
logger = logging.getLogger("aiba_mcp_poc")

# ---------------------------------------------------------------------------
# 서버 상수 (화이트리스트 고정값)
# ---------------------------------------------------------------------------

SERVER_NAME = "aiba-mcp-poc"
SERVER_VERSION = "0.1.0"
AIBA_SYSTEM = "AIBA Self-Evolution-Ready System"
AIBA_VERSION = "v1.5"
VPS_HOST = "159.203.125.1"
CANONICAL_PATH = "/opt/arss/engine/arss-protocol"


def _audit(tool_name: str, result_summary: str) -> None:
    """모든 도구 호출을 Audit Trail에 기록한다."""
    logger.info("TOOL_CALL tool=%s result=%s", tool_name, result_summary)


# ---------------------------------------------------------------------------
# 도구 구현
# ---------------------------------------------------------------------------

def ping() -> dict[str, Any]:
    """서버 생존 확인 — 고정 응답 반환."""
    result = {
        "status": "ok",
        "message": "AIBA MCP POC server is alive",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _audit("ping", "ok")
    return result


def get_server_status() -> dict[str, Any]:
    """서버 및 AIBA 시스템 상태 반환 — 화이트리스트 고정값만."""
    result = {
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "aiba_system": AIBA_SYSTEM,
        "aiba_version": AIBA_VERSION,
        "vps_host": VPS_HOST,
        "canonical_path": CANONICAL_PATH,
        "mcp_poc_task": "PT-S125-BOOT-ONDEMAND-001",
        "eag_stage": "EAG-2_COMPLETE",
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _audit("get_server_status", "operational")
    return result


def get_current_epoch() -> dict[str, Any]:
    """현재 epoch 및 UTC 타임스탬프 반환."""
    now = datetime.now(timezone.utc)
    result = {
        "epoch_ms": int(now.timestamp() * 1000),
        "epoch_s": int(now.timestamp()),
        "utc_iso": now.isoformat(),
        "source": "vps_system_clock",
        "note": "Used for CLASS-B Integrity Contract canonical_epoch field",
    }
    _audit("get_current_epoch", f"epoch_ms={result['epoch_ms']}")
    return result


# ---------------------------------------------------------------------------
# MCP 프로토콜 핸들러 (stdio JSON-RPC)
# ---------------------------------------------------------------------------

TOOLS = {
    "ping": {
        "name": "ping",
        "description": "AIBA MCP POC 서버 생존 확인. 고정 응답 반환.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "fn": ping,
    },
    "get_server_status": {
        "name": "get_server_status",
        "description": "AIBA 시스템 및 MCP 서버 상태를 화이트리스트 고정값으로 반환.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "fn": get_server_status,
    },
    "get_current_epoch": {
        "name": "get_current_epoch",
        "description": "현재 epoch(ms/s) 및 UTC 타임스탬프 반환. CLASS-B Integrity Contract canonical_epoch 용도.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "fn": get_current_epoch,
    },
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle(request: dict) -> None:
    method = request.get("method", "")
    req_id = request.get("id")

    # initialize
    if method == "initialize":
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        })

    # tools/list
    elif method == "tools/list":
        tool_list = [
            {
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            }
            for t in TOOLS.values()
        ]
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_list}})

    # tools/call
    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        if tool_name not in TOOLS:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            })
            return
        try:
            result = TOOLS[tool_name]["fn"]()
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            })
        except Exception as exc:
            logger.error("TOOL_ERROR tool=%s error=%s", tool_name, str(exc))
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {exc}"}],
                    "isError": True,
                },
            })

    # notifications/initialized (응답 불필요)
    elif method == "notifications/initialized":
        pass

    else:
        if req_id is not None:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


def main() -> None:
    logger.info("AIBA MCP POC Server starting — task=PT-S125-BOOT-ONDEMAND-001")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            _handle(request)
        except json.JSONDecodeError as exc:
            logger.error("JSON_DECODE_ERROR: %s", exc)
            _send({
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            })


if __name__ == "__main__":
    main()

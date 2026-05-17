"""
mcp_write_server.py — MCP Write Plane Server v1.0.0
PT-S136-MCP-WRITE-GATEKEEPER

Read Plane(mcp_read_server.py)과 물리적으로 분리된 Write Plane 서버.
모든 쓰기 요청은 MCP_WriteGatekeeper를 통과해야 함.

Tools:
  - write_file: EAG approval 기반 sandbox 파일 쓰기
  - get_write_plane_state: Write Plane 현재 상태 조회
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_gatekeeper import get_gatekeeper, FailClosedError, WritePlaneState

WRITE_SERVER_VERSION = "1.0.0"

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

WRITE_SERVER_PORT = 8444  # Read server: 8443, Write server: 8444 (물리적 분리)


# ── Tool Handlers ─────────────────────────────────────────────────────

def handle_write_file(approval_id: str, target_path: str, content: str) -> dict:
    """write_file tool 핸들러. Gatekeeper 통과 필수."""
    gk = get_gatekeeper()
    try:
        result = gk.execute_write(approval_id, target_path, content)
        return {"ok": True, "result": result}
    except FailClosedError as fc:
        return {
            "ok": False,
            "error": str(fc),
            "tier": fc.tier,
            "write_plane_state": gk.get_state().value,
        }
    except Exception as exc:
        return {"ok": False, "error": f"unexpected error: {exc}"}


def handle_get_write_plane_state() -> dict:
    """Write Plane 상태 조회 tool 핸들러."""
    gk = get_gatekeeper()
    return {"ok": True, "write_plane_state": gk.get_state().value}


# ── FastAPI App ───────────────────────────────────────────────────────

def create_app():
    if not HAS_FASTAPI:
        raise RuntimeError("fastapi/uvicorn not installed")

    app = FastAPI(
        title="AIBA MCP Write Server",
        version=WRITE_SERVER_VERSION,
        description="MCP Write Plane — Read Plane과 물리적 분리. Gatekeeper 통과 필수.",
    )

    @app.get("/health")
    async def health():
        gk = get_gatekeeper()
        return {
            "status": "ok",
            "write_plane_state": gk.get_state().value,
            "version": WRITE_SERVER_VERSION,
        }

    @app.post("/mcp/write")
    async def mcp_write(request: Request):
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"ok": False, "error": "invalid JSON body"}, status_code=400)

        tool = body.get("tool")
        params = body.get("params", {})

        if tool == "write_file":
            approval_id = params.get("approval_id")
            target_path = params.get("target_path")
            content = params.get("content", "")
            if not approval_id or not target_path:
                return JSONResponse(
                    {"ok": False, "error": "approval_id and target_path required"},
                    status_code=400,
                )
            result = handle_write_file(approval_id, target_path, content)
            status_code = 200 if result["ok"] else 403
            return JSONResponse(result, status_code=status_code)

        elif tool == "get_write_plane_state":
            return JSONResponse(handle_get_write_plane_state())

        else:
            return JSONResponse(
                {"ok": False, "error": f"unknown tool: {tool}"},
                status_code=400,
            )

    return app


# ── Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    if not HAS_FASTAPI:
        print(
            "[WRITE_SERVER] ERROR: fastapi/uvicorn required. "
            "pip install fastapi uvicorn --break-system-packages",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[WRITE_SERVER] AIBA MCP Write Server v{WRITE_SERVER_VERSION} starting")
    print(f"[WRITE_SERVER] Port: {WRITE_SERVER_PORT} (Read Plane: 8443)")
    print(f"[WRITE_SERVER] Write Plane physically separated from Read Plane")

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=WRITE_SERVER_PORT)

"""
mcp_write_server.py — MCP Write Plane Server v2.1.0
PT-S137-MCP-WRITE-RUNTIME-001

Read Plane(mcp_read_server.py)과 물리적으로 분리된 Write Plane 서버.
모든 쓰기 요청은 MCP_WriteGatekeeper를 통과해야 함.

변경 이력:
  v1.0.0 (S136): FastAPI/uvicorn 기반 초기 구현
  v2.0.0 (S137): FastAPI/uvicorn 제거 → Python 표준 라이브러리(http.server) 기반 재구현
                 External dependency = 0
                 endpoint contract 보존 (/health GET, /mcp/write POST)
                 MAX_REQUEST_BODY_BYTES = 65536 (gatekeeper 진입 전 검증)
  v2.1.0 (S140): Recovery endpoint 추가 (PT-S140-MCP-WRITE-RECOVERY-001)
                 POST /internal/recovery/enter → beo_enter_recovery_mode()
                 POST /internal/recovery/close → beo_recovery_close()
                 BEO_ONLY authority basis: loopback-only + VPS shell possession
                 MCP bridge 미노출 / claude.ai 미노출
                 Jeni TRUST-ADVISORY 반영: RECEIPTS_DIR 조회 실패 시 FAIL-CLOSED

Tools:
  - write_file: EAG approval 기반 sandbox 파일 쓰기
  - get_write_plane_state: Write Plane 현재 상태 조회

Internal Recovery (BEO_ONLY, loopback-only, MCP 미노출):
  - /internal/recovery/enter: LOCKED/HOLD → RECOVERY_MODE
  - /internal/recovery/close: RECOVERY_MODE → NORMAL (PENDING receipt 없을 때만)
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_gatekeeper import get_gatekeeper, FailClosedError, WritePlaneState
from mcp_write_config import RECEIPTS_DIR

WRITE_SERVER_VERSION = "2.1.0"
WRITE_SERVER_PORT = 8444        # Read server: 8443, Write server: 8444 (물리적 분리)
WRITE_SERVER_HOST = "127.0.0.1" # loopback only — Nginx reverse proxy만 진입점
MAX_REQUEST_BODY_BYTES = 65536  # 64 KiB — gatekeeper 호출 전 검증 (D-3 설계 Lock)


# ── 감사 로그 ─────────────────────────────────────────────────────────

def _log(level: str, msg: str) -> None:
    """sys.stderr 기반 감사 로그 (제니 ADVISORY 2항)."""
    print(f"[WRITE_SERVER][{level}] {msg}", file=sys.stderr, flush=True)


# ── Tool Handlers ─────────────────────────────────────────────────────

def handle_write_file(approval_id: str, target_path: str, content: str) -> dict:
    """write_file tool 핸들러. Gatekeeper 통과 필수."""
    gk = get_gatekeeper()
    try:
        result = gk.execute_write(approval_id, target_path, content)
        _log("INFO", f"write_file OK: approval_id={approval_id} path={target_path}")
        return {"ok": True, "result": result}
    except FailClosedError as fc:
        _log("WARN", f"write_file FAIL-CLOSED: tier={fc.tier} approval_id={approval_id}")
        return {
            "ok": False,
            "error": str(fc),
            "tier": fc.tier,
            "write_plane_state": gk.get_state().value,
        }
    except Exception as exc:
        _log("ERROR", f"write_file unexpected: {exc}")
        return {"ok": False, "error": f"unexpected error: {exc}"}


def handle_get_write_plane_state() -> dict:
    """Write Plane 상태 조회 tool 핸들러."""
    gk = get_gatekeeper()
    state = gk.get_state().value
    _log("INFO", f"get_write_plane_state: {state}")
    return {"ok": True, "write_plane_state": state}


# ── Recovery Handlers (BEO_ONLY, loopback-only, MCP 미노출) ──────────

def _find_pending_receipts() -> list:
    """
    PENDING_BEO_REVIEW 상태 receipt 목록 반환.
    조회 실패(권한 오류, 경로 없음 등) 시 FAIL-CLOSED — 빈 리스트 반환 금지.
    Jeni TRUST-ADVISORY: 조회 불가 → 거부 처리.
    반환: (receipts: list, error: str or None)
    """
    if not os.path.exists(RECEIPTS_DIR):
        # 디렉토리 자체가 없으면 pending 없음으로 간주 (정상 초기 상태)
        return [], None

    try:
        entries = os.listdir(RECEIPTS_DIR)
    except OSError as e:
        # 조회 실패 → FAIL-CLOSED (pending이 없다고 가정하지 않음)
        return None, f"RECEIPTS_DIR listdir failed: {e}"

    pending = []
    for fname in sorted(entries):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(RECEIPTS_DIR, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                receipt = json.load(f)
            if receipt.get("status") == "PENDING_BEO_REVIEW":
                pending.append(receipt.get("receipt_id", fname))
        except (OSError, json.JSONDecodeError) as e:
            # 개별 파일 읽기 실패 → FAIL-CLOSED
            return None, f"receipt file read failed ({fname}): {e}"

    return pending, None


def handle_recovery_enter() -> tuple:
    """
    POST /internal/recovery/enter
    LOCKED 또는 HOLD → RECOVERY_MODE 전환.
    authority basis: loopback-only + VPS shell possession (BEO_ONLY)
    반환: (status_code, body_dict)
    """
    gk = get_gatekeeper()
    current_state = gk.get_state().value
    try:
        gk.beo_enter_recovery_mode()
        new_state = gk.get_state().value
        _log("INFO", f"recovery/enter OK: {current_state} → {new_state}")
        return 200, {
            "ok": True,
            "previous_state": current_state,
            "current_state": new_state,
        }
    except ValueError as e:
        _log("WARN", f"recovery/enter DENIED: state={current_state} reason={e}")
        return 400, {
            "ok": False,
            "error": str(e),
            "write_plane_state": current_state,
        }
    except Exception as e:
        _log("ERROR", f"recovery/enter unexpected: {e}")
        return 500, {"ok": False, "error": f"unexpected error: {e}"}


def handle_recovery_close() -> tuple:
    """
    POST /internal/recovery/close
    RECOVERY_MODE → NORMAL 전환.
    PENDING_BEO_REVIEW receipt 존재 시 거부 (receipt chain 보호).
    RECEIPTS_DIR 조회 실패 시 FAIL-CLOSED (Jeni TRUST-ADVISORY).
    authority basis: loopback-only + VPS shell possession (BEO_ONLY)
    반환: (status_code, body_dict)
    """
    gk = get_gatekeeper()
    current_state = gk.get_state().value

    # PENDING receipt 확인 — 조회 실패 시 FAIL-CLOSED
    pending, err = _find_pending_receipts()
    if err is not None:
        _log("WARN", f"recovery/close DENIED: receipt scan failed — {err}")
        return 500, {
            "ok": False,
            "error": f"FAIL-CLOSED: receipt scan failed — {err}",
            "write_plane_state": current_state,
        }

    if pending:
        _log("WARN", f"recovery/close DENIED: {len(pending)} PENDING receipt(s) exist: {pending}")
        return 400, {
            "ok": False,
            "error": "PENDING_BEO_REVIEW receipts exist — resolve before closing recovery",
            "pending_receipts": pending,
            "write_plane_state": current_state,
        }

    try:
        gk.beo_recovery_close()
        new_state = gk.get_state().value
        _log("INFO", f"recovery/close OK: {current_state} → {new_state}")
        return 200, {
            "ok": True,
            "previous_state": current_state,
            "current_state": new_state,
        }
    except ValueError as e:
        _log("WARN", f"recovery/close DENIED: state={current_state} reason={e}")
        return 400, {
            "ok": False,
            "error": str(e),
            "write_plane_state": current_state,
        }
    except Exception as e:
        _log("ERROR", f"recovery/close unexpected: {e}")
        return 500, {"ok": False, "error": f"unexpected error: {e}"}


# ── JSON 응답 헬퍼 ────────────────────────────────────────────────────

def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    """JSON envelope 응답 전송."""
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


# ── Request Body 검증 ────────────────────────────────────────────────

def _read_body(handler: BaseHTTPRequestHandler):
    """
    Content-Length 기반 body 읽기 + 65536 bytes 제한 검증.
    도미 설계 Lock 4규칙:
      1. Content-Length 없음 → reject
      2. Content-Length 비정수 → reject
      3. Content-Length > 65536 → reject
      4. 실제 read 중 초과 감지 → reject
    반환: (body_bytes, error_dict or None)
    """
    cl_header = handler.headers.get("Content-Length")

    # 규칙 1: Content-Length 없음
    if cl_header is None:
        _log("WARN", "rejected: Content-Length missing")
        return None, {"ok": False, "error": "Content-Length header required"}

    # 규칙 2: Content-Length 비정수
    try:
        content_length = int(cl_header)
    except ValueError:
        _log("WARN", f"rejected: Content-Length non-integer: {cl_header!r}")
        return None, {"ok": False, "error": "Content-Length must be an integer"}

    # 규칙 3: Content-Length 초과
    if content_length > MAX_REQUEST_BODY_BYTES:
        _log("WARN", f"rejected: Content-Length {content_length} > {MAX_REQUEST_BODY_BYTES}")
        return None, {
            "ok": False,
            "error": f"Request body exceeds limit ({MAX_REQUEST_BODY_BYTES} bytes)",
        }

    # 규칙 4: 실제 read 중 초과 감지
    body = handler.rfile.read(content_length)
    if len(body) > MAX_REQUEST_BODY_BYTES:
        _log("WARN", f"rejected: actual body {len(body)} > {MAX_REQUEST_BODY_BYTES}")
        return None, {
            "ok": False,
            "error": f"Request body exceeds limit ({MAX_REQUEST_BODY_BYTES} bytes)",
        }

    return body, None


# ── HTTP Handler ──────────────────────────────────────────────────────

class WriteServerHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):  # BaseHTTPRequestHandler 기본 로그 → stderr 통일
        _log("ACCESS", fmt % args)

    # ── GET /health ───────────────────────────────────────────────────

    def do_GET(self):
        if self.path == "/health":
            gk = get_gatekeeper()
            _json_response(self, 200, {
                "status": "ok",
                "write_plane_state": gk.get_state().value,
                "version": WRITE_SERVER_VERSION,
            })
        else:
            _log("WARN", f"GET unknown path: {self.path}")
            _json_response(self, 403, {"ok": False, "error": "forbidden"})

    # ── POST ──────────────────────────────────────────────────────────

    def do_POST(self):
        # ── /internal/recovery/* (BEO_ONLY, body 불필요) ─────────────
        if self.path == "/internal/recovery/enter":
            status, body = handle_recovery_enter()
            _json_response(self, status, body)
            return

        if self.path == "/internal/recovery/close":
            status, body = handle_recovery_close()
            _json_response(self, status, body)
            return

        # ── /mcp/write ────────────────────────────────────────────────
        if self.path != "/mcp/write":
            _log("WARN", f"POST unknown path: {self.path}")
            _json_response(self, 403, {"ok": False, "error": "forbidden"})
            return

        # body size 검증 (gatekeeper 진입 전)
        body_bytes, err = _read_body(self)
        if err is not None:
            _json_response(self, 400, err)
            return

        # JSON 파싱
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            _log("WARN", "rejected: invalid JSON body")
            _json_response(self, 400, {"ok": False, "error": "invalid JSON body"})
            return

        tool = body.get("tool")
        params = body.get("params", {})

        if tool == "write_file":
            approval_id = params.get("approval_id")
            target_path = params.get("target_path")
            content = params.get("content", "")
            if not approval_id or not target_path:
                _json_response(self, 400, {
                    "ok": False,
                    "error": "approval_id and target_path required",
                })
                return
            result = handle_write_file(approval_id, target_path, content)
            status_code = 200 if result["ok"] else 403
            _json_response(self, status_code, result)

        elif tool == "get_write_plane_state":
            _json_response(self, 200, handle_get_write_plane_state())

        elif tool is None:
            _log("WARN", "rejected: tool field missing")
            _json_response(self, 400, {"ok": False, "error": "tool field required"})

        else:
            _log("WARN", f"rejected: unknown tool: {tool!r}")
            _json_response(self, 400, {"ok": False, "error": f"unknown tool: {tool}"})

    # ── 미허용 메서드 ─────────────────────────────────────────────────

    def do_PUT(self):
        _log("WARN", f"method not allowed: PUT {self.path}")
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})

    def do_DELETE(self):
        _log("WARN", f"method not allowed: DELETE {self.path}")
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})

    def do_PATCH(self):
        _log("WARN", f"method not allowed: PATCH {self.path}")
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})


# ── Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    _log("INFO", f"AIBA MCP Write Server v{WRITE_SERVER_VERSION} starting")
    _log("INFO", f"Port: {WRITE_SERVER_PORT} (Read Plane: 8443)")
    _log("INFO", f"Host: {WRITE_SERVER_HOST} (loopback only)")
    _log("INFO", f"MAX_REQUEST_BODY_BYTES: {MAX_REQUEST_BODY_BYTES}")
    _log("INFO", "External dependency: 0 (stdlib only)")
    _log("INFO", "Recovery endpoints: /internal/recovery/enter, /internal/recovery/close")

    server = HTTPServer((WRITE_SERVER_HOST, WRITE_SERVER_PORT), WriteServerHandler)
    _log("INFO", "Server ready. Waiting for requests.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("INFO", "Server shutdown requested.")
        server.server_close()

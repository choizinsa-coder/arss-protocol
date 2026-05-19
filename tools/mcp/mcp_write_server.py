"""
mcp_write_server.py — MCP Write Plane Server v2.3.0
PT-S141-MCP-WRITE-FINALIZE-001

v2.3.0 (S141): NORMAL → RECOVERY_MODE 조건부 전이 지원
  handle_recovery_enter(): NORMAL 상태 시 _find_pending_receipts() scan 수행
  pending_count를 beo_enter_recovery_mode(pending_count)에 전달
  entry_reason을 응답 body에 포함
  도미 S141-002 설계 + 제니 TRUST_READY PASS(T-1~T-6) + EAG-2 비오(Joshua) 승인
"""

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_gatekeeper import get_gatekeeper, FailClosedError, WritePlaneState
from mcp_write_config import RECEIPTS_DIR, TOKEN_TTL

WRITE_SERVER_VERSION = "2.3.0"
WRITE_SERVER_PORT = 8444
WRITE_SERVER_HOST = "127.0.0.1"
MAX_REQUEST_BODY_BYTES = 65536

TERMINAL_STATES = {"CONFIRMED", "REJECTED", "EXPIRED"}
ALLOWED_FINALIZE_TARGETS = {"CONFIRMED", "REJECTED"}


# ── 감사 로그 ─────────────────────────────────────────────────────────

def _log(level: str, msg: str) -> None:
    print(f"[WRITE_SERVER][{level}] {msg}", file=sys.stderr, flush=True)


# ── Tool Handlers ─────────────────────────────────────────────────────

def handle_write_file(approval_id: str, target_path: str, content: str) -> dict:
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
    gk = get_gatekeeper()
    state = gk.get_state().value
    _log("INFO", f"get_write_plane_state: {state}")
    return {"ok": True, "write_plane_state": state}


# ── Receipt Scan 헬퍼 ─────────────────────────────────────────────────

def _find_pending_receipts() -> tuple:
    """
    PENDING_BEO_REVIEW 상태 receipt 목록 반환.
    반환: (receipts: list | None, error: str | None)
    조회 실패 시 FAIL-CLOSED — None 반환.
    """
    if not os.path.exists(RECEIPTS_DIR):
        return [], None
    try:
        entries = os.listdir(RECEIPTS_DIR)
    except OSError as e:
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
            return None, f"receipt file read failed ({fname}): {e}"

    return pending, None


# ── Recovery Handlers ─────────────────────────────────────────────────

def handle_recovery_enter() -> tuple:
    """
    POST /internal/recovery/enter
    LOCKED/HOLD → RECOVERY_MODE : 기존 경로 (무조건)
    NORMAL      → RECOVERY_MODE : PENDING receipts 존재 시 조건부 (v2.3.0 신규)

    NORMAL 상태에서:
      - scan 실패 → FAIL_CLOSED (500)
      - PENDING 없음 → DENY (400)
      - PENDING 존재 → RECOVERY_MODE 진입, entry_reason=STALE_PENDING_RECEIPT_RECOVERY
    """
    gk = get_gatekeeper()
    current_state = gk.get_state().value

    # NORMAL 상태 전용 사전 scan (v2.3.0)
    pending_count = 0
    if current_state == WritePlaneState.NORMAL.value:
        pending, err = _find_pending_receipts()
        if err is not None:
            _log("WARN", f"recovery/enter FAIL-CLOSED: scan failed in NORMAL state — {err}")
            return 500, {
                "ok": False,
                "error": f"FAIL-CLOSED: receipt scan failed — {err}",
                "write_plane_state": current_state,
            }
        pending_count = len(pending)
        if pending_count == 0:
            _log("WARN", "recovery/enter DENIED: NORMAL state + no PENDING receipts")
            return 400, {
                "ok": False,
                "error": "NORMAL → RECOVERY_MODE 불가: PENDING receipt 없음",
                "write_plane_state": current_state,
            }
        _log("INFO", f"recovery/enter: NORMAL state, {pending_count} PENDING receipt(s) detected")

    try:
        entry_reason = gk.beo_enter_recovery_mode(pending_count=pending_count)
        new_state = gk.get_state().value
        _log("INFO", f"recovery/enter OK: {current_state} → {new_state} reason={entry_reason}")
        return 200, {
            "ok": True,
            "previous_state": current_state,
            "current_state": new_state,
            "entry_reason": entry_reason,
            **({"pending_receipt_count": pending_count} if current_state == WritePlaneState.NORMAL.value else {}),
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
    """POST /internal/recovery/close — RECOVERY_MODE → NORMAL (PENDING 없을 때만)"""
    gk = get_gatekeeper()
    current_state = gk.get_state().value

    pending, err = _find_pending_receipts()
    if err is not None:
        _log("WARN", f"recovery/close DENIED: receipt scan failed — {err}")
        return 500, {
            "ok": False,
            "error": f"FAIL-CLOSED: receipt scan failed — {err}",
            "write_plane_state": current_state,
        }

    if pending:
        _log("WARN", f"recovery/close DENIED: {len(pending)} PENDING receipt(s): {pending}")
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


# ── Receipt Finalize Handler ──────────────────────────────────────────

def handle_receipt_finalize(receipt_id: str, target_state: str) -> tuple:
    """POST /internal/receipt/finalize — PENDING_BEO_REVIEW → CONFIRMED | REJECTED | EXPIRED"""
    gk = get_gatekeeper()

    current_plane_state = gk.get_state().value
    if current_plane_state != WritePlaneState.RECOVERY_MODE.value:
        _log("WARN", f"receipt/finalize DENIED: not RECOVERY_MODE (state={current_plane_state})")
        return 400, {
            "ok": False,
            "error": f"RECOVERY_MODE required (current: {current_plane_state})",
            "write_plane_state": current_plane_state,
        }

    if target_state not in ALLOWED_FINALIZE_TARGETS:
        _log("WARN", f"receipt/finalize DENIED: invalid target_state={target_state!r}")
        return 400, {
            "ok": False,
            "error": f"target_state must be one of {sorted(ALLOWED_FINALIZE_TARGETS)}",
        }

    receipt_path = os.path.join(RECEIPTS_DIR, f"{receipt_id}.json")
    if not os.path.exists(receipt_path):
        _log("WARN", f"receipt/finalize DENIED: not found: {receipt_id}")
        return 404, {"ok": False, "error": f"receipt not found: {receipt_id}"}

    try:
        with open(receipt_path, encoding="utf-8") as f:
            receipt = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log("ERROR", f"receipt/finalize FAIL-CLOSED: read error {receipt_id}: {e}")
        return 500, {"ok": False, "error": f"FAIL-CLOSED: receipt read failed: {e}"}

    current_receipt_status = receipt.get("status", "UNKNOWN")
    if current_receipt_status in TERMINAL_STATES:
        _log("WARN", f"receipt/finalize DENIED: already terminal: {receipt_id} status={current_receipt_status}")
        return 400, {
            "ok": False,
            "error": f"receipt already in terminal state: {current_receipt_status}",
            "receipt_id": receipt_id,
            "current_status": current_receipt_status,
        }

    if current_receipt_status != "PENDING_BEO_REVIEW":
        _log("WARN", f"receipt/finalize DENIED: unexpected status={current_receipt_status}")
        return 400, {
            "ok": False,
            "error": f"unexpected receipt status: {current_receipt_status} (PENDING_BEO_REVIEW required)",
            "receipt_id": receipt_id,
        }

    effective_target_state = target_state
    ttl_expired = False
    created_at_str = receipt.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
            if elapsed > TOKEN_TTL:
                effective_target_state = "EXPIRED"
                ttl_expired = True
                _log("INFO", f"receipt/finalize TTL override: {receipt_id} elapsed={elapsed:.0f}s → EXPIRED")
        except ValueError as e:
            _log("WARN", f"receipt/finalize created_at parse failed: {e} — TTL check skipped")

    finalized_at = datetime.now(timezone.utc).isoformat()
    receipt["status"] = effective_target_state
    receipt["finalized_at"] = finalized_at
    receipt["finalized_by"] = "Beo"
    receipt["finalize_requested_target"] = target_state

    try:
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2, ensure_ascii=False)
    except OSError as e:
        _log("ERROR", f"receipt/finalize write failed: {receipt_id}: {e}")
        return 500, {"ok": False, "error": f"FAIL-CLOSED: receipt write failed: {e}"}

    _log("INFO", f"receipt/finalize OK: {receipt_id} PENDING_BEO_REVIEW → {effective_target_state}")
    return 200, {
        "ok": True,
        "receipt_id": receipt_id,
        "previous_status": "PENDING_BEO_REVIEW",
        "current_status": effective_target_state,
        "finalized_at": finalized_at,
        "ttl_expired": ttl_expired,
    }


# ── JSON 응답 헬퍼 ────────────────────────────────────────────────────

def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


# ── Request Body 검증 ────────────────────────────────────────────────

def _read_body(handler: BaseHTTPRequestHandler):
    cl_header = handler.headers.get("Content-Length")
    if cl_header is None:
        _log("WARN", "rejected: Content-Length missing")
        return None, {"ok": False, "error": "Content-Length header required"}
    try:
        content_length = int(cl_header)
    except ValueError:
        _log("WARN", f"rejected: Content-Length non-integer: {cl_header!r}")
        return None, {"ok": False, "error": "Content-Length must be an integer"}
    if content_length > MAX_REQUEST_BODY_BYTES:
        _log("WARN", f"rejected: Content-Length {content_length} > {MAX_REQUEST_BODY_BYTES}")
        return None, {"ok": False, "error": f"Request body exceeds limit ({MAX_REQUEST_BODY_BYTES} bytes)"}
    body = handler.rfile.read(content_length)
    if len(body) > MAX_REQUEST_BODY_BYTES:
        _log("WARN", f"rejected: actual body {len(body)} > {MAX_REQUEST_BODY_BYTES}")
        return None, {"ok": False, "error": f"Request body exceeds limit ({MAX_REQUEST_BODY_BYTES} bytes)"}
    return body, None


# ── HTTP Handler ──────────────────────────────────────────────────────

class WriteServerHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        _log("ACCESS", fmt % args)

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

    def do_POST(self):
        if self.path == "/internal/recovery/enter":
            status, body = handle_recovery_enter()
            _json_response(self, status, body)
            return

        if self.path == "/internal/recovery/close":
            status, body = handle_recovery_close()
            _json_response(self, status, body)
            return

        if self.path == "/internal/receipt/finalize":
            body_bytes, err = _read_body(self)
            if err is not None:
                _json_response(self, 400, err)
                return
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                _log("WARN", "rejected: invalid JSON body")
                _json_response(self, 400, {"ok": False, "error": "invalid JSON body"})
                return
            receipt_id = body.get("receipt_id")
            target_state = body.get("target_state")
            if not receipt_id or not target_state:
                _json_response(self, 400, {"ok": False, "error": "receipt_id and target_state required"})
                return
            status, resp_body = handle_receipt_finalize(receipt_id, target_state)
            _json_response(self, status, resp_body)
            return

        if self.path != "/mcp/write":
            _log("WARN", f"POST unknown path: {self.path}")
            _json_response(self, 403, {"ok": False, "error": "forbidden"})
            return

        body_bytes, err = _read_body(self)
        if err is not None:
            _json_response(self, 400, err)
            return
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
                _json_response(self, 400, {"ok": False, "error": "approval_id and target_path required"})
                return
            result = handle_write_file(approval_id, target_path, content)
            _json_response(self, 200 if result["ok"] else 403, result)
        elif tool == "get_write_plane_state":
            _json_response(self, 200, handle_get_write_plane_state())
        elif tool is None:
            _log("WARN", "rejected: tool field missing")
            _json_response(self, 400, {"ok": False, "error": "tool field required"})
        else:
            _log("WARN", f"rejected: unknown tool: {tool!r}")
            _json_response(self, 400, {"ok": False, "error": f"unknown tool: {tool}"})

    def do_PUT(self):
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})

    def do_DELETE(self):
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})

    def do_PATCH(self):
        _json_response(self, 405, {"ok": False, "error": "method not allowed"})


# ── Entry Point ───────────────────────────────────────────────────────

if __name__ == "__main__":
    _log("INFO", f"AIBA MCP Write Server v{WRITE_SERVER_VERSION} starting")
    _log("INFO", f"Port: {WRITE_SERVER_PORT} | Host: {WRITE_SERVER_HOST} | MaxBody: {MAX_REQUEST_BODY_BYTES}")
    _log("INFO", "Endpoints: /internal/recovery/enter, /internal/recovery/close, /internal/receipt/finalize")
    server = HTTPServer((WRITE_SERVER_HOST, WRITE_SERVER_PORT), WriteServerHandler)
    _log("INFO", "Server ready.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("INFO", "Server shutdown.")
        server.server_close()

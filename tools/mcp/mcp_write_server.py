"""
mcp_write_server.py — MCP Write Plane Server v3.0.1
EAG-1 (S164): Write Plane Restore

v3.0.1 (S178):
  - handle_receipt_finalize 추가 (P4-C4 Batch-6, EAG-1 비오 승인)
  - RECEIPTS_DIR 변수 추가
  - get_gatekeeper import 추가 (하위 호환)
  - 기존 v3.0.0 코드 변경 없음

v3.0.0 (S164):
  - mcp_write_gatekeeper 의존 완전 제거
  - Tier Router (tools/mcp_write/tier_router.py) 기반 신규 흐름 적용
  - Tier1Handler / Tier2Handler 연결
  - 상태 모델: NORMAL / LOCKED_TIER1 / LOCKED_ALL / RECOVERY
  - 기존 /internal/recovery/* 엔드포인트 유지 (하위 호환)
  - CONTRACT-01~10 집행 구조 완성

v2.3.0 (S141): NORMAL → RECOVERY_MODE 조건부 전이 지원 [SUPERSEDED]
"""

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

_ROOT = "/opt/arss/engine/arss-protocol"
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.mcp_write.tier_router import (
    route_request,
    get_write_plane_state,
    set_write_plane_state,
    WritePlaneState,
    WritePlaneLockedError,
    TierClassification,
)
from tools.mcp_write.tier1_handler import handle_tier1_write, Tier1DenyError
from tools.mcp_write.tier2_handler import handle_tier2_write, Tier2DenyError
from mcp_write_gatekeeper import get_gatekeeper, WritePlaneState as GatekeeperState
from mcp_write_config import RECEIPTS_DIR, TOKEN_TTL

WRITE_SERVER_VERSION = "3.0.1"
WRITE_SERVER_PORT = 8444
WRITE_SERVER_HOST = "127.0.0.1"
MAX_REQUEST_BODY_BYTES = 65536

# finalize 허용 target_state
_FINALIZE_VALID_TARGET_STATES = {"CONFIRMED", "REJECTED"}
# terminal 상태 (불변)
_FINALIZE_TERMINAL_STATUSES = {"CONFIRMED", "REJECTED", "EXPIRED"}


# ── 로그 ──────────────────────────────────────────────────────────────

def _log(level: str, msg: str) -> None:
    print(f"[WRITE_SERVER_V3][{level}] {msg}", file=sys.stderr, flush=True)


# ── Tool Handlers ─────────────────────────────────────────────────────

def handle_write_file(approval_id: str, target_path: str, content: str) -> dict:
    """
    write_file 요청 처리.
    Tier Router → Tier1 또는 Tier2 핸들러로 분기.
    """
    try:
        tier = route_request(target_path)
    except WritePlaneLockedError as e:
        _log("WARN", f"write_file LOCKED: {e}")
        return {
            "ok": False,
            "error": str(e),
            "write_plane_state": e.state,
        }

    # Tier2: approval 불필요 (CONTRACT-01)
    if tier == TierClassification.TIER2:
        try:
            result = handle_tier2_write(target_path, content)
            _log("INFO", f"write_file TIER2 OK: path={target_path}")
            return {"ok": True, "result": result}
        except Tier2DenyError as e:
            _log("WARN", f"write_file TIER2 DENY: {e}")
            return {"ok": False, "error": str(e), "tier": "TIER2"}

    # Tier1: approval_id 필수 (CONTRACT-04)
    if not approval_id:
        _log("WARN", f"write_file TIER1 DENY: approval_id missing (CONTRACT-04)")
        return {
            "ok": False,
            "error": "TIER1: approval_id 필수 (CONTRACT-04)",
            "tier": "TIER1",
        }

    try:
        result = handle_tier1_write(approval_id, target_path, content)
        _log("INFO", f"write_file TIER1 OK: approval_id={approval_id} path={target_path}")
        return {"ok": True, "result": result}
    except FileNotFoundError as e:
        _log("WARN", f"write_file TIER1 DENY: artifact not found {e}")
        return {"ok": False, "error": f"approval artifact not found: {e}", "tier": "TIER1"}
    except Tier1DenyError as e:
        _log("WARN", f"write_file TIER1 DENY: {e}")
        return {
            "ok": False,
            "error": str(e),
            "tier": "TIER1",
            "contract": e.contract,
            "write_plane_state": get_write_plane_state().value,
        }
    except Exception as e:
        _log("ERROR", f"write_file TIER1 unexpected: {e}")
        return {"ok": False, "error": f"unexpected error: {e}"}


def handle_get_write_plane_state() -> dict:
    state = get_write_plane_state()
    _log("INFO", f"get_write_plane_state: {state.value}")
    return {"ok": True, "write_plane_state": state.value}


def handle_receipt_finalize(receipt_id: str, target_state: str) -> tuple:
    """
    POST /internal/receipt/finalize — receipt 상태 전이 (비오님 전용).

    RECOVERY_MODE 상태에서만 허용.
    PENDING_BEO_REVIEW → CONFIRMED / REJECTED (TTL 초과 시 EXPIRED 강제).
    terminal 상태(CONFIRMED/REJECTED/EXPIRED)는 불변.

    Returns:
        (http_status: int, body: dict)
    """
    gk = get_gatekeeper()
    state = gk.get_state()

    # 상태 검증: RECOVERY_MODE만 허용
    if state != GatekeeperState.RECOVERY_MODE:
        return 400, {
            "ok": False,
            "error": f"RECOVERY_MODE 상태에서만 finalize 가능. 현재: {state.value}",
        }

    # target_state 검증
    if target_state not in _FINALIZE_VALID_TARGET_STATES:
        return 400, {
            "ok": False,
            "error": (
                f"유효하지 않은 target_state: {target_state}. "
                f"허용: {sorted(_FINALIZE_VALID_TARGET_STATES)}"
            ),
        }

    # receipt 로드
    receipt_path = os.path.join(RECEIPTS_DIR, f"{receipt_id}.json")
    if not os.path.exists(receipt_path):
        return 404, {"ok": False, "error": f"receipt not found: {receipt_id}"}

    with open(receipt_path, encoding="utf-8") as f:
        receipt = json.load(f)

    current_status = receipt.get("status")

    # terminal immutability
    if current_status in _FINALIZE_TERMINAL_STATUSES:
        return 400, {
            "ok": False,
            "error": f"terminal 상태 변경 불가: {current_status}",
        }

    # PENDING_BEO_REVIEW 검증
    if current_status != "PENDING_BEO_REVIEW":
        return 400, {
            "ok": False,
            "error": (
                f"finalize 대상은 PENDING_BEO_REVIEW 상태여야 함. "
                f"현재: {current_status}"
            ),
        }

    # TTL 검사
    created_at = datetime.fromisoformat(receipt["created_at"])
    elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
    ttl_expired = elapsed > TOKEN_TTL

    final_status = "EXPIRED" if ttl_expired else target_state

    # receipt 업데이트 및 저장
    receipt["status"] = final_status
    receipt["finalized_by"] = "Beo"
    receipt["finalized_at"] = datetime.now(timezone.utc).isoformat()
    with open(receipt_path, "w", encoding="utf-8") as f:
        json.dump(receipt, f, indent=2, ensure_ascii=False)

    _log("INFO", f"receipt_finalize OK: {receipt_id} → {final_status} ttl_expired={ttl_expired}")
    return 200, {
        "ok": True,
        "receipt_id": receipt_id,
        "current_status": final_status,
        "ttl_expired": ttl_expired,
    }


# ── Recovery 진입 핸들러 (비오님 전용) ──────────────────────────────

def _find_pending_receipts(receipts_dir: str):
    """
    RECEIPTS_DIR에서 PENDING_BEO_REVIEW 상태 receipt 수를 반환.
    Returns:
        (count: int, error: None) — 정상
        (None, error_msg: str)   — scan 실패 (fail-closed)
    """
    try:
        if not os.path.exists(receipts_dir):
            return 0, None
        count = 0
        for fname in os.listdir(receipts_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(receipts_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    r = f.read()
                import json as _json
                data = _json.loads(r)
                if data.get("status") == "PENDING_BEO_REVIEW":
                    count += 1
            except Exception as _e:
                return None, f"receipt scan error: {_e}"
        return count, None
    except Exception as e:
        return None, f"receipts_dir scan failed: {e}"


def handle_recovery_enter() -> tuple:
    """
    POST /internal/recovery/enter — recovery 진입 (비오님 전용).

    NORMAL 상태: PENDING receipt 수 확인 후 조건부 진입
    LOCKED/HOLD 상태: 무조건 진입 (FAULT_RECOVERY)

    Returns:
        (http_status: int, body: dict)
    """
    gk = get_gatekeeper()
    state = gk.get_state()

    # NORMAL 상태: pending receipt 스캔 필요
    if state == state.__class__.NORMAL:
        pending_count, scan_error = _find_pending_receipts(RECEIPTS_DIR)

        # N-4: scan 실패 → FAIL-CLOSED
        if scan_error is not None:
            _log("ERROR", f"recovery_enter FAIL-CLOSED: {scan_error}")
            return 500, {
                "ok": False,
                "error": f"FAIL-CLOSED: receipt scan 실패 — {scan_error}",
            }

        # N-2: pending 없음 → deny
        if pending_count == 0:
            _log("WARN", "recovery_enter DENY: NORMAL 상태에서 PENDING receipt 없음")
            return 400, {
                "ok": False,
                "error": "NORMAL 상태에서 PENDING receipt 없음 — RECOVERY_MODE 진입 불가",
            }

        # N-1/N-3: pending 존재 → 진입
        try:
            entry_reason = gk.beo_enter_recovery_mode(pending_count=pending_count)
        except ValueError as e:
            # N-7: gatekeeper deny 전파
            _log("WARN", f"recovery_enter gatekeeper deny: {e}")
            return 400, {"ok": False, "error": str(e)}

        _log("INFO", f"recovery_enter OK: NORMAL reason={entry_reason} pending={pending_count}")
        return 200, {
            "ok": True,
            "entry_reason": entry_reason,
            "pending_receipt_count": pending_count,
        }

    # LOCKED / HOLD 상태: 무조건 진입 (N-5/N-6)
    try:
        entry_reason = gk.beo_enter_recovery_mode(pending_count=0)
    except ValueError as e:
        _log("WARN", f"recovery_enter gatekeeper deny: {e}")
        return 400, {"ok": False, "error": str(e)}

    _log("INFO", f"recovery_enter OK: {state.value} reason={entry_reason}")
    return 200, {
        "ok": True,
        "entry_reason": entry_reason,
    }


# ── 상태 관리 핸들러 (비오님 전용) ──────────────────────────────────

def handle_set_state(target_state_str: str, reason: str = "") -> tuple:
    """POST /internal/state/set — 비오님 수동 상태 변경."""
    try:
        target_state = WritePlaneState(target_state_str)
    except ValueError:
        valid = [s.value for s in WritePlaneState]
        return 400, {
            "ok": False,
            "error": f"유효하지 않은 상태: {target_state_str}. 허용: {valid}",
        }

    current = get_write_plane_state()
    set_write_plane_state(target_state, reason=reason or "manual_set_by_beo")
    _log("INFO", f"state/set: {current.value} → {target_state.value} reason={reason}")
    return 200, {
        "ok": True,
        "previous_state": current.value,
        "current_state": target_state.value,
        "reason": reason,
    }


# ── JSON 응답 / Body 파싱 ─────────────────────────────────────────────

def _json_response(handler: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def _read_body(handler: BaseHTTPRequestHandler):
    cl_header = handler.headers.get("Content-Length")
    if cl_header is None:
        return None, {"ok": False, "error": "Content-Length header required"}
    try:
        content_length = int(cl_header)
    except ValueError:
        return None, {"ok": False, "error": "Content-Length must be an integer"}
    if content_length > MAX_REQUEST_BODY_BYTES:
        return None, {"ok": False, "error": f"Request body exceeds limit ({MAX_REQUEST_BODY_BYTES} bytes)"}
    body = handler.rfile.read(content_length)
    return body, None


# ── HTTP Handler ──────────────────────────────────────────────────────

class WriteServerHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        _log("ACCESS", fmt % args)

    def do_GET(self):
        if self.path == "/health":
            state = get_write_plane_state()
            _json_response(self, 200, {
                "status": "ok",
                "write_plane_state": state.value,
                "version": WRITE_SERVER_VERSION,
            })
        else:
            _log("WARN", f"GET unknown path: {self.path}")
            _json_response(self, 403, {"ok": False, "error": "forbidden"})

    def do_POST(self):
        # 상태 수동 변경 (비오님 전용)
        if self.path == "/internal/state/set":
            body_bytes, err = _read_body(self)
            if err:
                _json_response(self, 400, err)
                return
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                _json_response(self, 400, {"ok": False, "error": "invalid JSON body"})
                return
            target_state = body.get("state")
            reason = body.get("reason", "")
            if not target_state:
                _json_response(self, 400, {"ok": False, "error": "state field required"})
                return
            status, resp = handle_set_state(target_state, reason)
            _json_response(self, status, resp)
            return

        # receipt finalize (비오님 전용)
        if self.path == "/internal/receipt/finalize":
            body_bytes, err = _read_body(self)
            if err:
                _json_response(self, 400, err)
                return
            try:
                body = json.loads(body_bytes.decode("utf-8"))
            except Exception:
                _json_response(self, 400, {"ok": False, "error": "invalid JSON body"})
                return
            receipt_id = body.get("receipt_id")
            target_state = body.get("target_state")
            if not receipt_id or not target_state:
                _json_response(self, 400, {"ok": False, "error": "receipt_id and target_state required"})
                return
            status, resp = handle_receipt_finalize(receipt_id, target_state)
            _json_response(self, status, resp)
            return

        # write_file / get_write_plane_state
        if self.path != "/mcp/write":
            _log("WARN", f"POST unknown path: {self.path}")
            _json_response(self, 403, {"ok": False, "error": "forbidden"})
            return

        body_bytes, err = _read_body(self)
        if err:
            _json_response(self, 400, err)
            return
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except Exception:
            _json_response(self, 400, {"ok": False, "error": "invalid JSON body"})
            return

        tool = body.get("tool")
        params = body.get("params", {})

        if tool == "write_file":
            approval_id = params.get("approval_id", "")
            target_path = params.get("target_path")
            content = params.get("content", "")
            if not target_path:
                _json_response(self, 400, {"ok": False, "error": "target_path required"})
                return
            result = handle_write_file(approval_id, target_path, content)
            _json_response(self, 200 if result["ok"] else 403, result)

        elif tool == "get_write_plane_state":
            _json_response(self, 200, handle_get_write_plane_state())

        elif tool is None:
            _json_response(self, 400, {"ok": False, "error": "tool field required"})

        else:
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
    _log("INFO", f"Port: {WRITE_SERVER_PORT} | Host: {WRITE_SERVER_HOST}")
    _log("INFO", "Tier Router 기반 Write Plane v2 활성화")
    server = HTTPServer((WRITE_SERVER_HOST, WRITE_SERVER_PORT), WriteServerHandler)
    _log("INFO", "Server ready.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("INFO", "Server shutdown.")
        server.server_close()

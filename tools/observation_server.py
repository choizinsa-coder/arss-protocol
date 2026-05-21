"""
observation_server.py
AIBA Observation Server — Layer 2 (L2-1, L2-10, L2-12)
SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL

port: 8445
runtime: Python stdlib HTTP server
purpose: OBSERVATION_ONLY + SANDBOX_WRITE_GATE
"""

import json
import os
import hashlib
import logging
import threading
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from projection_builder import get_projection, get_stale_output, check_ttl
from sandbox_validator import validate_write, SANDBOX_ROOT, ALLOWED_AGENTS

# ── 상수 ───────────────────────────────────────────────────────────────────

PORT = 8446
KST = timezone(timedelta(hours=9))
AUDIT_DIR = Path("/opt/arss/engine/arss-protocol/tools/sandbox/audit")
TOKEN_FILE = Path("/opt/arss/engine/arss-protocol/tools/sandbox/.tokens")

# ── Fail-Closed 상태 ───────────────────────────────────────────────────────

_fail_closed_lock = threading.Lock()
_system_state = {
    "observation_locked": False,
    "lock_reason": None,
    "lock_time": None,
}


def is_observation_locked() -> bool:
    with _fail_closed_lock:
        return _system_state["observation_locked"]


def engage_fail_closed(reason: str):
    """Fail-Closed 발동 (L2-12) — Execution Layer 비간섭"""
    with _fail_closed_lock:
        _system_state["observation_locked"] = True
        _system_state["lock_reason"] = reason
        _system_state["lock_time"] = datetime.now(KST).isoformat()
    _write_audit(
        agent="system",
        method="SYSTEM",
        path="fail_closed",
        status_code=503,
        result="FAIL_CLOSED_ENGAGED",
        reason=reason,
    )
    logging.critical(f"[FAIL-CLOSED] OBSERVATION_LOCKED: {reason}")


# ── 토큰 관리 ──────────────────────────────────────────────────────────────

# 토큰 저장 구조 (메모리)
# { "domi": {"hash": sha256_hex, "expires_epoch": float, "revoked": bool}, ... }
_token_store: dict = {}
_token_lock = threading.Lock()


def _sha256_prefix(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def register_token(agent: str, token: str, ttl_seconds: int = 43200):
    """토큰 등록 (TTL ≤ 12h = 43200s)"""
    assert agent in ALLOWED_AGENTS
    assert ttl_seconds <= 43200
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with _token_lock:
        _token_store[agent] = {
            "hash": token_hash,
            "expires_epoch": datetime.now(KST).timestamp() + ttl_seconds,
            "revoked": False,
        }


def revoke_token(agent: str):
    with _token_lock:
        if agent in _token_store:
            _token_store[agent]["revoked"] = True


def validate_token(agent: str, token: str) -> tuple[bool, str]:
    """
    토큰 검증
    반환: (valid: bool, reason: str)
    """
    with _token_lock:
        entry = _token_store.get(agent)
    if entry is None:
        return False, "TOKEN_REQUIRED"
    if entry["revoked"]:
        return False, "TOKEN_REVOKED"
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    if token_hash != entry["hash"]:
        return False, "TOKEN_AGENT_MISMATCH"
    if datetime.now(KST).timestamp() > entry["expires_epoch"]:
        return False, "TOKEN_EXPIRED"
    return True, "OK"


def _extract_token(handler: "ObservationHandler") -> tuple[Optional[str], Optional[str]]:
    """Authorization: Bearer <token> 헤더 파싱"""
    auth = handler.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, None
    token = auth[7:].strip()
    return token, _sha256_prefix(token)


# ── Audit ──────────────────────────────────────────────────────────────────

def _write_audit(
    agent: str,
    method: str,
    path: str,
    status_code: int,
    result: str,
    reason: Optional[str] = None,
    sandbox_filename: Optional[str] = None,
    response_bytes: int = 0,
    token_hash: Optional[str] = None,
):
    """append-only JSONL audit (L2-9)"""
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(KST).strftime("%Y%m%d")
    audit_path = AUDIT_DIR / f"agent_access_{date_str}.jsonl"

    record = {
        "ts": datetime.now(KST).isoformat(),
        "agent": agent,
        "method": method,
        "path": path,
        "status_code": status_code,
        "response_bytes": response_bytes,
        "sandbox_filename": sandbox_filename,
        "author": agent,
        "token_hash": token_hash or "N/A",
        "result": result,
        "reason": reason,
    }
    try:
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logging.error(f"[AUDIT] write failed: {e}")

# ── Fail-Closed 발동 조건 탐지 ────────────────────────────────────────────

FAIL_CLOSED_TRIGGERS = {
    "PATH_OUTSIDE_SANDBOX": "sandbox_escape",
    "SYMLINK_DENIED": "symlink",
    "FORBIDDEN_EXTENSION": "forbidden_write",
    "CROSS_OVERWRITE_DENIED": "cross_overwrite_pattern",
    "TOKEN_AGENT_MISMATCH": "auth_bypass_attempt",
}


def _check_fail_closed_trigger(reason: str) -> Optional[str]:
    for keyword, trigger in FAIL_CLOSED_TRIGGERS.items():
        if keyword in reason:
            return trigger
    return None

# ── Request Handler ────────────────────────────────────────────────────────

class ObservationHandler(BaseHTTPRequestHandler):

    # endpoint → 허용 agent 매트릭스 (GAP-01)
    GET_ENDPOINT_AGENT = {
        "/domi-view/projection":    "domi",
        "/jeni-view/projection":    "jeni",
        "/domi-view/sandbox/index": "domi",
        "/jeni-view/sandbox/index": "jeni",
    }
    POST_ENDPOINT_AGENT = {
        "/domi-view/sandbox": "domi",
        "/jeni-view/sandbox": "jeni",
    }

    def log_message(self, format, *args):
        # nginx가 token masking 담당 — 여기서는 최소 로그
        logging.info(f"[REQUEST] {self.address_string()} {format % args}")

    def _send_json(self, status: int, body: dict):
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Authority", "OBSERVATION_ONLY_NO_EXECUTION")
        self.end_headers()
        self.wfile.write(payload)
        return len(payload)

    def _send_error(self, status: int, reason: str):
        return self._send_json(status, {"error": reason, "execution_allowed": False})

    def _auth(self, required_agent: str) -> tuple[bool, Optional[str], Optional[str]]:
        """
        토큰 인증 공통 처리
        반환: (ok, agent, token_hash)
        """
        token, token_hash = _extract_token(self)
        if not token:
            return False, None, None
        valid, reason = validate_token(required_agent, token)
        if not valid:
            return False, reason, token_hash
        return True, required_agent, token_hash

    # ── GET ────────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Fail-Closed 확인
        if is_observation_locked():
            rb = self._send_error(503, "OBSERVATION_LOCKED")
            _write_audit("unknown", "GET", path, 503, "DENY", "OBSERVATION_LOCKED",
                         response_bytes=rb)
            return

        required_agent = self.GET_ENDPOINT_AGENT.get(path)
        if required_agent is None:
            rb = self._send_error(404, "ENDPOINT_NOT_FOUND")
            return

        ok, agent_or_reason, token_hash = self._auth(required_agent)
        if not ok:
            code = 401 if agent_or_reason in ("TOKEN_REQUIRED", "TOKEN_EXPIRED") else 403
            rb = self._send_error(code, agent_or_reason)
            _write_audit(required_agent, "GET", path, code, "DENY",
                         agent_or_reason, token_hash=token_hash, response_bytes=rb)
            return

        # /projection
        if path.endswith("/projection"):
            projection, is_stale = get_projection()
            if is_stale or check_ttl(projection):
                rb = self._send_json(200, {
                    "stale": True,
                    "message": get_stale_output(),
                    "execution_allowed": False,
                })
                _write_audit(required_agent, "GET", path, 200, "ALLOW",
                             "STALE_PROJECTION", token_hash=token_hash, response_bytes=rb)
            else:
                rb = self._send_json(200, projection)
                _write_audit(required_agent, "GET", path, 200, "ALLOW",
                             token_hash=token_hash, response_bytes=rb)

        # /sandbox/index
        elif path.endswith("/sandbox/index"):
            agent_dir = SANDBOX_ROOT / required_agent / "active"
            if not agent_dir.exists():
                rb = self._send_json(200, {"files": [], "agent": required_agent})
            else:
                files = [str(p.name) for p in agent_dir.rglob("*") if p.is_file()]
                rb_body = {"files": files, "agent": required_agent,
                           "execution_allowed": False}
                rb = self._send_json(200, rb_body)
            _write_audit(required_agent, "GET", path, 200, "ALLOW",
                         token_hash=token_hash, response_bytes=rb)

    # ── POST ───────────────────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Fail-Closed 확인
        if is_observation_locked():
            rb = self._send_error(503, "OBSERVATION_LOCKED")
            _write_audit("unknown", "POST", path, 503, "DENY",
                         "OBSERVATION_LOCKED", response_bytes=rb)
            return

        required_agent = self.POST_ENDPOINT_AGENT.get(path)
        if required_agent is None:
            rb = self._send_error(404, "ENDPOINT_NOT_FOUND")
            return

        ok, agent_or_reason, token_hash = self._auth(required_agent)
        if not ok:
            code = 401 if agent_or_reason in ("TOKEN_REQUIRED", "TOKEN_EXPIRED") else 403
            rb = self._send_error(code, agent_or_reason)
            _write_audit(required_agent, "POST", path, code, "DENY",
                         agent_or_reason, token_hash=token_hash, response_bytes=rb)
            # auth 우회 시도 → Fail-Closed 검토
            trigger = _check_fail_closed_trigger(agent_or_reason or "")
            if trigger:
                engage_fail_closed(f"auth_bypass_attempt: {agent_or_reason}")
            return

        # body 파싱
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 1 * 1024 * 1024:
            rb = self._send_error(413, "REQUEST_TOO_LARGE")
            return
        raw_body = self.rfile.read(content_length)

        try:
            body = json.loads(raw_body.decode("utf-8"))
        except Exception:
            rb = self._send_error(400, "INVALID_JSON_BODY")
            return

        file_name = body.get("filename", "")
        file_content_str = body.get("content", "")
        file_status = body.get("status", "DRAFT")
        safe_pass = bool(body.get("safe_pass", False))
        target_path_str = str(SANDBOX_ROOT / required_agent / "active" / file_name)

        # sandbox_validator 12단계 검증
        result = validate_write(
            request_agent=required_agent,
            target_path_str=target_path_str,
            file_content=file_content_str.encode("utf-8"),
            file_name=file_name,
            file_status=file_status,
            safe_pass_requested=safe_pass,
        )

        if not result.allowed:
            code = result.status_code
            rb = self._send_error(code, result.reason)
            _write_audit(required_agent, "POST", path, code, "DENY",
                         result.reason, sandbox_filename=file_name,
                         token_hash=token_hash, response_bytes=rb)
            # Fail-Closed 트리거 확인
            trigger = _check_fail_closed_trigger(result.reason)
            if trigger:
                engage_fail_closed(f"{trigger}: {result.reason}")
            return

        # 파일 쓰기
        try:
            target_path = Path(target_path_str)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "w", encoding="utf-8") as f:
                f.write(file_content_str)
        except Exception as e:
            rb = self._send_error(500, f"WRITE_FAILED: {e}")
            _write_audit(required_agent, "POST", path, 500, "DENY",
                         str(e), sandbox_filename=file_name,
                         token_hash=token_hash, response_bytes=rb)
            return

        rb = self._send_json(200, {
            "result": "ALLOW",
            "filename": file_name,
            "execution_allowed": False,
        })
        _write_audit(required_agent, "POST", path, 200, "ALLOW",
                     sandbox_filename=file_name, token_hash=token_hash,
                     response_bytes=rb)


# ── Threading HTTP Server ──────────────────────────────────────────────────

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ── 진입점 ────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadedHTTPServer(("127.0.0.1", PORT), ObservationHandler)
    logging.info(f"[OBSERVATION SERVER] listening on 127.0.0.1:{PORT}")
    logging.info("[OBSERVATION SERVER] AUTHORITY=OBSERVATION_ONLY_NO_EXECUTION")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("[OBSERVATION SERVER] shutdown")


if __name__ == "__main__":
    main()

"""
observation_server.py
AIBA Observation Server — Layer 2 (L2-1, L2-10, L2-12)
SSOT: BRIEFING-DOMI-S142-DESIGN-REQUEST-FINAL
IMPL-NOTE-03: active file count stale — S143
IMPL-NOTE-04: Fail-Closed unlock — S143
TOKEN-ISSUANCE: BRIEFING-DOMI-S143-TOKEN-001 — S143

port: 8446
runtime: Python stdlib HTTP server
purpose: OBSERVATION_ONLY + SANDBOX_WRITE_GATE
"""

import json
import os
import secrets
import hashlib
import logging
import threading
import tempfile
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from projection_builder import get_projection, get_stale_output, check_ttl, invalidate_cache
from sandbox_validator import validate_write, SANDBOX_ROOT, ALLOWED_AGENTS

# ── 상수 ───────────────────────────────────────────────────────────────────

PORT = 8446
KST = timezone(timedelta(hours=9))
AUDIT_DIR = Path("/opt/arss/engine/arss-protocol/tools/sandbox/audit")
TOKEN_FILE = Path("/opt/arss/engine/arss-protocol/tools/sandbox/.tokens")

FAIL_CLOSED_STATE_FILE = Path(
    "/opt/arss/engine/arss-protocol/tools/sandbox/audit/observation_fail_closed_state.json"
)
UNLOCK_APPROVAL_PHRASE = "BEO_APPROVE_OBSERVATION_UNLOCK"
TOKEN_REGISTER_APPROVAL_PHRASE = "BEO_APPROVE_TOKEN_REGISTER"
TOKEN_TTL_MAX = 43200  # 12h

# ── Fail-Closed 상태 ───────────────────────────────────────────────────────

_fail_closed_lock = threading.Lock()
_system_state = {
    "observation_locked": False,
    "lock_reason": None,
    "lock_time": None,
    "incident_id": None,
    "locked_by": "system",
    "unlock_required_by": "beo",
}


def _load_fail_closed_state():
    if not FAIL_CLOSED_STATE_FILE.exists():
        return
    try:
        with open(FAIL_CLOSED_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _fail_closed_lock:
            _system_state["observation_locked"] = bool(data.get("observation_locked", False))
            _system_state["lock_reason"] = data.get("reason")
            _system_state["lock_time"] = data.get("locked_at")
            _system_state["incident_id"] = data.get("incident_id")
            _system_state["locked_by"] = data.get("locked_by", "system")
            _system_state["unlock_required_by"] = data.get("unlock_required_by", "beo")
        logging.info(
            f"[FAIL-CLOSED] state loaded: locked={_system_state['observation_locked']}"
        )
    except Exception as e:
        logging.error(f"[FAIL-CLOSED] state file load failed: {e}. Using default (unlocked).")


def _persist_fail_closed_state(locked: bool, reason: Optional[str] = None,
                                incident_id: Optional[str] = None):
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    now_kst = datetime.now(KST).isoformat()
    payload = {
        "observation_locked": locked,
        "locked_at": now_kst if locked else None,
        "reason": reason,
        "incident_id": incident_id,
        "locked_by": "system" if locked else None,
        "unlock_required_by": "beo",
        "updated_at": now_kst,
    }
    try:
        dir_path = FAIL_CLOSED_STATE_FILE.parent
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8",
            dir=dir_path, delete=False, suffix=".tmp"
        ) as tf:
            json.dump(payload, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
            tmp_path = tf.name
        os.replace(tmp_path, FAIL_CLOSED_STATE_FILE)
    except Exception as e:
        logging.error(f"[FAIL-CLOSED] state file persist failed: {e}")


def is_observation_locked() -> bool:
    with _fail_closed_lock:
        return _system_state["observation_locked"]


def engage_fail_closed(reason: str, incident_id: Optional[str] = None):
    with _fail_closed_lock:
        _system_state["observation_locked"] = True
        _system_state["lock_reason"] = reason
        _system_state["lock_time"] = datetime.now(KST).isoformat()
        _system_state["incident_id"] = incident_id
    _persist_fail_closed_state(locked=True, reason=reason, incident_id=incident_id)
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

_token_store: dict = {}
_token_lock = threading.Lock()
_token_file_lock = threading.Lock()


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_prefix(value: str) -> str:
    return _sha256_hex(value)[:16]


# ── TOKEN_FILE persist ─────────────────────────────────────────────────────

def _load_token_file():
    """
    기동 시 .tokens 파일 로드
    revoked=false + expires_at 유효 항목만 _token_store 활성화
    raw token 미저장 — hash만 복원
    """
    if not TOKEN_FILE.exists():
        logging.info("[TOKEN] .tokens file not found. Starting with empty store.")
        return
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now_epoch = datetime.now(KST).timestamp()
        loaded = 0
        with _token_lock:
            for agent, entry in data.items():
                if agent not in ALLOWED_AGENTS:
                    continue
                if entry.get("revoked", True):
                    continue
                expires_at_str = entry.get("expires_at", "")
                try:
                    expires_epoch = datetime.fromisoformat(expires_at_str).timestamp()
                except Exception:
                    continue
                if now_epoch >= expires_epoch:
                    continue
                # hash only 복원 — raw token 복원 불가
                _token_store[agent] = {
                    "hash": entry["token_hash"],
                    "expires_epoch": expires_epoch,
                    "revoked": False,
                }
                loaded += 1
        logging.info(f"[TOKEN] Loaded {loaded} active token(s) from .tokens file.")
    except Exception as e:
        logging.error(f"[TOKEN] .tokens load failed: {e}. Starting with empty store.")


def _persist_token_file():
    """
    _token_store → .tokens 파일 atomic write
    tmpfile은 TOKEN_FILE과 동일 디렉토리(tools/sandbox/) 내 생성 (T-3 TA 반영)
    raw token 저장 금지 — token_hash only
    """
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    now_kst = datetime.now(KST).isoformat()

    with _token_lock:
        payload = {}
        for agent, entry in _token_store.items():
            expires_at = datetime.fromtimestamp(
                entry["expires_epoch"], tz=KST
            ).isoformat()
            payload[agent] = {
                "token_hash": entry["hash"],
                "issued_at": entry.get("issued_at", now_kst),
                "expires_at": expires_at,
                "ttl_seconds": entry.get("ttl_seconds", TOKEN_TTL_MAX),
                "revoked": entry["revoked"],
            }

    try:
        with _token_file_lock:
            # tmpfile: 동일 디렉토리(tools/sandbox/) 내 생성
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8",
                dir=TOKEN_FILE.parent, delete=False, suffix=".tmp"
            ) as tf:
                json.dump(payload, tf, ensure_ascii=False, indent=2)
                tf.flush()
                os.fsync(tf.fileno())
                tmp_path = tf.name
            os.replace(tmp_path, TOKEN_FILE)
            # chmod 600
            os.chmod(TOKEN_FILE, 0o600)
    except Exception as e:
        logging.error(f"[TOKEN] .tokens persist failed: {e}")


def register_token(agent: str, token: str, ttl_seconds: int = TOKEN_TTL_MAX) -> dict:
    """
    토큰 등록 (internal use)
    반환: {"token_hash_prefix": str, "expires_at": str}
    """
    assert agent in ALLOWED_AGENTS
    ttl_seconds = min(ttl_seconds, TOKEN_TTL_MAX)
    token_hash = _sha256_hex(token)
    now_kst = datetime.now(KST)
    expires_epoch = now_kst.timestamp() + ttl_seconds
    expires_at = datetime.fromtimestamp(expires_epoch, tz=KST).isoformat()

    with _token_lock:
        _token_store[agent] = {
            "hash": token_hash,
            "expires_epoch": expires_epoch,
            "revoked": False,
            "issued_at": now_kst.isoformat(),
            "ttl_seconds": ttl_seconds,
        }
    _persist_token_file()
    return {
        "token_hash_prefix": token_hash[:16],
        "expires_at": expires_at,
    }


def revoke_token(agent: str):
    with _token_lock:
        if agent in _token_store:
            _token_store[agent]["revoked"] = True
    _persist_token_file()


def validate_token(agent: str, token: str) -> tuple[bool, str]:
    with _token_lock:
        entry = _token_store.get(agent)
    if entry is None:
        return False, "TOKEN_REQUIRED"
    if entry["revoked"]:
        return False, "TOKEN_REVOKED"
    if _sha256_hex(token) != entry["hash"]:
        return False, "TOKEN_AGENT_MISMATCH"
    if datetime.now(KST).timestamp() > entry["expires_epoch"]:
        return False, "TOKEN_EXPIRED"
    return True, "OK"


def _extract_token(handler: "ObservationHandler") -> tuple[Optional[str], Optional[str]]:
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
    event: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
):
    """append-only JSONL audit (L2-9) — raw token 미기록"""
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
        "token_hash": token_hash or "N/A",  # hash prefix only — raw token 금지
        "result": result,
        "reason": reason,
    }
    if event:
        record["event"] = event
    if ttl_seconds is not None:
        record["ttl_seconds"] = ttl_seconds

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
        token, token_hash = _extract_token(self)
        if not token:
            return False, None, None
        valid, reason = validate_token(required_agent, token)
        if not valid:
            return False, reason, token_hash
        return True, required_agent, token_hash

    def _is_loopback(self) -> bool:
        client_ip = self.client_address[0]
        return client_ip in ("127.0.0.1", "::1")

    def _read_body(self, max_bytes: int = 65536) -> Optional[dict]:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > max_bytes:
            self._send_error(413, "REQUEST_TOO_LARGE")
            return None
        try:
            return json.loads(self.rfile.read(content_length).decode("utf-8"))
        except Exception:
            self._send_error(400, "INVALID_JSON_BODY")
            return None

    # ── GET ────────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if is_observation_locked():
            rb = self._send_error(503, "OBSERVATION_LOCKED")
            _write_audit("unknown", "GET", path, 503, "DENY", "OBSERVATION_LOCKED",
                         response_bytes=rb)
            return

        required_agent = self.GET_ENDPOINT_AGENT.get(path)
        if required_agent is None:
            self._send_error(404, "ENDPOINT_NOT_FOUND")
            return

        ok, agent_or_reason, token_hash = self._auth(required_agent)
        if not ok:
            code = 401 if agent_or_reason in ("TOKEN_REQUIRED", "TOKEN_EXPIRED") else 403
            rb = self._send_error(code, agent_or_reason)
            _write_audit(required_agent, "GET", path, code, "DENY",
                         agent_or_reason, token_hash=token_hash, response_bytes=rb)
            return

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

        elif path.endswith("/sandbox/index"):
            agent_dir = SANDBOX_ROOT / required_agent / "active"
            if not agent_dir.exists():
                rb = self._send_json(200, {"files": [], "agent": required_agent})
            else:
                files = [str(p.name) for p in agent_dir.rglob("*") if p.is_file()]
                rb = self._send_json(200, {
                    "files": files, "agent": required_agent,
                    "execution_allowed": False,
                })
            _write_audit(required_agent, "GET", path, 200, "ALLOW",
                         token_hash=token_hash, response_bytes=rb)

    # ── POST ───────────────────────────────────────────────────────────────

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # internal 라우팅
        if path == "/internal/observation/unlock":
            self._handle_unlock()
            return
        if path == "/internal/token/register":
            self._handle_token_register()
            return

        if is_observation_locked():
            rb = self._send_error(503, "OBSERVATION_LOCKED")
            _write_audit("unknown", "POST", path, 503, "DENY",
                         "OBSERVATION_LOCKED", response_bytes=rb)
            return

        required_agent = self.POST_ENDPOINT_AGENT.get(path)
        if required_agent is None:
            self._send_error(404, "ENDPOINT_NOT_FOUND")
            return

        ok, agent_or_reason, token_hash = self._auth(required_agent)
        if not ok:
            code = 401 if agent_or_reason in ("TOKEN_REQUIRED", "TOKEN_EXPIRED") else 403
            rb = self._send_error(code, agent_or_reason)
            _write_audit(required_agent, "POST", path, code, "DENY",
                         agent_or_reason, token_hash=token_hash, response_bytes=rb)
            trigger = _check_fail_closed_trigger(agent_or_reason or "")
            if trigger:
                engage_fail_closed(f"auth_bypass_attempt: {agent_or_reason}")
            return

        body = self._read_body()
        if body is None:
            return

        file_name = body.get("filename", "")
        file_content_str = body.get("content", "")
        file_status = body.get("status", "DRAFT")
        safe_pass = bool(body.get("safe_pass", False))
        target_path_str = str(SANDBOX_ROOT / required_agent / "active" / file_name)

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
            trigger = _check_fail_closed_trigger(result.reason)
            if trigger:
                engage_fail_closed(f"{trigger}: {result.reason}")
            return

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

    # ── TOKEN REGISTER Handler ─────────────────────────────────────────────

    def _handle_token_register(self):
        """
        POST /internal/token/register
        BEO_ONLY + loopback-only
        raw token 1회 응답 후 서버 복원 불가
        """
        path = "/internal/token/register"

        if not self._is_loopback():
            rb = self._send_error(403, "TOKEN_REGISTER_DENIED: LOOPBACK_ONLY")
            _write_audit("unknown", "POST", path, 403, "DENY",
                         "NON_LOOPBACK_TOKEN_REGISTER", response_bytes=rb,
                         event="TOKEN_REGISTER")
            return

        body = self._read_body()
        if body is None:
            return

        actor = body.get("actor", "")
        approval_phrase = body.get("approval_phrase", "")
        agent = body.get("agent", "")
        ttl_seconds = int(body.get("ttl_seconds", TOKEN_TTL_MAX))

        # 조건 검증
        failures = []
        if actor != "beo":
            failures.append("ACTOR_NOT_BEO")
        if approval_phrase != TOKEN_REGISTER_APPROVAL_PHRASE:
            failures.append("APPROVAL_PHRASE_MISMATCH")
        if agent not in ("domi", "jeni"):
            failures.append(f"INVALID_AGENT: {agent}")
        if ttl_seconds > TOKEN_TTL_MAX:
            failures.append(f"TTL_EXCEEDS_MAX: {ttl_seconds}")

        if failures:
            reason = "TOKEN_REGISTER_DENIED: " + ", ".join(failures)
            rb = self._send_error(403, reason)
            _write_audit("beo", "POST", path, 403, "DENY", reason,
                         response_bytes=rb, event="TOKEN_REGISTER")
            return

        # 기존 토큰 rotation — revoked=true
        is_rotation = False
        with _token_lock:
            if agent in _token_store and not _token_store[agent]["revoked"]:
                _token_store[agent]["revoked"] = True
                is_rotation = True
        if is_rotation:
            _persist_token_file()
            _write_audit("beo", "POST", path, 200, "TOKEN_ROTATE",
                         reason=f"agent={agent}", event="TOKEN_ROTATE",
                         ttl_seconds=ttl_seconds)

        # 신규 토큰 생성 (secrets.token_urlsafe — raw token)
        raw_token = secrets.token_urlsafe(32)
        meta = register_token(agent, raw_token, ttl_seconds)

        event_type = "TOKEN_ROTATE" if is_rotation else "TOKEN_REGISTER"
        _write_audit(
            agent="beo", method="POST", path=path,
            status_code=200, result="SUCCESS",
            reason=f"agent={agent}",
            token_hash=meta["token_hash_prefix"],  # hash prefix only — raw token 미기록
            event=event_type,
            ttl_seconds=ttl_seconds,
        )
        logging.info(
            f"[TOKEN] {event_type}: agent={agent} "
            f"hash_prefix={meta['token_hash_prefix']} expires={meta['expires_at']}"
        )

        # raw token 1회 응답 반환
        rb = self._send_json(200, {
            "ok": True,
            "agent": agent,
            "token": raw_token,          # 1회만 — 이후 서버 복원 불가
            "expires_at": meta["expires_at"],
            "token_hash_prefix": meta["token_hash_prefix"],
            "execution_allowed": False,
        })

    # ── UNLOCK Handler ─────────────────────────────────────────────────────

    def _handle_unlock(self):
        path = "/internal/observation/unlock"

        if not self._is_loopback():
            rb = self._send_error(403, "OBSERVATION_UNLOCK_DENIED: LOOPBACK_ONLY")
            _write_audit("unknown", "POST", path, 403, "DENY",
                         "NON_LOOPBACK_UNLOCK_ATTEMPT", response_bytes=rb)
            return

        body = self._read_body()
        if body is None:
            return

        actor = body.get("actor", "")
        approval_phrase = body.get("approval_phrase", "")
        incident_id = body.get("incident_id", "")
        jeni_trust = body.get("jeni_trust_revalidation", "")
        caddy_report = body.get("caddy_incident_report", "")
        token_rotation = body.get("new_token_rotation", "")

        failures = []
        if actor != "beo":
            failures.append("ACTOR_NOT_BEO")
        if approval_phrase != UNLOCK_APPROVAL_PHRASE:
            failures.append("APPROVAL_PHRASE_MISMATCH")
        if not incident_id:
            failures.append("INCIDENT_ID_MISSING")
        if jeni_trust != "PASS":
            failures.append("JENI_TRUST_REVALIDATION_NOT_PASS")
        if caddy_report != "PRESENT":
            failures.append("CADDY_INCIDENT_REPORT_MISSING")
        if token_rotation != "DONE":
            failures.append("NEW_TOKEN_ROTATION_NOT_DONE")

        if failures:
            reason = "OBSERVATION_UNLOCK_DENIED: " + ", ".join(failures)
            rb = self._send_error(403, reason)
            _write_audit("beo", "POST", path, 403, "DENY", reason, response_bytes=rb)
            return

        with _fail_closed_lock:
            _system_state["observation_locked"] = False
            _system_state["lock_reason"] = None
            _system_state["lock_time"] = None
            _system_state["incident_id"] = None

        _persist_fail_closed_state(locked=False, reason=None, incident_id=incident_id)
        invalidate_cache()

        _write_audit("beo", "POST", path, 200, "OBSERVATION_UNLOCKED",
                     reason=f"incident_id={incident_id}", response_bytes=0)
        logging.info(f"[FAIL-CLOSED] OBSERVATION_UNLOCKED by beo. incident_id={incident_id}")

        rb = self._send_json(200, {
            "result": "OBSERVATION_UNLOCKED",
            "incident_id": incident_id,
            "projection_cache_invalidated": True,
            "execution_allowed": False,
        })


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
    _load_fail_closed_state()
    _load_token_file()

    server = ThreadedHTTPServer(("127.0.0.1", PORT), ObservationHandler)
    logging.info(f"[OBSERVATION SERVER] listening on 127.0.0.1:{PORT}")
    logging.info("[OBSERVATION SERVER] AUTHORITY=OBSERVATION_ONLY_NO_EXECUTION")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("[OBSERVATION SERVER] shutdown")


if __name__ == "__main__":
    main()

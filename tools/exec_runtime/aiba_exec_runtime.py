"""
aiba_exec_runtime.py v1.0.0
AIBA Exec Runtime — exec_scoped 허용 명령 실행 서비스

설계 근거: S196 EAG-1 비오(Joshua) 승인
거버넌스 체인: 도미 Rev.2 설계 → 제니 TRUST_READY PASS → 비오 EAG-1

보안 원칙:
  - 정적 enum 화이트리스트 — 목록 외 명령 즉시 거부 (Fail-Closed)
  - 명령별 고정 파라미터 스키마 — Shell Injection 방어
  - approval_id 필수 — EAG 게이트
  - Audit mandatory (pre/post) — 누락 시 실행 차단
  - actor_id = caddy only
  - subprocess.run(shell=False) — 쉘 인터프리터 우회 불가

포트: 8449
엔드포인트: POST /exec
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any

# ── 상수 ────────────────────────────────────────────────────────────────────

EXEC_RUNTIME_VERSION = "1.0.0"
EXEC_HOST = "127.0.0.1"
EXEC_PORT = 8449

ALLOWED_ACTOR = "caddy"

# 명령별 타임아웃 (초)
COMMAND_TIMEOUTS: dict[str, int] = {
    "pytest": 300,
    "git_commit": 30,
    "git_status": 30,
    "git_diff": 30,
    "systemctl_restart": 30,
}

# systemctl_restart 허용 서비스 화이트리스트 (3종 한정)
ALLOWED_SERVICES = frozenset({
    "aiba-mcp-bridge",
    "aiba-domi-runtime",
    "aiba-jeni-runtime",
})

# pytest 허용 옵션 enum (쉘 인젝션 방어용)
ALLOWED_PYTEST_OPTIONS = frozenset({
    "-v", "--verbose",
    "-s", "--capture=no",
    "-x", "--exitfirst",
    "--tb=short", "--tb=long", "--tb=no",
    "-q", "--quiet",
    "--no-header",
    "-p", "no:warnings",
})

# ARSS 프로젝트 루트 (절대경로 고정)
ARSS_ROOT = "/opt/arss/engine/arss-protocol"

# 감사 로그 경로 (bridge audit_trail 옆에 위치)
AUDIT_LOG_PATH = os.path.join(ARSS_ROOT, "tools/mcp/exec_audit_trail.log")

# ── 로깅 ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[EXEC_RUNTIME] %(asctime)s %(levelname)s %(message)s",
)
_log = logging.getLogger("aiba_exec_runtime")


# ── Audit ────────────────────────────────────────────────────────────────────

def _write_audit(
    *,
    audit_id: str,
    stage: str,
    command: str,
    actor_id: str,
    approval_id: str,
    detail: str,
    exit_code: int | None = None,
) -> bool:
    """
    감사 로그 기록. 실패 시 False 반환 → 호출자가 실행 차단.
    stage: "PRE" | "POST_OK" | "POST_FAIL" | "DENY"
    """
    entry = {
        "audit_id": audit_id,
        "stage": stage,
        "command": command,
        "actor_id": actor_id,
        "approval_id": approval_id,
        "detail": detail,
        "exit_code": exit_code,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "version": EXEC_RUNTIME_VERSION,
    }
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        _log.error("AUDIT WRITE FAILED: %s", e)
        return False


# ── 파라미터 검증 ─────────────────────────────────────────────────────────────

def _validate_and_build_cmd(command: str, params: dict) -> tuple[bool, str, list[str]]:
    """
    화이트리스트 검증 + subprocess 인자 리스트 생성.
    Returns: (ok, error_reason, cmd_list)
    shell=False이므로 cmd_list는 문자열 토큰 리스트.
    """
    if command == "pytest":
        path = params.get("path", "")
        options: list = params.get("options", [])

        if not path:
            return False, "pytest: path required", []

        # path: ARSS_ROOT 이하만 허용 (경로 탈출 방어)
        real_path = os.path.realpath(os.path.abspath(path))
        real_root = os.path.realpath(ARSS_ROOT)
        if not (real_path == real_root or real_path.startswith(real_root + os.sep)):
            return False, f"pytest: path '{real_path}' outside ARSS_ROOT", []

        # options: enum 검증
        if not isinstance(options, list):
            return False, "pytest: options must be list", []
        for opt in options:
            if opt not in ALLOWED_PYTEST_OPTIONS:
                return False, f"pytest: option '{opt}' not in allowlist", []

        cmd = ["python3", "-m", "pytest", real_path] + list(options)
        return True, "", cmd

    if command == "git_commit":
        message = params.get("message", "")
        files: list = params.get("files", [])

        if not message:
            return False, "git_commit: message required", []
        if not isinstance(files, list) or not files:
            return False, "git_commit: files must be non-empty list", []

        # 각 파일 경로: ARSS_ROOT 이하만 허용
        real_root = os.path.realpath(ARSS_ROOT)
        validated_files = []
        for f in files:
            real_f = os.path.realpath(os.path.abspath(
                os.path.join(ARSS_ROOT, f) if not os.path.isabs(f) else f
            ))
            if not (real_f == real_root or real_f.startswith(real_root + os.sep)):
                return False, f"git_commit: file '{real_f}' outside ARSS_ROOT", []
            validated_files.append(real_f)

        # git add + git commit 순차 실행은 런타임에서 처리
        # 여기서는 add용 파일 목록 + commit 메시지 반환
        cmd = ["__GIT_COMMIT__", message] + validated_files
        return True, "", cmd

    if command == "git_status":
        cmd = ["git", "-C", ARSS_ROOT, "status"]
        return True, "", cmd

    if command == "git_diff":
        cmd = ["git", "-C", ARSS_ROOT, "diff"]
        return True, "", cmd

    if command == "systemctl_restart":
        service = params.get("service", "")
        if not service:
            return False, "systemctl_restart: service required", []
        if service not in ALLOWED_SERVICES:
            return False, f"systemctl_restart: service '{service}' not in allowlist", []
        cmd = ["systemctl", "restart", service]
        return True, "", cmd

    return False, f"command '{command}' not in whitelist", []


# ── 명령 실행 ─────────────────────────────────────────────────────────────────

def _run_command(command: str, cmd_list: list[str], timeout: int) -> dict:
    """
    subprocess.run(shell=False)으로 안전하게 실행.
    git_commit은 add → commit 2단계 처리.
    """
    try:
        if command == "git_commit":
            # __GIT_COMMIT__ 마커: 인덱스[1]=message, 인덱스[2:]=files
            message = cmd_list[1]
            files = cmd_list[2:]

            # Step 1: git add (지정 파일만)
            add_result = subprocess.run(
                ["git", "-C", ARSS_ROOT, "add"] + files,
                capture_output=True, text=True, timeout=30, shell=False,
            )
            if add_result.returncode != 0:
                return {
                    "stdout": add_result.stdout,
                    "stderr": f"[git add FAILED]\n{add_result.stderr}",
                    "exit_code": add_result.returncode,
                }

            # Step 2: git commit -m
            commit_result = subprocess.run(
                ["git", "-C", ARSS_ROOT, "commit", "-m", message],
                capture_output=True, text=True, timeout=30, shell=False,
            )
            combined_stdout = f"[git add OK]\n{add_result.stdout}\n[git commit]\n{commit_result.stdout}"
            return {
                "stdout": combined_stdout,
                "stderr": commit_result.stderr,
                "exit_code": commit_result.returncode,
            }

        result = subprocess.run(
            cmd_list,
            capture_output=True, text=True,
            timeout=timeout, shell=False,
            cwd=ARSS_ROOT,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": f"TIMEOUT: command '{command}' exceeded {timeout}s",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"EXEC_ERROR: {e}",
            "exit_code": -2,
        }


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class ExecHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass  # RULE-6: 불필요한 stdout 억제

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "version": EXEC_RUNTIME_VERSION, "port": EXEC_PORT})
            return
        self._send_json(403, {"error": "forbidden"})

    def do_POST(self):
        if self.path != "/exec":
            self._send_json(404, {"error": "not_found"})
            return

        # ── 요청 파싱 ────────────────────────────────────────────────────────
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body: dict[str, Any] = json.loads(raw_body)
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return

        command = body.get("command", "")
        params = body.get("params", {})
        approval_id = body.get("approval_id", "")
        actor_id = body.get("actor_id", "")
        audit_id = str(uuid.uuid4())

        # ── Gate 1: actor 검증 ───────────────────────────────────────────────
        if actor_id != ALLOWED_ACTOR:
            _write_audit(
                audit_id=audit_id, stage="DENY", command=command,
                actor_id=actor_id, approval_id=approval_id,
                detail=f"actor '{actor_id}' not allowed",
            )
            self._send_json(403, {"ok": False, "error": f"DENY: actor must be '{ALLOWED_ACTOR}'"})
            return

        # ── Gate 2: approval_id 검증 ─────────────────────────────────────────
        if not approval_id:
            _write_audit(
                audit_id=audit_id, stage="DENY", command=command,
                actor_id=actor_id, approval_id="",
                detail="approval_id missing",
            )
            self._send_json(403, {"ok": False, "error": "DENY: approval_id required"})
            return

        # ── Gate 3: 파라미터 검증 + cmd 빌드 ─────────────────────────────────
        ok, reason, cmd_list = _validate_and_build_cmd(command, params)
        if not ok:
            _write_audit(
                audit_id=audit_id, stage="DENY", command=command,
                actor_id=actor_id, approval_id=approval_id,
                detail=reason,
            )
            self._send_json(400, {"ok": False, "error": f"DENY: {reason}"})
            return

        # ── Gate 4: audit PRE mandatory ──────────────────────────────────────
        pre_ok = _write_audit(
            audit_id=audit_id, stage="PRE", command=command,
            actor_id=actor_id, approval_id=approval_id,
            detail=f"cmd_list={cmd_list[:3]}...",
        )
        if not pre_ok:
            self._send_json(500, {"ok": False, "error": "FAIL_CLOSED: audit pre-record failed"})
            return

        # ── 명령 실행 ─────────────────────────────────────────────────────────
        timeout = COMMAND_TIMEOUTS.get(command, 30)
        _log.info("EXEC command=%s approval_id=%s audit_id=%s", command, approval_id, audit_id)
        exec_result = _run_command(command, cmd_list, timeout)

        success = exec_result["exit_code"] == 0

        # ── Gate 5: audit POST mandatory ─────────────────────────────────────
        post_stage = "POST_OK" if success else "POST_FAIL"
        post_ok = _write_audit(
            audit_id=audit_id, stage=post_stage, command=command,
            actor_id=actor_id, approval_id=approval_id,
            detail=f"exit_code={exec_result['exit_code']}",
            exit_code=exec_result["exit_code"],
        )
        if not post_ok:
            self._send_json(500, {"ok": False, "error": "FAIL_CLOSED: audit post-record failed"})
            return

        # ── 응답 ─────────────────────────────────────────────────────────────
        self._send_json(200, {
            "ok": success,
            "command": command,
            "stdout": exec_result["stdout"],
            "stderr": exec_result["stderr"],
            "exit_code": exec_result["exit_code"],
            "audit_id": audit_id,
            "approval_id": approval_id,
        })


class ThreadedExecServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    import signal

    def _handle_shutdown(signum, frame):
        _log.info("EXEC_RUNTIME shutdown signal received")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    _log.info("aiba-exec-runtime v%s starting on %s:%d", EXEC_RUNTIME_VERSION, EXEC_HOST, EXEC_PORT)
    server = ThreadedExecServer((EXEC_HOST, EXEC_PORT), ExecHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

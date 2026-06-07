"""
aiba_exec_runtime.py v1.3.0
AIBA Exec Runtime — exec_scoped 허용 명령 실행 서비스

변경 이력:
  v1.1.0 (S197): EAG-1 승인 (비오(Joshua)) — Rev.2 C-5
                 session_audit_id 수신 및 audit log 기록 추가
                 audit entry에 session_audit_id 필드 포함 (optional)
                 backward compatible — session_audit_id 없으면 기존 동작 유지

  v1.2.0 (S198): EAG-3 승인 (비오(Joshua))
                 pytest 분기 ENV=test 자동 주입

  v1.3.0 (S200): EAG 승인 (비오(Joshua))
                 git_push 명령어 추가.
                 remote={"origin"}, branch={"main"} allowlist 고정 (Fail-Closed).
                 dry_run bool 파라미터 추가 — git push --dry-run 검증 경로 제공.
                 error_type 구조화 응답 추가:
                   NON_FAST_FORWARD, REMOTE_REJECTED, AUTH_FAILED,
                   NETWORK_ERROR, UNKNOWN_FAILURE, None.
                 audit PRE/POST detail에 remote/branch/dry_run 포함.
                 shell=False, approval_id 필수, Fail-Closed 원칙 유지.

설계 근거: S200 비오(Joshua) 직접 설계 제공 + Jeni TRUST_READY PASS
거버넌스 체인: 비오 설계 → 캐디 IMPLEMENTABLE 검토 → 제니 TRUST_READY PASS → 비오 EAG

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

EXEC_RUNTIME_VERSION = "1.4.0"
EXEC_HOST = "127.0.0.1"
EXEC_PORT = 8449

ALLOWED_ACTOR = "caddy"

# 명령별 타임아웃 (초)
COMMAND_TIMEOUTS: dict[str, int] = {
    "pytest": 300,
    "git_commit": 30,
    "git_status": 30,
    "git_diff": 30,
    "git_push": 120,
    "systemctl_restart": 30,
    "write_script": 10,
    "run_script": 120,
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

# git_push allowlist (Fail-Closed)
ALLOWED_GIT_REMOTES = frozenset({"origin"})
ALLOWED_GIT_BRANCHES = frozenset({"main"})

# ARSS 프로젝트 루트 (절대경로 고정)
ARSS_ROOT = "/opt/arss/engine/arss-protocol"

# 감사 로그 경로 (bridge audit_trail 옆에 위치)
AUDIT_LOG_PATH = os.path.join(ARSS_ROOT, "tools/mcp/exec_audit_trail.log")

# caddy sandbox 경로 (write_script / run_script 전용, S201 EAG-B 위치 수정)
CADDY_SANDBOX = os.path.join(ARSS_ROOT, "tools/sandbox/caddy/active")

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
    session_audit_id: str | None = None,
) -> bool:
    """
    감사 로그 기록. 실패 시 False 반환 → 호출자가 실행 차단.
    stage: "PRE" | "POST_OK" | "POST_FAIL" | "DENY"
    session_audit_id: bridge에서 발행한 병렬 묶음 ID (optional, v1.1.0)
    """
    entry: dict = {
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
    # session_audit_id는 있을 때만 포함 (backward compatible)
    if session_audit_id:
        entry["session_audit_id"] = session_audit_id

    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        _log.error("AUDIT WRITE FAILED: %s", e)
        return False


# ── 파라미터 검증 ─────────────────────────────────────────────────────────────

def _validate_and_build_cmd(command: str, params: dict) -> tuple[bool, str, list | dict]:
    """
    화이트리스트 검증 + subprocess 인자 리스트(또는 spec dict) 생성.
    Returns: (ok, error_reason, cmd_list_or_spec)
    shell=False이므로 cmd_list는 문자열 토큰 리스트.
    git_push의 경우 cmd_list 자리에 push_spec dict 반환.
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

        cmd = ["__GIT_COMMIT__", message] + validated_files
        return True, "", cmd

    if command == "git_status":
        cmd = ["git", "-C", ARSS_ROOT, "status"]
        return True, "", cmd

    if command == "git_diff":
        cmd = ["git", "-C", ARSS_ROOT, "diff"]
        return True, "", cmd

    if command == "git_push":
        remote = params.get("remote", "origin")
        branch = params.get("branch", "main")
        dry_run = params.get("dry_run", False)

        if not isinstance(remote, str) or remote not in ALLOWED_GIT_REMOTES:
            return False, f"git_push denied: remote not allowed: {remote!r}", {}

        if not isinstance(branch, str) or branch not in ALLOWED_GIT_BRANCHES:
            return False, f"git_push denied: branch not allowed: {branch!r}", {}

        if not isinstance(dry_run, bool):
            return False, "git_push denied: dry_run must be boolean", {}

        push_spec = {
            "command": "git_push",
            "remote": remote,
            "branch": branch,
            "dry_run": dry_run,
            "timeout": COMMAND_TIMEOUTS["git_push"],
            "audit_detail": {
                "command": "git_push",
                "remote": remote,
                "branch": branch,
                "dry_run": dry_run,
            },
        }
        return True, "", push_spec

    if command == "systemctl_restart":
        service = params.get("service", "")
        if not service:
            return False, "systemctl_restart: service required", []
        if service not in ALLOWED_SERVICES:
            return False, f"systemctl_restart: service '{service}' not in allowlist", []
        cmd = ["systemctl", "restart", service]
        return True, "", cmd

    if command == "write_script":
        filename = params.get("filename", "")
        script_content = params.get("content", "")

        if not filename:
            return False, "write_script: filename required", []
        if not filename.endswith(".py"):
            return False, f"write_script: filename must end with .py: {filename!r}", []
        if "/" in filename or "\\" in filename:
            return False, f"write_script: path separator not allowed in filename: {filename!r}", []
        if not script_content:
            return False, "write_script: content required", []

        os.makedirs(CADDY_SANDBOX, exist_ok=True)
        target = os.path.realpath(os.path.join(CADDY_SANDBOX, filename))
        real_sandbox = os.path.realpath(CADDY_SANDBOX)
        if not (target == real_sandbox or target.startswith(real_sandbox + os.sep)):
            return False, f"write_script: path escape detected: {target!r}", []

        spec = {"command": "write_script", "target": target, "content": script_content}
        return True, "", spec

    if command == "run_script":
        script_path = params.get("script_path", "")

        if not script_path:
            return False, "run_script: script_path required", []
        if not script_path.endswith(".py"):
            return False, f"run_script: script_path must end with .py: {script_path!r}", []

        real_script = os.path.realpath(os.path.abspath(script_path))
        real_sandbox = os.path.realpath(CADDY_SANDBOX)
        if not (real_script == real_sandbox or real_script.startswith(real_sandbox + os.sep)):
            return False, f"run_script: path outside caddy sandbox: {real_script!r}", []
        if not os.path.isfile(real_script):
            return False, f"run_script: script not found: {real_script!r}", []

        cmd = ["python3", real_script]
        return True, "", cmd

    return False, f"command '{command}' not in whitelist", []


# ── 명령 실행 ─────────────────────────────────────────────────────────────────

def _run_command(command: str, cmd_list: list | dict, timeout: int) -> dict:
    """
    subprocess.run(shell=False)으로 안전하게 실행.
    git_commit은 add → commit 2단계 처리.
    git_push는 push_spec dict를 수신하여 처리.
    """
    try:
        if command == "git_commit":
            message = cmd_list[1]
            files = cmd_list[2:]

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

        if command == "write_script":
            spec = cmd_list  # write_script spec dict
            try:
                with open(spec["target"], "w", encoding="utf-8") as f:
                    f.write(spec["content"])
                return {
                    "stdout": f"WRITE_OK: {spec['target']}",
                    "stderr": "",
                    "exit_code": 0,
                    "written_path": spec["target"],
                }
            except Exception as e:
                return {"stdout": "", "stderr": f"WRITE_ERROR: {e}", "exit_code": -1}

        if command == "git_push":
            push_spec = cmd_list  # push_spec dict
            remote = push_spec["remote"]
            branch = push_spec["branch"]
            dry_run = push_spec.get("dry_run", False)
            push_timeout = push_spec.get("timeout", COMMAND_TIMEOUTS["git_push"])

            git_cmd = ["git", "-C", ARSS_ROOT, "push"]
            if dry_run:
                git_cmd.append("--dry-run")
            git_cmd.extend([remote, branch])

            result = subprocess.run(
                git_cmd,
                capture_output=True,
                text=True,
                timeout=push_timeout,
                shell=False,
            )

            stderr = result.stderr or ""
            exit_code = result.returncode

            if exit_code == 0:
                error_type = None
            elif "[non-fast-forward]" in stderr:
                error_type = "NON_FAST_FORWARD"
            elif "[rejected]" in stderr:
                error_type = "REMOTE_REJECTED"
            elif "Authentication failed" in stderr:
                error_type = "AUTH_FAILED"
            elif "Could not read" in stderr or "Connection" in stderr:
                error_type = "NETWORK_ERROR"
            else:
                error_type = "UNKNOWN_FAILURE"

            return {
                "stdout": result.stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "error_type": error_type,
                "dry_run": dry_run,
                "remote": remote,
                "branch": branch,
            }

        _pytest_env = {**os.environ, "ENV": "test"}
        result = subprocess.run(
            cmd_list,
            capture_output=True, text=True,
            timeout=timeout, shell=False,
            cwd=ARSS_ROOT,
            env=_pytest_env,
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
        # v1.1.0: session_audit_id 수신 (optional — backward compatible)
        session_audit_id: str | None = body.get("session_audit_id") or None
        audit_id = str(uuid.uuid4())

        # ── Gate 1: actor 검증 ───────────────────────────────────────────────
        if actor_id != ALLOWED_ACTOR:
            _write_audit(
                audit_id=audit_id, stage="DENY", command=command,
                actor_id=actor_id, approval_id=approval_id,
                detail=f"actor '{actor_id}' not allowed",
                session_audit_id=session_audit_id,
            )
            self._send_json(403, {"ok": False, "error": f"DENY: actor must be '{ALLOWED_ACTOR}'"})
            return

        # ── Gate 2: approval_id 검증 ─────────────────────────────────────────
        if not approval_id:
            _write_audit(
                audit_id=audit_id, stage="DENY", command=command,
                actor_id=actor_id, approval_id="",
                detail="approval_id missing",
                session_audit_id=session_audit_id,
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
                session_audit_id=session_audit_id,
            )
            self._send_json(400, {"ok": False, "error": f"DENY: {reason}"})
            return

        # ── Gate 4: audit PRE mandatory ──────────────────────────────────────
        # git_push는 audit_detail dict를 JSON 직렬화하여 detail로 전달
        if command == "git_push":
            pre_detail = json.dumps(cmd_list["audit_detail"], ensure_ascii=False)
        elif isinstance(cmd_list, dict):
            pre_detail = f"cmd_list={str(cmd_list)[:100]}"
        else:
            pre_detail = f"cmd_list={cmd_list[:3]}..."

        pre_ok = _write_audit(
            audit_id=audit_id, stage="PRE", command=command,
            actor_id=actor_id, approval_id=approval_id,
            detail=pre_detail,
            session_audit_id=session_audit_id,
        )
        if not pre_ok:
            self._send_json(500, {"ok": False, "error": "FAIL_CLOSED: audit pre-record failed"})
            return

        # ── 명령 실행 ─────────────────────────────────────────────────────────
        timeout = COMMAND_TIMEOUTS.get(command, 30)
        _log.info(
            "EXEC command=%s approval_id=%s audit_id=%s session_audit_id=%s",
            command, approval_id, audit_id, session_audit_id or "none",
        )
        exec_result = _run_command(command, cmd_list, timeout)

        success = exec_result["exit_code"] == 0

        # ── Gate 5: audit POST mandatory ─────────────────────────────────────
        post_stage = "POST_OK" if success else "POST_FAIL"
        post_detail = f"exit_code={exec_result['exit_code']}"
        if command == "git_push":
            post_detail += f" error_type={exec_result.get('error_type')} dry_run={exec_result.get('dry_run')}"

        post_ok = _write_audit(
            audit_id=audit_id, stage=post_stage, command=command,
            actor_id=actor_id, approval_id=approval_id,
            detail=post_detail,
            exit_code=exec_result["exit_code"],
            session_audit_id=session_audit_id,
        )
        if not post_ok:
            self._send_json(500, {"ok": False, "error": "FAIL_CLOSED: audit post-record failed"})
            return

        # ── 응답 ─────────────────────────────────────────────────────────────
        response: dict = {
            "ok": success,
            "command": command,
            "stdout": exec_result["stdout"],
            "stderr": exec_result["stderr"],
            "exit_code": exec_result["exit_code"],
            "audit_id": audit_id,
            "approval_id": approval_id,
        }
        # write_script 전용 응답 필드 추가
        if command == "write_script":
            response["written_path"] = exec_result.get("written_path")

        # git_push 전용 응답 필드 추가
        if command == "git_push":
            response["error_type"] = exec_result.get("error_type")
            response["dry_run"] = exec_result.get("dry_run")
            response["remote"] = exec_result.get("remote")
            response["branch"] = exec_result.get("branch")

        if session_audit_id:
            response["session_audit_id"] = session_audit_id

        self._send_json(200, response)


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

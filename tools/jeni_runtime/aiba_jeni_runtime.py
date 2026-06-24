"""
aiba_jeni_runtime.py v4.1.0
AIBA Jeni Runtime — Persistent Autonomous Verification Agent
PT-S193-JENI-PERSIST-001

변경 내역:
  v1.0.0 (S189): FORWARD_ONLY 단일 호출
  v2.0.0 (S191): Independent Verification Loop (텍스트 TRIGGER 기반)
  v3.0.0 (S193): Multi-Turn Tool Loop ([JENI_TOOL_REQUEST] 텍스트 파싱)
  v4.0.0 (S193): Persistent Autonomous Agent 전면 재설계
    - 도미 Rev.3 (BRIEFING-DOMI-S193-002 Final) + 제니 TRUST_READY PASS
    - 문제 1: WRITE_SCOPE = SANDBOX_ONLY (tools/sandbox/jeni/** 한정)
    - 문제 2: Persistent Memory Layer (conversation/findings/audits/state)
    - 문제 3: STATE_6 PERSIST_RESULTS — 응답 후 sandbox 자동 기록
    - 문제 4: Memory Injection — _load_memory_context()
    - 문제 5: Gemini Function Calling API 전환
    - 제니 제언 1: Memory Pruning — RESOLVED/CLOSED findings 주입 제외
    - 제니 제언 2: Quota Lock — sandbox 50MB 초과 시 오래된 audits 롤링 삭제
  v4.1.0 (S199): Gemini 503 자동 재시도 1회 추가
  v4.4.0 (S211): NO_PARTS Exponential Backoff 재시도 3회 추가 (EAG-S211-JENI-001)
    - _parse_response() 헬퍼 신설 — NO_PARTS 2s/4s/8s backoff
    - 503/429 재시도 성공 경로도 _parse_response() 적용 (중복 제거)
    - 매 재시도마다 Request 재생성 (body stream 소진 방지)
    - _execute_gemini_request: HTTP 503 감지 시 2초 대기 후 1회 재시도
    - 재시도 후 503 지속 시 즉시 FAIL_CLOSED
    - S199 EAG-2: 비오(Joshua) 승인
  v4.7.0 (S277): write_file + COLLAB_DIR 추가 (EAG-S277-DOMI-JENI-WRITE-001)
  v4.8.0 (S278): SC_FINAL 자동 로드 + JENI_SESSION_BOOT_PROTOCOL 주입
  v4.9.0 (S279): /observe 엔드포인트 추가 (EAG-S279-OBSERVE-001)
    - POST /observe: targets 지정 시 Runtime이 ALLOWED_TOOLS 자율 호출 후 결과 반환
    - targets: session_context / runtime_snapshot / service_status
    - EAG-S278-AGENT-BOOT-001
    - _load_session_context(): POINTER → SC_FINAL 자동 로드 (TTL=프로세스 수명)
    - 로드 실패 시 FAIL_CLOSED (context empty, 경고 로그)
    - /health 응답에 sc_context_loaded 필드 추가
  설계 근거: BRIEFING-DOMI-S193-002 Final / S199 Domi 설계
  EAG-1: 비오(Joshua) S193 승인
  Jeni TRUST_READY: PASS (BRIEFING-JENI-S193-003)
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8447
RUNTIME_VERSION = "4.10.0"

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("AIBA_GEMINI_MODEL", "gemini-2.0-flash")
GEMINI_MODEL_ESCALATE = os.environ.get("AIBA_GEMINI_MODEL_ESCALATE", "gemini-2.5-pro")
GEMINI_TIMEOUT = 55
GEMINI_MAX_OUTPUT_TOKENS = 4096

GEMINI_API_KEY = os.environ.get("AIBA_GEMINI_API_KEY", "")

GEMINI_503_RETRY_SLEEP = 2  # 503 재시도 대기 시간(초)
GEMINI_429_RETRY_MAX_SLEEP = 60  # 429 Retry-After 상한(초)

NO_PARTS_RETRY_MAX = 3          # NO_PARTS 재시도 최대 횟수 (EAG-S211-JENI-001)
NO_PARTS_RETRY_BASE_SLEEP = 2   # NO_PARTS 기반 대기 시간(초) — 2s/4s/8s

HTTP_RETRY_MAX = 3              # 503/429 재시도 최대 횟수 (EAG-S284-JENI-RETRY-001)
HTTP_RETRY_BASE_SLEEP = 2       # 503/429 기반 대기 시간(초) — 2s/4s/8s

MAX_TOOL_ROUNDS = 5
MAX_TOTAL_SECONDS = 120
TIMEOUT_PREEMPT_SECONDS = 110

BRIDGE_BASE = "http://127.0.0.1:8443"
BRIDGE_TOKEN_ENDPOINT = f"{BRIDGE_BASE}/token"
BRIDGE_TOKEN_TTL = 3600
BRIDGE_TIMEOUT = 15

JENI_CLIENT_ID = os.environ.get("AIBA_JENI_CLIENT_ID", "")
JENI_CLIENT_SECRET = os.environ.get("AIBA_JENI_CLIENT_SECRET", "")

ARSS_ROOT = "/opt/arss/engine/arss-protocol"

BOOT_PROTOCOL_PATH = os.path.join(
    ARSS_ROOT, "tools/design/JENI_SESSION_BOOT_PROTOCOL.md")
SESSION_POINTER_PATH = os.path.join(ARSS_ROOT, "SESSION_CONTEXT_POINTER.json")

# ── Session Context Auto-Load (EAG-S278-AGENT-BOOT-001) ──────────────────────

_sc_cache: dict = {"content": None, "loaded": False}


def _load_session_context() -> str:
    """
    SESSION_CONTEXT_POINTER.json → SC_FINAL 자동 로드.
    TTL = 프로세스 수명 (세션 내 SC_FINAL 불변 보장).
    로드 실패 시 FAIL_CLOSED: 빈 문자열 반환 + 경고 로그.
    """
    if _sc_cache["loaded"]:
        return _sc_cache["content"] or ""
    try:
        # STEP 1: POINTER 읽기
        with open(SESSION_POINTER_PATH, encoding="utf-8") as f:
            pointer = json.load(f)
        last_session = pointer.get("last_session") or pointer.get("current_session")
        if last_session is None:
            raise ValueError("POINTER: last_session 키 없음")
        # STEP 2: SC_FINAL 읽기
        sc_path = os.path.join(
            ARSS_ROOT, f"SESSION_CONTEXT_S{last_session}_FINAL.json")
        with open(sc_path, encoding="utf-8") as f:
            sc_data = json.load(f)
        # STEP 3: 직렬화 (필요 키만)
        summary_keys = [
            "session_count", "chain", "next_steps", "agent_focus",
            "pytest_status", "session_reentry",
        ]
        sc_summary = {k: sc_data[k] for k in summary_keys if k in sc_data}
        sc_text = json.dumps(sc_summary, ensure_ascii=False, indent=2)
        # STEP 4: BOOT_PROTOCOL 읽기 (선택적)
        boot_text = ""
        try:
            with open(BOOT_PROTOCOL_PATH, encoding="utf-8") as f:
                boot_text = f.read()
        except Exception:
            pass  # 문서 없어도 SC_FINAL 로드는 유효
        content = (
            "[JENI SESSION BOOT — SC_FINAL 자동 로드]\n"
            f"{sc_text}\n\n"
        )
        if boot_text:
            content += f"[JENI SESSION BOOT PROTOCOL]\n{boot_text}\n\n"
        _sc_cache["content"] = content
        _sc_cache["loaded"] = True
        print(
            f"[JENI_RUNTIME] SC_FINAL loaded: session={last_session} "
            f"chain_tip={sc_data.get('chain', {}).get('tip', 'unknown')}",
            file=sys.stderr)
        return content
    except Exception as e:
        _sc_cache["loaded"] = True  # 재시도 방지
        _sc_cache["content"] = ""
        print(f"[JENI_RUNTIME] WARN: SC_FINAL load FAILED — {e} (FAIL_CLOSED: context empty)",
              file=sys.stderr)
        return ""


# WRITE_SCOPE = SANDBOX_ONLY (문제 1)
SANDBOX_ROOT = os.path.join(ARSS_ROOT, "tools/sandbox/jeni")
SANDBOX_ACTIVE = os.path.join(SANDBOX_ROOT, "active")
MEM_CONVERSATION_DIR = os.path.join(SANDBOX_ACTIVE, "conversation")
MEM_FINDINGS_DIR = os.path.join(SANDBOX_ACTIVE, "findings")
MEM_AUDITS_DIR = os.path.join(SANDBOX_ACTIVE, "audits")
MEM_STATE_DIR = os.path.join(SANDBOX_ACTIVE, "state")
MEM_STATE_FILE = os.path.join(MEM_STATE_DIR, "runtime_state.json")

MAX_MEMORY_TURNS = 20
MAX_FINDINGS_INJECT = 10
MAX_AUDITS_INJECT = 5

SANDBOX_QUOTA_BYTES = 50 * 1024 * 1024  # 50MB

COLLAB_DIR = os.path.join(ARSS_ROOT, "tools/sandbox/common/collab")

ALLOWED_TOOLS = frozenset({
    "read_file", "list_dir", "grep_scoped", "read_log", "get_runtime_snapshot",
    "write_file",
})

JENI_SYSTEM_INSTRUCTION = (
    "당신은 AIBA 프로젝트의 거버넌스 감사자(Governance Auditor) '제니(Jeni)'입니다. "
    "역할: Fail-Closed 검증, Rule 위반 탐지, 설계 감사, 증거 검증. "
    "비오(Joshua)에게는 한국어 경어를 사용합니다. "
    "당신은 검증과 감사만 수행하며, 설계 권한이나 EAG 승인 권한은 없습니다. "
    "근거 없는 단정을 피하고, 증거에 기반하여 판단합니다.\n\n"
    "[VPS 독립 검증 의무 — 검증 전 반드시 이행]\n"
    "1. 검증 대상 파일을 read_file 로 직접 읽는다. "
    "list_dir 만으로 판단를 시작하는 것은 금지된다.\n"
    "2. 코드 변경 검증 시 grep_scoped 로 실제 코드 패턴을 확인한다.\n"
    "3. 검증 없이 철학적 원칙만으로 TRUST_NOT_READY 판정 금지. "
    "반드시 실측 근거를 명시한다.\n"
    "4. TRUST_NOT_READY 판정 시 반드시 구체적 가드레일 위반 항목을 명시한다. "
    "미명시 시 TRUST_ADVISORY 로 자동 강등(실투 효력 없음).\n"
    "5. 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용된다.\n\n"
    "증거 수준: RAW(직접 읽음) / INFERRED(추측) / REPORTED(전달받음)\n\n"
    "이전 세션의 검증 이력(findings, audits, runtime_state)이 제공되면 "
    "맥락 연속성을 위해 참고하되, 이미 RESOLVED/CLOSED 처리된 항목이 "
    "현재의 독립적 판단을 편향시키지 않도록 주의하십시오."
)


def _build_function_declarations() -> list:
    return [
        {"name": "read_file",
         "description": "VPS 단일 파일 읽기. 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용.",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "읽을 파일의 절대 경로"}},
             "required": ["path"]}},
        {"name": "list_dir",
         "description": "VPS 디렉토리 목록 조회 (depth=1).",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "조회할 디렉토리 절대 경로"}},
             "required": ["path"]}},
        {"name": "grep_scoped",
         "description": "허용 경로 내 텍스트 검색.",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "검색 대상 경로"},
             "pattern": {"type": "string", "description": "검색 패턴"}},
             "required": ["path", "pattern"]}},
        {"name": "read_log",
         "description": "로그 파일 tail 읽기 (최대 200줄).",
         "parameters": {"type": "object", "properties": {
             "path": {"type": "string", "description": "로그 파일 경로"},
             "tail_lines": {"type": "integer", "description": "읽을 줄 수"}},
             "required": ["path"]}},
        {"name": "get_runtime_snapshot",
         "description": "사전 정의된 read-only 런타임 스냅샷 조회. 파라미터 불필요.",
         "parameters": {"type": "object", "properties": {}}},
        {"name": "write_file",
         "description": "VPS 파일 쓰기. 허용 경로: tools/sandbox/jeni/** 또는 tools/sandbox/common/collab/**. 에이전트 간 토론 결과를 collab/에 기록할 때 사용.",
         "parameters": {"type": "object", "properties": {
             "target_path": {"type": "string", "description": "쓸 파일의 절대 경로"},
             "content": {"type": "string", "description": "파일 내용"}},
             "required": ["target_path", "content"]}},
    ]


def _mask_key(key: str) -> str:
    if not key:
        return "<EMPTY>"
    if len(key) <= 6:
        return "***"
    return key[:6] + "***"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_finish_reason(data: dict) -> str:
    candidates = data.get("candidates", [])
    if not candidates:
        return "NO_CANDIDATES"
    return candidates[0].get("finishReason", "UNKNOWN")


def _extract_parts(data: dict) -> list:
    candidates = data.get("candidates", [])
    if not candidates:
        return []
    return candidates[0].get("content", {}).get("parts", [])


def _extract_text_from_parts(parts: list) -> str:
    return "".join(p.get("text", "") for p in parts if "text" in p)


def _extract_function_calls(parts: list) -> list:
    calls = []
    for p in parts:
        if "functionCall" in p:
            fc = p["functionCall"]
            calls.append({"name": fc.get("name", ""), "args": fc.get("args", {})})
    return calls


# ── OAuth Token ───────────────────────────────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0, "refresh_count": 0}
_MAX_TOKEN_REFRESH = None  # EAG-S211-OAUTH-001: 장기 실행 안정성 확보 — None = 무제한 자동 재발급


def _fetch_new_token() -> tuple:
    if not JENI_CLIENT_ID or not JENI_CLIENT_SECRET:
        return "", "OAUTH_CREDENTIALS_NOT_CONFIGURED"
    import urllib.parse
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": JENI_CLIENT_ID,
        "client_secret": JENI_CLIENT_SECRET,
    }).encode()
    try:
        req = urllib.request.Request(
            BRIDGE_TOKEN_ENDPOINT, data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
            token = resp.get("access_token", "")
            if not token:
                return "", f"OAUTH_NO_TOKEN: {resp}"
            return token, None
    except Exception as e:
        return "", f"OAUTH_FETCH_FAILED: {e}"


def _get_access_token() -> tuple:
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"], None
    if (
        _MAX_TOKEN_REFRESH is not None
        and _token_cache["refresh_count"] > _MAX_TOKEN_REFRESH
    ):
        return "", "OAUTH_REFRESH_LIMIT_EXCEEDED"
    token, err = _fetch_new_token()
    if err:
        return "", err
    _token_cache["access_token"] = token
    _token_cache["expires_at"] = now + BRIDGE_TOKEN_TTL
    _token_cache["refresh_count"] += 1
    return token, None


def _invalidate_token() -> None:
    _token_cache["access_token"] = ""
    _token_cache["expires_at"] = 0.0


# ── 경로 검증 ─────────────────────────────────────────────────────────────────


def _is_path_allowed(path: str) -> bool:
    if not path:
        return True
    try:
        real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    return real == os.path.realpath(ARSS_ROOT) or real.startswith(
        os.path.realpath(ARSS_ROOT) + os.sep)


def _is_sandbox_write_allowed(path: str) -> bool:
    if not path:
        return False
    try:
        real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    real_sandbox = os.path.realpath(SANDBOX_ROOT)
    return real == real_sandbox or real.startswith(real_sandbox + os.sep)


# ── bridge REST ───────────────────────────────────────────────────────────────


def _is_write_allowed(target_path: str) -> bool:
    """Jeni 쓰기 허용 경로: sandbox/jeni/** + sandbox/common/collab/**"""
    if not target_path:
        return False
    try:
        real = os.path.realpath(os.path.abspath(target_path))
    except Exception:
        return False
    for base in [os.path.realpath(SANDBOX_ROOT), os.path.realpath(COLLAB_DIR)]:
        if real == base or real.startswith(base + os.sep):
            return True
    return False


def _call_bridge_tool(tool: str, params: dict) -> tuple:
    token, err = _get_access_token()
    if err:
        return "", f"TOOL_AUTH_FAILED: {err}"

    def _do_request(bearer_token: str) -> tuple:
        body = json.dumps(params).encode()
        req = urllib.request.Request(
            f"{BRIDGE_BASE}/jeni/{tool}", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {bearer_token}",
                     "Content-Length": str(len(body))}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=BRIDGE_TIMEOUT) as r:
                resp = json.loads(r.read().decode())
                return (r.status if hasattr(r, "status") else 200), resp, None
        except urllib.error.HTTPError as e:
            return e.code, None, f"HTTP_{e.code}"
        except Exception as e:
            return 0, None, f"BRIDGE_ERROR: {e}"

    status, resp, call_err = _do_request(token)
    if status == 401:
        _invalidate_token()
        token2, err2 = _get_access_token()
        if err2:
            return "", f"TOOL_AUTH_RETRY_FAILED: {err2}"
        status, resp, call_err = _do_request(token2)

    if call_err and resp is None:
        return "", f"TOOL_CALL_FAILED: {call_err}"
    if resp is None:
        return "", "TOOL_CALL_EMPTY_RESPONSE"
    if resp.get("isError"):
        content_text = resp.get("content", [{}])[0].get("text", "")
        return "", f"TOOL_DENIED: {content_text}"
    return resp.get("content", [{}])[0].get("text", ""), None


def _execute_function_call(name: str, args: dict) -> tuple:
    if name not in ALLOWED_TOOLS:
        return "", f"TOOL_NOT_ALLOWED: '{name}'"
    # write_file 분기 (S277 추가)
    if name == "write_file":
        target_path = args.get("target_path", "")
        content = args.get("content", "")
        if not target_path:
            return "", "WRITE_DENIED: target_path required"
        if not _is_write_allowed(target_path):
            return "", f"WRITE_DENIED: path not in jeni whitelist: {target_path}"
        return _call_bridge_tool("write_file", {"target_path": target_path, "content": content})
    # 읽기 도구 분기
    path = args.get("path", "")
    if path and not _is_path_allowed(path):
        return "", f"PATH_NOT_ALLOWED: '{path}'"
    call_params: dict = {"purpose": "OBSERVATION"}
    if path:
        call_params["path"] = path
    if "pattern" in args:
        call_params["pattern"] = args["pattern"]
    if "tail_lines" in args:
        call_params["tail_lines"] = int(args["tail_lines"])
    if "max_results" in args:
        call_params["max_results"] = int(args["max_results"])
    return _call_bridge_tool(name, call_params)


# ── Audit ─────────────────────────────────────────────────────────────────────


def _make_tool_audit_entry(round_num: int, tool: str, status: str,
                           duration_ms: int, path: str = "") -> dict:
    entry: dict = {"round": round_num, "tool": tool, "status": status,
                   "duration_ms": duration_ms}
    if path:
        entry["path"] = path
    return entry


def _make_audit_bundle(tool_rounds: int, audit_trail: list) -> dict:
    tools_used = list(dict.fromkeys(e["tool"] for e in audit_trail if e.get("tool")))
    return {"tool_rounds": tool_rounds, "tools_used": tools_used, "trail": audit_trail}


# ── Persistent Memory Layer ───────────────────────────────────────────────────


def _ensure_memory_dirs() -> None:
    for d in (MEM_CONVERSATION_DIR, MEM_FINDINGS_DIR, MEM_AUDITS_DIR, MEM_STATE_DIR):
        os.makedirs(d, exist_ok=True)


def _read_json_safe(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _load_runtime_state() -> dict:
    return _read_json_safe(MEM_STATE_FILE)


def _load_recent_conversation(max_turns: int = MAX_MEMORY_TURNS) -> list:
    if not os.path.isdir(MEM_CONVERSATION_DIR):
        return []
    files = sorted(glob.glob(os.path.join(MEM_CONVERSATION_DIR, "*.jsonl")), reverse=True)
    turns: list = []
    for fpath in files:
        try:
            with open(fpath, encoding="utf-8") as f:
                lines = f.readlines()
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except Exception:
                    continue
                if len(turns) >= max_turns:
                    break
        except Exception:
            continue
        if len(turns) >= max_turns:
            break
    return list(reversed(turns))


def _load_recent_findings(max_count: int = MAX_FINDINGS_INJECT) -> list:
    if not os.path.isdir(MEM_FINDINGS_DIR):
        return []
    files = sorted(glob.glob(os.path.join(MEM_FINDINGS_DIR, "*.json")), reverse=True)
    findings: list = []
    for fpath in files:
        data = _read_json_safe(fpath)
        if not data:
            continue
        status = str(data.get("status", "")).upper()
        if status in ("RESOLVED", "CLOSED"):
            continue
        findings.append(data)
        if len(findings) >= max_count:
            break
    return findings


def _load_recent_audits(max_count: int = MAX_AUDITS_INJECT) -> list:
    if not os.path.isdir(MEM_AUDITS_DIR):
        return []
    files = sorted(glob.glob(os.path.join(MEM_AUDITS_DIR, "*.json")), reverse=True)
    audits: list = []
    for fpath in files[:max_count]:
        data = _read_json_safe(fpath)
        if data:
            audits.append(data)
    return audits


def _load_memory_context() -> dict:
    return {
        "runtime_state": _load_runtime_state(),
        "recent_findings": _load_recent_findings(),
        "recent_audits": _load_recent_audits(),
        "recent_conversation": _load_recent_conversation(),
    }


def _build_memory_preamble(mem: dict) -> str:
    parts = ["[이전 세션 검증 컨텍스트]"]
    state = mem.get("runtime_state", {})
    if state:
        parts.append(f"runtime_state: {json.dumps(state, ensure_ascii=False)}")
    findings = mem.get("recent_findings", [])
    if findings:
        parts.append(f"recent_findings (미해결 {len(findings)}건): "
                     f"{json.dumps(findings, ensure_ascii=False)}")
    audits = mem.get("recent_audits", [])
    if audits:
        parts.append(f"recent_audits ({len(audits)}건): "
                     f"{json.dumps(audits, ensure_ascii=False)}")
    conv = mem.get("recent_conversation", [])
    if conv:
        conv_text = "\n".join(
            f"  [{t.get('role','?')}] {str(t.get('content',''))[:200]}" for t in conv)
        parts.append(f"recent_conversation (최근 {len(conv)}턴):\n{conv_text}")
    if len(parts) == 1:
        return ""
    return "\n".join(parts)


# ── Quota Lock ────────────────────────────────────────────────────────────────


def _sandbox_total_bytes() -> int:
    total = 0
    for root, _, files in os.walk(SANDBOX_ROOT):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except Exception:
                continue
    return total


def _enforce_quota() -> None:
    if _sandbox_total_bytes() <= SANDBOX_QUOTA_BYTES:
        return
    audit_files = sorted(glob.glob(os.path.join(MEM_AUDITS_DIR, "*.json")))
    for fpath in audit_files:
        if _sandbox_total_bytes() <= SANDBOX_QUOTA_BYTES:
            break
        try:
            os.remove(fpath)
        except Exception:
            continue


# ── Persist (STATE_6) ─────────────────────────────────────────────────────────


def _persist_conversation(session: str, prompt: str, response_text: str) -> bool:
    try:
        _ensure_memory_dirs()
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        fpath = os.path.join(MEM_CONVERSATION_DIR, f"{date_str}.jsonl")
        ts = _utc_now_iso()
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps({"timestamp": ts, "session": session,
                                "role": "user", "content": prompt},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"timestamp": ts, "session": session,
                                "role": "jeni", "content": response_text},
                               ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _persist_audit(session: str, audit_bundle: dict) -> bool:
    if not audit_bundle.get("trail"):
        return True
    try:
        _ensure_memory_dirs()
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        fpath = os.path.join(MEM_AUDITS_DIR, f"AUDIT-{session}-{ts}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump({"session": session, "timestamp": _utc_now_iso(),
                       **audit_bundle}, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _persist_results(session: str, prompt: str, response_text: str,
                     audit_bundle: dict):
    failures = []
    if not _persist_conversation(session, prompt, response_text):
        failures.append("conversation")
    if not _persist_audit(session, audit_bundle):
        failures.append("audit")
    try:
        _enforce_quota()
    except Exception:
        failures.append("quota")
    if failures:
        return f"PERSISTENCE_FAILED: {','.join(failures)}"
    return None


# ── Fail-Closed ───────────────────────────────────────────────────────────────


def _make_fail_closed_result(reason: str, detail: str, rounds_used: int,
                             audit_bundle=None) -> dict:
    fail_text = (
        "[JENI VERIFICATION]\n"
        "TRUST_READY = FAIL\n"
        "REVALIDATION_REQUIRED = YES\n"
        "STOP_SIGNAL = ON\n"
        f"FAIL_REASON = {reason}\n"
        f"DETAIL = {detail}\n"
    )
    result: dict = {"ok": False, "text": fail_text, "error": reason,
                    "rounds_used": rounds_used}
    if audit_bundle is not None:
        result["audit"] = audit_bundle
    return result


# ── Gemini 호출 ────────────────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:
        return "<unreadable>"


def _execute_gemini_request(req: urllib.request.Request) -> dict:
    """Gemini API 단일 요청 실행.
    503/429 재시도 유지. NO_PARTS 발생 시 Exponential Backoff 재시도 추가 (EAG-S211-JENI-001).
    """
    started_at = time.time()

    _orig_url = req.full_url
    _orig_data = req.data
    _orig_headers = dict(req.headers)

    def _new_req() -> urllib.request.Request:
        return urllib.request.Request(
            _orig_url, data=_orig_data,
            headers=_orig_headers, method="POST")

    def _budget_ok(extra_sleep: float = 0.0) -> bool:
        elapsed = time.time() - started_at
        return (elapsed + extra_sleep) < min(GEMINI_TIMEOUT, MAX_TOTAL_SECONDS)

    def _parse_response(data: dict) -> dict:
        """parts 추출 시도. NO_PARTS 되면 exponential backoff 재시도."""
        parts = _extract_parts(data)
        if parts:
            return {"ok": True, "text": _extract_text_from_parts(parts),
                    "function_calls": _extract_function_calls(parts),
                    "parts": parts, "error": None}

        finish = _extract_finish_reason(data)

        for retry_idx in range(NO_PARTS_RETRY_MAX):
            sleep_sec = NO_PARTS_RETRY_BASE_SLEEP * (2 ** retry_idx)  # 2/4/8
            if not _budget_ok(sleep_sec):
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "error": "FAIL_CLOSED: NO_PARTS retry would exceed time budget"}
            time.sleep(sleep_sec)
            try:
                with urllib.request.urlopen(_new_req(), timeout=GEMINI_TIMEOUT) as r:
                    rd = json.loads(r.read().decode("utf-8"))
                    rp = _extract_parts(rd)
                    if rp:
                        return {"ok": True, "text": _extract_text_from_parts(rp),
                                "function_calls": _extract_function_calls(rp),
                                "parts": rp, "error": None}
                    finish = _extract_finish_reason(rd)
            except Exception as re_err:
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "error": f"FAIL_CLOSED: NO_PARTS retry error — {re_err}"}

        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"NO_PARTS: finish_reason={finish} (after_{NO_PARTS_RETRY_MAX}_retries)"}

    def _retry_http_with_backoff(code: int) -> dict:
        """503/429 공통 지수 백오프 재시도 (EAG-S284-JENI-RETRY-001).
        NO_PARTS 백오프와 동일 패턴: 최대 3회, 2/4/8초.
        시간 예산 초과 시 즉시 FAIL_CLOSED.
        """
        tag = f"after_{code}_retry"
        for retry_idx in range(HTTP_RETRY_MAX):
            sleep_sec = HTTP_RETRY_BASE_SLEEP * (2 ** retry_idx)  # 2/4/8
            if not _budget_ok(sleep_sec):
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "error": f"FAIL_CLOSED: HTTP_{code} retry would exceed time budget ({tag})"}
            time.sleep(sleep_sec)
            try:
                with urllib.request.urlopen(_new_req(), timeout=GEMINI_TIMEOUT) as resp_r:
                    data_r = json.loads(resp_r.read().decode("utf-8"))
                    return _parse_response(data_r)
            except urllib.error.HTTPError as e_r:
                if e_r.code in (503, 429):
                    code = e_r.code
                    tag = f"after_{code}_retry"
                    continue
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "error": f"HTTP_{e_r.code}: {_read_http_error_body(e_r)} ({tag})"}
            except Exception as e_r:
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "error": f"FAIL_CLOSED: HTTP_{code} retry error — {e_r} ({tag})"}
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"HTTP_{code}: persisted after {HTTP_RETRY_MAX} retries ({tag})"}

    try:
        with urllib.request.urlopen(_new_req(), timeout=GEMINI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return _parse_response(data)
    except urllib.error.HTTPError as e:
        if e.code in (503, 429):
            return _retry_http_with_backoff(e.code)
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"HTTP_{e.code}: {_read_http_error_body(e)}"}
    except urllib.error.URLError as e:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"FAIL_CLOSED: Gemini unreachable — {e}"}
    except TimeoutError:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"FAIL_CLOSED: Gemini timeout ({GEMINI_TIMEOUT}s)"}
    except Exception as e:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _call_gemini(contents: list, escalate: bool = False) -> dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": "FAIL_CLOSED: AIBA_GEMINI_API_KEY not configured"}
    _model = GEMINI_MODEL_ESCALATE if escalate else GEMINI_MODEL
    body = {
        "system_instruction": {"parts": [{"text": JENI_SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "tools": [{"functionDeclarations": _build_function_declarations()}],
        "generationConfig": {"temperature": 0.4,
                             "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS},
    }
    raw_body = json.dumps(body).encode("utf-8")
    url = f"{GEMINI_API_BASE}/{_model}:generateContent"
    req = urllib.request.Request(
        url, data=raw_body,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": GEMINI_API_KEY,
                 "Content-Length": str(len(raw_body))}, method="POST")
    return _execute_gemini_request(req)


# ── Message 조립 ──────────────────────────────────────────────────────────────


def _build_initial_message(prompt: str, context: str, memory_preamble: str,
                           sc_context: str = "") -> dict:
    segments = []
    if sc_context:
        segments.append(sc_context)
    if memory_preamble:
        segments.append(memory_preamble)
    if context:
        segments.append(f"[배경 정보]\n{context}")
    segments.append(f"[질문]\n{prompt}")
    return {"role": "user", "parts": [{"text": "\n\n".join(segments)}]}


def _build_function_response_message(name: str, result_text: str, error) -> dict:
    response_payload = {"error": error} if error else {"result": result_text}
    return {"role": "user",
            "parts": [{"functionResponse": {"name": name, "response": response_payload}}]}


# ── Observe Loop (EAG-S279-OBSERVE-001) ──────────────────────────────────────


def _run_observe_loop(targets: list, session: str = "S000") -> dict:
    """
    /observe 엔드포인트 처리.
    targets 목록에 따라 ALLOWED_TOOLS 자율 호출 후 결과를 dict로 반환.
    targets:
      - "session_context"    : SESSION_CONTEXT_POINTER + SC_FINAL 읽기
      - "runtime_snapshot"   : get_runtime_snapshot 호출
      - "service_status"     : runtime_snapshot 내 services 필드 추출
    """
    results: dict = {}
    errors: dict = {}

    for target in targets:
        try:
            if target == "session_context":
                # POINTER 읽기
                ptr_text, ptr_err = _execute_function_call(
                    "read_file",
                    {"path": "/opt/arss/engine/arss-protocol/SESSION_CONTEXT_POINTER.json"}
                )
                if ptr_err:
                    errors[target] = f"POINTER_READ_FAILED: {ptr_err}"
                    continue
                import json as _json
                pointer = _json.loads(ptr_text)
                last_session = pointer.get("last_session") or pointer.get("current_session")
                if last_session is None:
                    errors[target] = "POINTER: last_session 키 없음"
                    continue
                # SC_FINAL 읽기
                sc_path = (
                    f"/opt/arss/engine/arss-protocol/"
                    f"SESSION_CONTEXT_S{last_session}_FINAL.json"
                )
                sc_text, sc_err = _execute_function_call("read_file", {"path": sc_path})
                if sc_err:
                    errors[target] = f"SC_FINAL_READ_FAILED: {sc_err}"
                    continue
                sc_data = _json.loads(sc_text)
                summary_keys = [
                    "session_count", "chain", "next_steps",
                    "agent_focus", "pytest_status", "session_reentry",
                ]
                summary = {k: sc_data[k] for k in summary_keys if k in sc_data}
                results[target] = summary

            elif target in ("runtime_snapshot", "service_status"):
                snap_text, snap_err = _execute_function_call(
                    "get_runtime_snapshot", {}
                )
                if snap_err:
                    errors[target] = f"SNAPSHOT_FAILED: {snap_err}"
                    continue
                import json as _json
                snap_data = _json.loads(snap_text)
                if target == "service_status":
                    results[target] = snap_data.get("services", snap_data)
                else:
                    results[target] = snap_data

            else:
                errors[target] = f"UNKNOWN_TARGET: {target}"

        except Exception as e:
            errors[target] = f"EXCEPTION: {e}"

    return {
        "ok": len(errors) == 0,
        "session": session,
        "results": results,
        "errors": errors,
    }



# ── Persistent Multi-Turn Loop ────────────────────────────────────────────────


def _run_verification_loop(prompt: str, context: str, session: str = "S000", escalate: bool = False) -> dict:
    loop_start = time.time()

    sc_context = _load_session_context()
    memory = _load_memory_context()
    memory_preamble = _build_memory_preamble(memory)

    accumulated: list = [_build_initial_message(prompt, context, memory_preamble, sc_context)]
    audit_trail: list = []
    round_num = 0
    final_result = None

    while round_num <= MAX_TOOL_ROUNDS:
        elapsed = time.time() - loop_start
        if elapsed >= TIMEOUT_PREEMPT_SECONDS:
            final_result = _make_fail_closed_result(
                "TIMEOUT_BUDGET_EXCEEDED",
                f"elapsed={elapsed:.1f}s >= preempt={TIMEOUT_PREEMPT_SECONDS}s",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        call_result = _call_gemini(accumulated, escalate=escalate)
        if not call_result["ok"]:
            final_result = _make_fail_closed_result(
                "VALIDATION_PARSE_FAILURE", call_result.get("error") or "",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        model_parts = call_result["parts"]
        accumulated.append({"role": "model", "parts": model_parts})

        function_calls = call_result["function_calls"]
        if function_calls:
            if round_num >= MAX_TOOL_ROUNDS:
                final_result = _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"function_call at round {round_num}, max={MAX_TOOL_ROUNDS}",
                    round_num, _make_audit_bundle(round_num, audit_trail))
                break

            fc = function_calls[0]
            name = fc["name"]
            args = fc.get("args", {})
            path = args.get("path", "")
            t_start = time.time()
            result_text, tool_err = _execute_function_call(name, args)
            duration_ms = int((time.time() - t_start) * 1000)

            audit_trail.append(_make_tool_audit_entry(
                round_num=round_num + 1, tool=name,
                status="ALLOW" if not tool_err else "DENY",
                duration_ms=duration_ms, path=path))

            round_num += 1
            accumulated.append(
                _build_function_response_message(name, result_text, tool_err))
            continue

        final_result = {"ok": True, "text": call_result["text"], "error": None,
                        "rounds_used": round_num,
                        "audit": _make_audit_bundle(round_num, audit_trail)}
        break

    if final_result is None:  # pragma: no cover
        final_result = _make_fail_closed_result(
            "MAX_ROUNDS_EXCEEDED", "loop exit without resolution",
            round_num, _make_audit_bundle(round_num, audit_trail))

    persist_err = _persist_results(
        session, prompt, final_result.get("text", ""),
        final_result.get("audit", {"tool_rounds": 0, "tools_used": [], "trail": []}))
    if persist_err:
        final_result["persistence"] = persist_err

    return final_result


# ── HTTP Server ────────────────────────────────────────────────────────────────


class JeniRuntimeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {
                "status": "active", "version": RUNTIME_VERSION,
                "model": GEMINI_MODEL, "model_escalate": GEMINI_MODEL_ESCALATE,
                "key_present": bool(GEMINI_API_KEY),
                "max_tool_rounds": MAX_TOOL_ROUNDS,
                "max_total_seconds": MAX_TOTAL_SECONDS,
                "persistent_memory": True, "function_calling": True,
                "gemini_503_retry": True,
                "http_retry_backoff": "3x_2_4_8",
                "sc_context_loaded": _sc_cache["loaded"],
                "observe_endpoint": True})
            return
        self._send_json(403, {"error": "forbidden"})

    def do_POST(self):
        if self.path == "/observe":
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                req_body = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return
            targets = req_body.get("targets", ["session_context", "runtime_snapshot", "service_status"])
            session = req_body.get("session", "S000")
            result = _run_observe_loop(targets, session)
            self._send_json(200, result)
            return
        if self.path != "/ask":
            self._send_json(403, {"error": "forbidden"})
            return
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            req_body = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid_json"})
            return
        prompt = req_body.get("prompt", "")
        context = req_body.get("context", "")
        session = req_body.get("session", "S000")
        escalate = bool(req_body.get("escalate", False))
        if not prompt:
            self._send_json(400, {"ok": False, "error": "prompt required"})
            return
        result = _run_verification_loop(prompt, context, session, escalate=escalate)
        self._send_json(200, result)  # v4.2.0: 항상 200, ok=false 시 body에 error 포함


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    import signal

    def _handle_shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    _ensure_memory_dirs()

    print(f"[JENI_RUNTIME] starting v{RUNTIME_VERSION} model={GEMINI_MODEL} "
          f"key={_mask_key(GEMINI_API_KEY)} max_tool_rounds={MAX_TOOL_ROUNDS} "
          f"persistent_memory=True function_calling=True "
          f"gemini_503_retry=True sleep={GEMINI_503_RETRY_SLEEP}s sc_auto_load=True", file=sys.stderr)
    if not GEMINI_API_KEY:
        print("[JENI_RUNTIME] WARN: AIBA_GEMINI_API_KEY not set — /ask will FAIL_CLOSED",
              file=sys.stderr)

    server = ThreadedHTTPServer((RUNTIME_HOST, RUNTIME_PORT), JeniRuntimeHandler)
    print(f"[JENI_RUNTIME] listening on {RUNTIME_HOST}:{RUNTIME_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

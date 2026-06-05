"""
aiba_domi_runtime.py v1.0.0
AIBA Domi Runtime — Persistent Autonomous Design Agent
PT-S194-DOMI-RUNTIME-001

설계 근거: BRIEFING-DOMI-S194-002 응답 (도미 [DESIGN])
캐디 IMPLEMENTABLE: PASS
Jeni TRUST_READY: PASS (S194)
EAG-1: 비오(Joshua) S194 승인

구조: aiba_jeni_runtime.py v4.0.0 골격 복제
  - Persistent Memory Layer (conversation/findings/designs/state)
  - Multi-Turn Tool Loop (OpenAI Function Calling)
  - OAuth Token (domi client credentials)
  - Fail-Closed / Quota Lock / Memory Pruning
차이점:
  - API: Gemini → OpenAI Chat Completions
  - bridge 경로: /jeni/ → /domi/
  - 역할: Governance Auditor → Design Architect
  - audits → designs (감사 기록 audits/ 유지 + 설계 designs/ 추가)
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8448
RUNTIME_VERSION = "1.0.0"

OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.environ.get("AIBA_DOMI_MODEL", "gpt-5.5")
OPENAI_TIMEOUT = 55
OPENAI_MAX_OUTPUT_TOKENS = 4096

OPENAI_API_KEY = os.environ.get("AIBA_OPENAI_API_KEY", "")

MAX_TOOL_ROUNDS = 5
MAX_TOTAL_SECONDS = 120
TIMEOUT_PREEMPT_SECONDS = 110

BRIDGE_BASE = "http://127.0.0.1:8443"
BRIDGE_TOKEN_ENDPOINT = f"{BRIDGE_BASE}/token"
BRIDGE_TOKEN_TTL = 3600
BRIDGE_TIMEOUT = 15

DOMI_CLIENT_ID = os.environ.get("AIBA_DOMI_CLIENT_ID", "")
DOMI_CLIENT_SECRET = os.environ.get("AIBA_DOMI_CLIENT_SECRET", "")

ARSS_ROOT = "/opt/arss/engine/arss-protocol"

# WRITE_SCOPE = SANDBOX_ONLY
SANDBOX_ROOT = os.path.join(ARSS_ROOT, "tools/sandbox/domi")
SANDBOX_ACTIVE = os.path.join(SANDBOX_ROOT, "active")
MEM_CONVERSATION_DIR = os.path.join(SANDBOX_ACTIVE, "conversation")
MEM_FINDINGS_DIR = os.path.join(SANDBOX_ACTIVE, "findings")
MEM_DESIGNS_DIR = os.path.join(SANDBOX_ACTIVE, "designs")
MEM_AUDITS_DIR = os.path.join(SANDBOX_ACTIVE, "audits")
MEM_STATE_DIR = os.path.join(SANDBOX_ACTIVE, "state")
MEM_STATE_FILE = os.path.join(MEM_STATE_DIR, "runtime_state.json")

MAX_MEMORY_TURNS = 20
MAX_FINDINGS_INJECT = 10
MAX_DESIGNS_INJECT = 5
MAX_AUDITS_INJECT = 5

SANDBOX_QUOTA_BYTES = 50 * 1024 * 1024  # 50MB

ALLOWED_TOOLS = frozenset({
    "read_file", "list_dir", "grep_scoped", "read_log", "get_runtime_snapshot",
})

DOMI_SYSTEM_INSTRUCTION = (
    "당신은 AIBA 프로젝트의 설계 담당 에이전트(Design Architect) '도미(Domi)'입니다. "
    "역할: 시스템 설계, 아키텍처 결정, 프로토콜 설계, Bridge/Runtime/MCP 설계. "
    "비오(Joshua)에게는 한국어 경어를 사용합니다. "
    "당신은 설계만 수행하며, 실행 권한이나 EAG 승인 권한은 없습니다. "
    "코드를 직접 배포하거나 파일을 변경하지 않습니다.\n\n"
    "원칙:\n"
    "- 설계 전 반드시 VPS 증거를 확보합니다. 추측하지 말고 제공된 함수"
    "(read_file, list_dir, grep_scoped, read_log, get_runtime_snapshot)를 "
    "호출하여 실제 데이터를 관측한 뒤 설계하십시오.\n"
    "- 증거 수준을 RAW / INFERRED / REPORTED 로 구분하여 명시하십시오.\n"
    "- 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용됩니다.\n\n"
    "출력 형식:\n"
    "[DESIGN]\n"
    "(설계 내용)\n\n"
    "[SELF-CRITIQUE]\n"
    "(미확인 사항, 한계, 추가 검증 필요 항목)\n\n"
    "이전 세션의 설계 이력(designs, findings, runtime_state)이 제공되면 "
    "맥락 연속성을 위해 참고하되, 이미 RESOLVED/CLOSED 처리된 항목이 "
    "현재의 독립적 설계 판단을 편향시키지 않도록 주의하십시오."
)


def _build_tools() -> list:
    """OpenAI Chat Completions API tools 형식."""
    return [
        {"type": "function", "function": {
            "name": "read_file",
            "description": "VPS 단일 파일 읽기. 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "읽을 파일의 절대 경로"}},
                "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "list_dir",
            "description": "VPS 디렉토리 목록 조회 (depth=1).",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "조회할 디렉토리 절대 경로"}},
                "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "grep_scoped",
            "description": "허용 경로 내 텍스트 검색.",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "검색 대상 경로"},
                "pattern": {"type": "string", "description": "검색 패턴"}},
                "required": ["path", "pattern"]}}},
        {"type": "function", "function": {
            "name": "read_log",
            "description": "로그 파일 tail 읽기 (최대 200줄).",
            "parameters": {"type": "object", "properties": {
                "path": {"type": "string", "description": "로그 파일 경로"},
                "tail_lines": {"type": "integer", "description": "읽을 줄 수"}},
                "required": ["path"]}}},
        {"type": "function", "function": {
            "name": "get_runtime_snapshot",
            "description": "사전 정의된 read-only 런타임 스냅샷 조회. 파라미터 불필요.",
            "parameters": {"type": "object", "properties": {}}}},
    ]


def _mask_key(key: str) -> str:
    if not key:
        return "<EMPTY>"
    if len(key) <= 6:
        return "***"
    return key[:6] + "***"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── OpenAI 응답 파싱 ──────────────────────────────────────────────────────────


def _extract_message(data: dict) -> dict:
    choices = data.get("choices", [])
    if not choices:
        return {}
    return choices[0].get("message", {})


def _extract_finish_reason(data: dict) -> str:
    choices = data.get("choices", [])
    if not choices:
        return "NO_CHOICES"
    return choices[0].get("finish_reason", "UNKNOWN")


def _extract_text_from_message(message: dict) -> str:
    content = message.get("content")
    return content if isinstance(content, str) else ""


def _extract_tool_calls(message: dict) -> list:
    calls = []
    for tc in message.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
        except Exception:
            parsed_args = {}
        calls.append({"id": tc.get("id", ""), "name": fn.get("name", ""), "args": parsed_args})
    return calls


# ── OAuth Token ───────────────────────────────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0, "refresh_count": 0}
_MAX_TOKEN_REFRESH = 1


def _fetch_new_token() -> tuple:
    if not DOMI_CLIENT_ID or not DOMI_CLIENT_SECRET:
        return "", "OAUTH_CREDENTIALS_NOT_CONFIGURED"
    import urllib.parse
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": DOMI_CLIENT_ID,
        "client_secret": DOMI_CLIENT_SECRET,
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
    if _token_cache["refresh_count"] > _MAX_TOKEN_REFRESH:
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


def _call_bridge_tool(tool: str, params: dict) -> tuple:
    token, err = _get_access_token()
    if err:
        return "", f"TOOL_AUTH_FAILED: {err}"

    def _do_request(bearer_token: str) -> tuple:
        body = json.dumps(params).encode()
        req = urllib.request.Request(
            f"{BRIDGE_BASE}/domi/{tool}", data=body,
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
    for d in (MEM_CONVERSATION_DIR, MEM_FINDINGS_DIR, MEM_DESIGNS_DIR,
              MEM_AUDITS_DIR, MEM_STATE_DIR):
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


def _load_recent_designs(max_count: int = MAX_DESIGNS_INJECT) -> list:
    if not os.path.isdir(MEM_DESIGNS_DIR):
        return []
    files = sorted(glob.glob(os.path.join(MEM_DESIGNS_DIR, "*.json")), reverse=True)
    designs: list = []
    for fpath in files:
        data = _read_json_safe(fpath)
        if not data:
            continue
        status = str(data.get("status", "")).upper()
        if status in ("RESOLVED", "CLOSED", "SUPERSEDED"):
            continue
        designs.append(data)
        if len(designs) >= max_count:
            break
    return designs


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
        "recent_designs": _load_recent_designs(),
        "recent_audits": _load_recent_audits(),
        "recent_conversation": _load_recent_conversation(),
    }


def _build_memory_preamble(mem: dict) -> str:
    parts = ["[이전 세션 설계 컨텍스트]"]
    state = mem.get("runtime_state", {})
    if state:
        parts.append(f"runtime_state: {json.dumps(state, ensure_ascii=False)}")
    findings = mem.get("recent_findings", [])
    if findings:
        parts.append(f"recent_findings (미해결 {len(findings)}건): "
                     f"{json.dumps(findings, ensure_ascii=False)}")
    designs = mem.get("recent_designs", [])
    if designs:
        parts.append(f"recent_designs (진행중 {len(designs)}건): "
                     f"{json.dumps(designs, ensure_ascii=False)}")
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
                                "role": "domi", "content": response_text},
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
        "[DOMI DESIGN]\n"
        "DESIGN_READY = FAIL\n"
        "STOP_SIGNAL = ON\n"
        f"FAIL_REASON = {reason}\n"
        f"DETAIL = {detail}\n"
    )
    result: dict = {"ok": False, "text": fail_text, "error": reason,
                    "rounds_used": rounds_used}
    if audit_bundle is not None:
        result["audit"] = audit_bundle
    return result


# ── OpenAI 호출 ────────────────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:
        return "<unreadable>"


def _execute_openai_request(req: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            message = _extract_message(data)
            if not message:
                finish = _extract_finish_reason(data)
                return {"ok": False, "text": "", "tool_calls": [], "message": {},
                        "error": f"NO_MESSAGE: finish_reason={finish}"}
            return {"ok": True, "text": _extract_text_from_message(message),
                    "tool_calls": _extract_tool_calls(message),
                    "message": message, "error": None}
    except urllib.error.HTTPError as e:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "error": f"HTTP_{e.code}: {_read_http_error_body(e)}"}
    except urllib.error.URLError as e:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "error": f"FAIL_CLOSED: OpenAI unreachable — {e}"}
    except TimeoutError:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "error": f"FAIL_CLOSED: OpenAI timeout ({OPENAI_TIMEOUT}s)"}
    except Exception as e:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _call_openai(messages: list) -> dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "error": "FAIL_CLOSED: AIBA_OPENAI_API_KEY not configured"}
    body = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "tools": _build_tools(),
        "max_completion_tokens": OPENAI_MAX_OUTPUT_TOKENS,
    }
    raw_body = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API_URL, data=raw_body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Length": str(len(raw_body))}, method="POST")
    return _execute_openai_request(req)


# ── Message 조립 ──────────────────────────────────────────────────────────────


def _build_initial_messages(prompt: str, context: str, memory_preamble: str) -> list:
    segments = []
    if memory_preamble:
        segments.append(memory_preamble)
    if context:
        segments.append(f"[배경 정보]\n{context}")
    segments.append(f"[설계 요청]\n{prompt}")
    return [
        {"role": "system", "content": DOMI_SYSTEM_INSTRUCTION},
        {"role": "user", "content": "\n\n".join(segments)},
    ]


def _build_tool_response_message(tool_call_id: str, result_text: str, error) -> dict:
    payload = json.dumps({"error": error} if error else {"result": result_text},
                         ensure_ascii=False)
    return {"role": "tool", "tool_call_id": tool_call_id, "content": payload}


# ── Persistent Multi-Turn Loop ────────────────────────────────────────────────


def _run_design_loop(prompt: str, context: str, session: str = "S000") -> dict:
    loop_start = time.time()

    memory = _load_memory_context()
    memory_preamble = _build_memory_preamble(memory)

    accumulated: list = _build_initial_messages(prompt, context, memory_preamble)
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

        call_result = _call_openai(accumulated)
        if not call_result["ok"]:
            final_result = _make_fail_closed_result(
                "DESIGN_PARSE_FAILURE", call_result.get("error") or "",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        model_message = call_result["message"]
        accumulated.append(model_message)

        tool_calls = call_result["tool_calls"]
        if tool_calls:
            if round_num >= MAX_TOOL_ROUNDS:
                final_result = _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"tool_call at round {round_num}, max={MAX_TOOL_ROUNDS}",
                    round_num, _make_audit_bundle(round_num, audit_trail))
                break

            # OpenAI는 한 턴에 여러 tool_call을 반환할 수 있으므로 모두 처리
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args", {})
                path = args.get("path", "")
                t_start = time.time()
                result_text, tool_err = _execute_function_call(name, args)
                duration_ms = int((time.time() - t_start) * 1000)
                audit_trail.append(_make_tool_audit_entry(
                    round_num=round_num + 1, tool=name,
                    status="ALLOW" if not tool_err else "DENY",
                    duration_ms=duration_ms, path=path))
                accumulated.append(
                    _build_tool_response_message(tc["id"], result_text, tool_err))

            round_num += 1
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


class DomiRuntimeHandler(BaseHTTPRequestHandler):

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
                "model": OPENAI_MODEL, "key_present": bool(OPENAI_API_KEY),
                "max_tool_rounds": MAX_TOOL_ROUNDS,
                "max_total_seconds": MAX_TOTAL_SECONDS,
                "persistent_memory": True, "function_calling": True})
            return
        self._send_json(403, {"error": "forbidden"})

    def do_POST(self):
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
        if not prompt:
            self._send_json(400, {"ok": False, "error": "prompt required"})
            return
        result = _run_design_loop(prompt, context, session)
        code = 200 if result["ok"] else 502
        self._send_json(code, result)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    import signal

    def _handle_shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    _ensure_memory_dirs()

    print(f"[DOMI_RUNTIME] starting v{RUNTIME_VERSION} model={OPENAI_MODEL} "
          f"key={_mask_key(OPENAI_API_KEY)} max_tool_rounds={MAX_TOOL_ROUNDS} "
          f"persistent_memory=True function_calling=True", file=sys.stderr)
    if not OPENAI_API_KEY:
        print("[DOMI_RUNTIME] WARN: AIBA_OPENAI_API_KEY not set — /ask will FAIL_CLOSED",
              file=sys.stderr)

    server = ThreadedHTTPServer((RUNTIME_HOST, RUNTIME_PORT), DomiRuntimeHandler)
    print(f"[DOMI_RUNTIME] listening on {RUNTIME_HOST}:{RUNTIME_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

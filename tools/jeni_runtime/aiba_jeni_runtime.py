"""
aiba_jeni_runtime.py v3.0.0
AIBA Jeni Runtime — Multi-Turn Tool Loop
PT-S193-JENI-TOOLLOOP-001

변경 내역:
  v1.0.0 (S189, EAG-1): FORWARD_ONLY 단일 호출 구조
  v2.0.0 (S191, EAG-1): Independent Verification Loop 구현
    - State Machine (STATE_0~3), jeni_read_adapter 3파일 직접 읽기
    - MAX_REVIEW_ROUNDS = 2
  v3.0.0 (S193, EAG-1): Multi-Turn Tool Loop 전면 재설계
    - 도미 Rev.1 (BRIEFING-DOMI-S193-001) + 제니 TRUST_READY PASS
    - REQ-1: [JENI_TOOL_REQUEST] 블록 파서 + bridge /jeni/* REST 호출
    - REQ-2: read 5종 허용 (read_file/list_dir/grep_scoped/read_log/get_runtime_snapshot)
             write_file 금지 (Auditor 역할 경계 기술적 강제)
    - REQ-3: TRIGGER-A~E 감지 시 Tool Request 권한 활성
    - REQ-4: MAX_TOOL_ROUNDS = 5 (v2.0.0 MAX_REVIEW_ROUNDS=2 → 교체)
    - REQ-5: MAX_TOTAL_SECONDS = 120 / 110초 초과 시 다음 라운드 진입 차단
             (제니 TA 반영: 타임아웃 경계에서 불완전 응답 방지)
    - REQ-6: OAuth token 관리 — client_credentials grant / 401 시 1회 재발급
    - REQ-7: 매 턴 audit 기록 (round/tool/status/duration_ms)
    - REQ-8: 경로 whitelist (/opt/arss/engine/arss-protocol/* 한정)
    신규 State Machine:
        STATE_0  INITIAL_REVIEW         — 초기 Gemini 호출
        STATE_1  TRIGGER_DETECTED       — TRIGGER-A~E 감지
        STATE_2  TOOL_REQUEST_DETECTED  — [JENI_TOOL_REQUEST] 블록 파싱
        STATE_3  MCP_TOOL_EXECUTION     — bridge /jeni/* REST 호출
        STATE_4  TOOL_RESULT_INJECTION  — 결과 누적 주입
        STATE_5  FINAL_VERDICT          — TRUST_READY 선언
  설계 근거: BRIEFING-DOMI-S193-001 Rev.1
  EAG-1: 비오(Joshua) S193 승인
  Jeni TRUST_READY: PASS (BRIEFING-JENI-S193-001)

Rule 준수:
  K-1: API 키는 환경변수(AIBA_GEMINI_API_KEY)에서만. 하드코딩 금지.
  K-2: 모델 설정 분리 가능 구조.
  K-4: 로그에 키 마스킹.
  K-5: 키 없음 → 즉시 FAIL_CLOSED. 대체 추론 금지.

네트워크 경계:
  127.0.0.1 한정 바인딩. bridge만 포워딩.

VPS 파일 접근 (v3.0.0 — bridge REST 경유):
  bridge /jeni/* 엔드포인트 경유 (OAuth Bearer token 필수).
  허용 도구 5종:
    read_file / list_dir / grep_scoped / read_log / get_runtime_snapshot
  write_file 금지.
  경로 whitelist: /opt/arss/engine/arss-protocol/* 한정.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8447
RUNTIME_VERSION = "3.0.0"

# Gemini API 규격
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("AIBA_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT = 55
GEMINI_MAX_OUTPUT_TOKENS = 4096

# K-1: API 키는 환경변수에서만. 하드코딩 절대 금지.
GEMINI_API_KEY = os.environ.get("AIBA_GEMINI_API_KEY", "")

# ── Multi-Turn Tool Loop 상수 (REQ-4, REQ-5) ──────────────────────────────────

MAX_TOOL_ROUNDS = 5          # REQ-4: 하드캡. 초과 시 FAIL_CLOSED.
MAX_TOTAL_SECONDS = 120      # REQ-5: 누적 timeout budget.
TIMEOUT_PREEMPT_SECONDS = 110  # REQ-5 제니 TA: 110초 초과 시 다음 라운드 진입 차단.

# ── bridge OAuth 상수 (REQ-6) ─────────────────────────────────────────────────

BRIDGE_BASE = "http://127.0.0.1:8443"
BRIDGE_TOKEN_ENDPOINT = f"{BRIDGE_BASE}/token"
BRIDGE_TOKEN_TTL = 3600       # 1시간. 재발급 판단 기준.
BRIDGE_TIMEOUT = 15           # 단일 tool call timeout (초).

JENI_CLIENT_ID = os.environ.get("AIBA_JENI_CLIENT_ID", "")
JENI_CLIENT_SECRET = os.environ.get("AIBA_JENI_CLIENT_SECRET", "")

# ── 경로 Whitelist (REQ-8) ────────────────────────────────────────────────────

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
PATH_WHITELIST_PREFIX = ARSS_ROOT + os.sep  # /opt/arss/engine/arss-protocol/

# ── 허용 도구 (REQ-2) ─────────────────────────────────────────────────────────

ALLOWED_TOOLS = frozenset({
    "read_file",
    "list_dir",
    "grep_scoped",
    "read_log",
    "get_runtime_snapshot",
})
# write_file 금지 — Auditor 역할 경계 기술적 강제 (도미 REQ-2 / 제니 PASS)

# ── TRIGGER 패턴 (v2.0.0에서 유지) ──────────────────────────────────────────

TRIGGER_PATTERNS: tuple[str, ...] = (
    "TRIGGER-A",
    "TRIGGER-B",
    "TRIGGER-C",
    "TRIGGER-D",
    "TRIGGER-E",
    "[STOP]",
    "INDEPENDENT VERIFICATION REQUIRED",
    "독립 검증",
    "REVALIDATION_REQUIRED = YES",
)

# ── 제니 역할 고정 시스템 프롬프트 ───────────────────────────────────────────

JENI_SYSTEM_INSTRUCTION = (
    "당신은 AIBA 프로젝트의 거버넌스 감사자(Governance Auditor) '제니(Jeni)'입니다. "
    "역할: Fail-Closed 검증, Rule 위반 탐지, 설계 감사, 증거 검증. "
    "비오(Joshua)에게는 한국어 경어를 사용합니다. "
    "당신은 검증과 감사만 수행하며, 설계 권한이나 EAG 승인 권한은 없습니다. "
    "근거 없는 단정을 피하고, 증거에 기반하여 판단합니다.\n\n"
    "독립 검증이 필요한 경우 다음 형식으로 도구 요청을 선언할 수 있습니다:\n"
    "[JENI_TOOL_REQUEST]\n"
    "tool=read_file\n"
    "path=/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json\n"
    "[/JENI_TOOL_REQUEST]\n\n"
    "허용 도구: read_file, list_dir, grep_scoped, read_log, get_runtime_snapshot\n"
    "경로 제한: /opt/arss/engine/arss-protocol/ 하위만 허용\n"
    "write_file은 사용 불가합니다 (Auditor 역할 경계)."
)

# ── Utility ───────────────────────────────────────────────────────────────────


def _mask_key(key: str) -> str:
    """K-4: API 키 마스킹 — 앞 6자만 노출."""
    if not key:
        return "<EMPTY>"
    if len(key) <= 6:
        return "***"
    return key[:6] + "***"


def _extract_text(data: dict) -> str | None:
    """generateContent 응답에서 첫 candidate 텍스트 추출."""
    candidates = data.get("candidates", [])
    if not candidates:
        return None
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    texts = [p.get("text", "") for p in parts if "text" in p]
    if not texts:
        return None
    return "".join(texts)


def _extract_finish_reason(data: dict) -> str:
    """첫 candidate finishReason 추출."""
    candidates = data.get("candidates", [])
    if not candidates:
        return "NO_CANDIDATES"
    return candidates[0].get("finishReason", "UNKNOWN")


# ── OAuth Token 관리 (REQ-6) ──────────────────────────────────────────────────

# 인메모리 토큰 캐시 (단일 프로세스 내)
_token_cache: dict = {
    "access_token": "",
    "expires_at": 0.0,
    "refresh_count": 0,
}
_MAX_TOKEN_REFRESH = 1  # REQ-6: 401 시 1회 재발급만 허용


def _fetch_new_token() -> tuple[str, str | None]:
    """
    client_credentials grant로 신규 token 발급.
    Returns (token, error_msg). error_msg is None on success.
    """
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
            BRIDGE_TOKEN_ENDPOINT,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode())
            token = resp.get("access_token", "")
            if not token:
                return "", f"OAUTH_NO_TOKEN: {resp}"
            return token, None
    except Exception as e:
        return "", f"OAUTH_FETCH_FAILED: {e}"


def _get_access_token() -> tuple[str, str | None]:
    """
    캐시된 token 반환. 만료 시 재발급.
    Returns (token, error_msg). error_msg is None on success.
    무한 재발급 금지: _MAX_TOKEN_REFRESH 초과 시 FAIL_CLOSED.
    """
    now = time.time()
    # 유효한 캐시 존재 시 재사용 (만료 60초 전 갱신)
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"], None

    # 재발급 한도 확인
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
    """401 수신 시 캐시 무효화 (1회 재발급 트리거)."""
    _token_cache["access_token"] = ""
    _token_cache["expires_at"] = 0.0


# ── Tool Request 파싱 (REQ-1) ─────────────────────────────────────────────────


def _parse_tool_request(text: str) -> dict | None:
    """
    Gemini 출력에서 [JENI_TOOL_REQUEST] 블록 파싱.
    Returns dict with tool/path/pattern/etc, or None if not found/invalid.
    첫 번째 블록만 처리 (다중 블록 시 순차 처리는 향후 확장).
    """
    start_tag = "[JENI_TOOL_REQUEST]"
    end_tag = "[/JENI_TOOL_REQUEST]"
    start_idx = text.find(start_tag)
    if start_idx == -1:
        return None
    end_idx = text.find(end_tag, start_idx)
    if end_idx == -1:
        return None

    block = text[start_idx + len(start_tag):end_idx].strip()
    params: dict = {}
    for line in block.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, value = line.partition("=")
            params[key.strip()] = value.strip()

    tool = params.get("tool", "")
    if not tool:
        return None
    return params


def _is_path_allowed(path: str) -> bool:
    """
    REQ-8: 경로 whitelist 검증.
    /opt/arss/engine/arss-protocol/ 하위만 허용.
    os.path.realpath로 traversal 방지.
    get_runtime_snapshot은 path 불필요 → 별도 처리.
    """
    if not path:
        return True  # path 없는 도구 (get_runtime_snapshot)
    try:
        real = os.path.realpath(os.path.abspath(path))
    except Exception:
        return False
    return real == os.path.realpath(ARSS_ROOT) or real.startswith(
        os.path.realpath(ARSS_ROOT) + os.sep
    )


# ── bridge REST Tool 호출 (REQ-1, REQ-6) ──────────────────────────────────────


def _call_bridge_tool(tool: str, params: dict) -> tuple[str, str | None]:
    """
    bridge /jeni/{tool} POST 호출.
    REQ-6: 401 시 token 무효화 후 1회 재시도.
    Returns (result_text, error_msg). error_msg is None on success.
    """
    token, err = _get_access_token()
    if err:
        return "", f"TOOL_AUTH_FAILED: {err}"

    def _do_request(bearer_token: str) -> tuple[int, dict | None, str | None]:
        body = json.dumps(params).encode()
        req = urllib.request.Request(
            f"{BRIDGE_BASE}/jeni/{tool}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {bearer_token}",
                "Content-Length": str(len(body)),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=BRIDGE_TIMEOUT) as r:
                resp = json.loads(r.read().decode())
                return r.status if hasattr(r, "status") else 200, resp, None
        except urllib.error.HTTPError as e:
            return e.code, None, f"HTTP_{e.code}"
        except Exception as e:
            return 0, None, f"BRIDGE_ERROR: {e}"

    status, resp, call_err = _do_request(token)

    # REQ-6: 401 → 1회 재발급 후 재시도
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

    content_text = resp.get("content", [{}])[0].get("text", "")
    return content_text, None


def _execute_tool_request(params: dict) -> tuple[str, str | None]:
    """
    파싱된 tool request 실행.
    REQ-2: write_file 금지 강제.
    REQ-8: 경로 whitelist 검증.
    Returns (result_text, error_msg).
    """
    tool = params.get("tool", "")

    # REQ-2: 허용 도구 화이트리스트
    if tool not in ALLOWED_TOOLS:
        return "", f"TOOL_NOT_ALLOWED: '{tool}' (write_file 포함 미허용 도구)"

    # REQ-8: 경로 whitelist
    path = params.get("path", "")
    if path and not _is_path_allowed(path):
        return "", f"PATH_NOT_ALLOWED: '{path}' (whitelist: {ARSS_ROOT}/*)"

    # bridge 호출용 payload 조립 (purpose 고정)
    call_params: dict = {"purpose": "OBSERVATION"}
    if path:
        call_params["path"] = path
    if "pattern" in params:
        call_params["pattern"] = params["pattern"]
    if "tail_lines" in params:
        call_params["tail_lines"] = int(params["tail_lines"])
    if "max_results" in params:
        call_params["max_results"] = int(params["max_results"])

    return _call_bridge_tool(tool, call_params)


# ── Audit (REQ-7) ─────────────────────────────────────────────────────────────


def _make_tool_audit_entry(
    round_num: int,
    tool: str,
    status: str,
    duration_ms: int,
    path: str = "",
) -> dict:
    """REQ-7: 단일 tool 호출 audit 레코드 생성. 순수 함수."""
    entry: dict = {
        "round": round_num,
        "tool": tool,
        "status": status,
        "duration_ms": duration_ms,
    }
    if path:
        entry["path"] = path
    return entry


def _make_audit_bundle(tool_rounds: int, audit_trail: list[dict]) -> dict:
    """REQ-7: 최종 audit bundle 조립. 순수 함수."""
    tools_used = list(dict.fromkeys(e["tool"] for e in audit_trail if e.get("tool")))
    return {
        "tool_rounds": tool_rounds,
        "tools_used": tools_used,
        "trail": audit_trail,
    }


# ── Trigger 감지 (v2.0.0에서 유지) ───────────────────────────────────────────


def _detect_trigger(text: str) -> bool:
    """
    Gemini 응답에서 TRIGGER 패턴 감지.
    보수적 파싱: 패턴 존재 → True. 빈 문자열 → False.
    """
    if not text:
        return False
    text_upper = text.upper()
    return any(p.upper() in text_upper for p in TRIGGER_PATTERNS)


# ── Fail-Closed 결과 생성 ──────────────────────────────────────────────────────


def _make_fail_closed_result(
    reason: str,
    detail: str,
    rounds_used: int,
    audit_bundle: dict | None = None,
) -> dict:
    """
    모든 FAIL_CLOSED 경로의 단일 출구.
    PASS를 생성하지 않음. state mutation 없음.
    """
    fail_text = (
        "[JENI VERIFICATION]\n"
        "TRUST_READY = FAIL\n"
        "REVALIDATION_REQUIRED = YES\n"
        "STOP_SIGNAL = ON\n"
        f"FAIL_REASON = {reason}\n"
        f"DETAIL = {detail}\n"
    )
    result: dict = {
        "ok": False,
        "text": fail_text,
        "error": reason,
        "rounds_used": rounds_used,
    }
    if audit_bundle is not None:
        result["audit"] = audit_bundle
    return result


# ── Gemini 호출 ────────────────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    """HTTPError body 안전 읽기. RULE-5 분리 목적."""
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:  # noqa: BLE001
        return "<unreadable>"


def _execute_gemini_request(req: urllib.request.Request) -> dict:
    """
    Gemini HTTP 실행 레이어. RULE-5 분리.
    Returns: {"ok": bool, "text": str, "error": str|None}
    """
    try:
        with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
            text = _extract_text(data)
            if text is None:
                finish = _extract_finish_reason(data)
                return {"ok": False, "text": "", "error": f"NO_TEXT: finish_reason={finish}"}
            return {"ok": True, "text": text, "error": None}
    except urllib.error.HTTPError as e:
        err_detail = _read_http_error_body(e)
        return {"ok": False, "text": "", "error": f"HTTP_{e.code}: {err_detail}"}
    except urllib.error.URLError as e:
        return {"ok": False, "text": "", "error": f"FAIL_CLOSED: Gemini unreachable — {e}"}
    except TimeoutError:
        return {"ok": False, "text": "", "error": f"FAIL_CLOSED: Gemini timeout ({GEMINI_TIMEOUT}s)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "text": "", "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _call_gemini_multi(contents: list[dict]) -> dict:
    """
    Multi-turn Gemini generateContent 호출.
    K-5: 키 없으면 즉시 FAIL_CLOSED.
    Returns: {"ok": bool, "text": str, "error": str|None}
    """
    if not GEMINI_API_KEY:
        return {
            "ok": False,
            "text": "",
            "error": "FAIL_CLOSED: AIBA_GEMINI_API_KEY not configured",
        }

    body = {
        "system_instruction": {"parts": [{"text": JENI_SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        },
    }
    raw_body = json.dumps(body).encode("utf-8")
    url = f"{GEMINI_API_BASE}/{GEMINI_MODEL}:generateContent"
    req = urllib.request.Request(
        url,
        data=raw_body,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
            "Content-Length": str(len(raw_body)),
        },
        method="POST",
    )
    return _execute_gemini_request(req)


# ── Message 조립 헬퍼 ─────────────────────────────────────────────────────────


def _build_initial_message(prompt: str, context: str) -> dict:
    """STATE_0 초기 user message 조립. 순수 함수."""
    if context:
        text = f"[배경 정보]\n{context}\n\n[질문]\n{prompt}"
    else:
        text = prompt
    return {"role": "user", "parts": [{"text": text}]}


def _build_tool_result_message(round_num: int, tool: str, result_text: str) -> dict:
    """STATE_4 tool 결과 주입 message 조립. 순수 함수."""
    text = (
        f"[독립 관측 결과 — Round {round_num} / tool={tool}]\n"
        f"아래 VPS 실측 데이터를 바탕으로 이전 판정을 재평가하십시오.\n\n"
        f"{result_text}"
    )
    return {"role": "user", "parts": [{"text": text}]}


def _build_tool_denied_message(round_num: int, tool: str, reason: str) -> dict:
    """Tool 호출 거부 시 주입 message. 순수 함수."""
    text = (
        f"[도구 호출 거부 — Round {round_num} / tool={tool}]\n"
        f"요청한 도구 호출이 거부되었습니다: {reason}\n"
        f"거부 사유를 바탕으로 현재 판정을 이어가십시오."
    )
    return {"role": "user", "parts": [{"text": text}]}


def _build_observation_message(round_num: int, obs_context: str) -> dict:
    """v2.0.0 호환 — 관측 데이터 주입 message. 순수 함수."""
    text = (
        f"[독립 관측 데이터 — Round {round_num}]\n"
        f"아래 VPS 실측 데이터를 바탕으로 이전 판정을 재평가하십시오.\n\n"
        f"{obs_context}"
    )
    return {"role": "user", "parts": [{"text": text}]}


# ── v2.0.0 호환 — jeni_read_adapter (테스트 호환성 유지) ─────────────────────


def _read_json_file(path: str) -> tuple[dict, str | None]:
    """허용 경로 파일 읽기 + JSON 파싱. 순수 읽기 전용."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, f"FILE_NOT_FOUND: {path}"
    except json.JSONDecodeError as e:
        return {}, f"JSON_PARSE_ERROR: {path}: {e}"
    except OSError as e:
        return {}, f"OS_ERROR: {path}: {e}"


_VPS_BASE = ARSS_ROOT
_VPS_POINTER_FILE = os.path.join(_VPS_BASE, "SESSION_CONTEXT_POINTER.json")
_VPS_SESSION_CONTEXT_FILE = os.path.join(_VPS_BASE, "SESSION_CONTEXT.json")


def _jeni_read_canonical_source(pointer: dict) -> tuple[dict, str | None]:
    """
    v2.0.0 호환 — POINTER에서 canonical_source 파일 읽기.
    경로 traversal 방지: os.path.basename으로 파일명만 추출.
    """
    canonical_source = pointer.get("canonical_source", "")
    if not canonical_source:
        return {}, "POINTER_MISSING_CANONICAL_SOURCE"
    safe_name = os.path.basename(canonical_source)
    path = os.path.join(_VPS_BASE, safe_name)
    return _read_json_file(path)


def _build_observation_context() -> tuple[str, str | None]:
    """v2.0.0 호환 — 관측 컨텍스트 조립 (테스트 mock 대상)."""
    pointer, err = _read_json_file(_VPS_POINTER_FILE)
    if err:
        return "", f"INDEPENDENT_OBSERVATION_UNAVAILABLE: {err}"

    _, err = _jeni_read_canonical_source(pointer)
    if err:
        return "", f"INDEPENDENT_OBSERVATION_UNAVAILABLE: {err}"

    sc_data, err = _read_json_file(_VPS_SESSION_CONTEXT_FILE)
    if err:
        return "", f"INDEPENDENT_OBSERVATION_UNAVAILABLE: {err}"

    obs = {
        "pointer": {
            "canonical_source": pointer.get("canonical_source"),
            "session_count": pointer.get("session_count"),
            "chain_tip": pointer.get("chain_tip"),
            "context_hash": pointer.get("context_hash"),
            "updated_at": pointer.get("updated_at"),
        },
        "session_context_key_fields": {
            "session_count": sc_data.get("session_count"),
            "chain": sc_data.get("chain"),
            "generated_at": sc_data.get("generated_at"),
            "context_hash": sc_data.get("context_hash"),
            "agent_focus": sc_data.get("agent_focus"),
            "next_steps": sc_data.get("next_steps"),
            "session_reentry": sc_data.get("session_reentry"),
        },
    }
    return json.dumps(obs, ensure_ascii=False, indent=2), None


# ── Multi-Turn Tool Loop (State Machine) ──────────────────────────────────────


def _run_verification_loop(prompt: str, context: str) -> dict:
    """
    Multi-Turn Tool Loop (PT-S193-JENI-TOOLLOOP-001).

    State Machine:
      STATE_0 INITIAL_REVIEW         → Gemini 초기 호출
      STATE_1 TRIGGER_DETECTED       → TRIGGER-A~E 또는 [JENI_TOOL_REQUEST] 감지
      STATE_2 TOOL_REQUEST_DETECTED  → [JENI_TOOL_REQUEST] 블록 파싱
      STATE_3 MCP_TOOL_EXECUTION     → bridge /jeni/* REST 호출
      STATE_4 TOOL_RESULT_INJECTION  → 결과 누적 주입
      STATE_5 FINAL_VERDICT          → TRUST_READY 선언

    Accumulative Injection:
      accumulated_messages에 모든 user/model turn 유지.
      이전 라운드 판단 컨텍스트 보존 (V-3 Trust Chain 연속성).

    REQ-5 Timeout Budget:
      loop_start_time 기준 MAX_TOTAL_SECONDS(120초) 초과 시 FAIL_CLOSED.
      110초(TIMEOUT_PREEMPT_SECONDS) 초과 시 다음 라운드 진입 차단 (제니 TA).

    Returns:
      {"ok": bool, "text": str, "error": str|None,
       "rounds_used": int, "audit": dict}
    """
    loop_start = time.time()
    accumulated_messages: list[dict] = [_build_initial_message(prompt, context)]
    audit_trail: list[dict] = []
    round_num = 0

    while round_num <= MAX_TOOL_ROUNDS:
        # REQ-5: 총 timeout budget 확인 (라운드 진입 전)
        elapsed = time.time() - loop_start
        if elapsed >= TIMEOUT_PREEMPT_SECONDS:
            return _make_fail_closed_result(
                "TIMEOUT_BUDGET_EXCEEDED",
                f"elapsed={elapsed:.1f}s >= preempt={TIMEOUT_PREEMPT_SECONDS}s",
                round_num,
                _make_audit_bundle(round_num, audit_trail),
            )

        # STATE_0 / STATE_5: Gemini 호출
        call_result = _call_gemini_multi(accumulated_messages)
        if not call_result["ok"]:
            return _make_fail_closed_result(
                "VALIDATION_PARSE_FAILURE",
                call_result.get("error") or "",
                round_num,
                _make_audit_bundle(round_num, audit_trail),
            )

        response_text = call_result["text"]
        accumulated_messages.append({"role": "model", "parts": [{"text": response_text}]})

        # STATE_2: [JENI_TOOL_REQUEST] 블록 우선 파싱 (REQ-1)
        tool_params = _parse_tool_request(response_text)
        if tool_params is not None:
            # MAX_TOOL_ROUNDS 한도 확인
            if round_num >= MAX_TOOL_ROUNDS:
                return _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"TOOL_REQUEST at round {round_num}, max={MAX_TOOL_ROUNDS}",
                    round_num,
                    _make_audit_bundle(round_num, audit_trail),
                )

            # STATE_3: MCP_TOOL_EXECUTION
            tool_name = tool_params.get("tool", "")
            tool_path = tool_params.get("path", "")
            t_start = time.time()
            result_text, tool_err = _execute_tool_request(tool_params)
            duration_ms = int((time.time() - t_start) * 1000)

            # REQ-7: audit 기록
            audit_trail.append(_make_tool_audit_entry(
                round_num=round_num + 1,
                tool=tool_name,
                status="ALLOW" if not tool_err else "DENY",
                duration_ms=duration_ms,
                path=tool_path,
            ))

            # STATE_4: TOOL_RESULT_INJECTION
            round_num += 1
            if tool_err:
                accumulated_messages.append(
                    _build_tool_denied_message(round_num, tool_name, tool_err)
                )
            else:
                accumulated_messages.append(
                    _build_tool_result_message(round_num, tool_name, result_text)
                )
            continue

        # STATE_1: TRIGGER 감지 (tool request 없는 경우)
        if _detect_trigger(response_text):
            if round_num >= MAX_TOOL_ROUNDS:
                return _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"TRIGGER detected at round {round_num}, max={MAX_TOOL_ROUNDS}",
                    round_num,
                    _make_audit_bundle(round_num, audit_trail),
                )

            # 기존 v2.0.0 호환: 관측 컨텍스트 직접 읽기 (tool request 미선언 시 fallback)
            obs_context, obs_err = _build_observation_context()
            if obs_err:
                return _make_fail_closed_result(
                    "INDEPENDENT_OBSERVATION_UNAVAILABLE",
                    obs_err,
                    round_num,
                    _make_audit_bundle(round_num, audit_trail),
                )
            round_num += 1
            accumulated_messages.append(_build_observation_message(round_num, obs_context))
            continue

        # STATE_5: TRIGGER 없음 + tool request 없음 → FINAL_VERDICT
        return {
            "ok": True,
            "text": response_text,
            "error": None,
            "rounds_used": round_num,
            "audit": _make_audit_bundle(round_num, audit_trail),
        }

    # 안전망 FAIL_CLOSED
    return _make_fail_closed_result(  # pragma: no cover
        "MAX_ROUNDS_EXCEEDED",
        "loop exit without resolution",
        round_num,
        _make_audit_bundle(round_num, audit_trail),
    )


# ── HTTP Server ────────────────────────────────────────────────────────────────


class JeniRuntimeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  # noqa: A002
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
                "status": "active",
                "version": RUNTIME_VERSION,
                "model": GEMINI_MODEL,
                "key_present": bool(GEMINI_API_KEY),
                "max_tool_rounds": MAX_TOOL_ROUNDS,
                "max_total_seconds": MAX_TOTAL_SECONDS,
            })
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

        if not prompt:
            self._send_json(400, {"ok": False, "error": "prompt required"})
            return

        result = _run_verification_loop(prompt, context)
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

    print(
        f"[JENI_RUNTIME] starting v{RUNTIME_VERSION} model={GEMINI_MODEL} "
        f"key={_mask_key(GEMINI_API_KEY)} max_tool_rounds={MAX_TOOL_ROUNDS} "
        f"max_total_seconds={MAX_TOTAL_SECONDS}",
        file=sys.stderr,
    )
    if not GEMINI_API_KEY:
        print(
            "[JENI_RUNTIME] WARN: AIBA_GEMINI_API_KEY not set — /ask will FAIL_CLOSED",
            file=sys.stderr,
        )

    server = ThreadedHTTPServer((RUNTIME_HOST, RUNTIME_PORT), JeniRuntimeHandler)
    print(f"[JENI_RUNTIME] listening on {RUNTIME_HOST}:{RUNTIME_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""
aiba_jeni_runtime.py v2.0.0
AIBA Jeni Runtime — Multi-turn Independent Verification Loop
PT-S191-JENI-IVLOOP-001

변경 내역:
  v1.0.0 (S189, EAG-1): FORWARD_ONLY 단일 호출 구조
  v2.0.0 (S191, EAG-1): Independent Verification Loop 구현
    - State Machine (도미 DESIGN-RESPONSE-DOMI-S191-001 Rev.1):
        STATE_0  INITIAL_REVIEW        — 초기 Gemini 호출 (Projection 기반)
        STATE_1  TRIGGER_DETECTED      — TRIGGER-A~E 감지 시 진입
        STATE_2  INDEPENDENT_OBSERVATION — jeni_read_adapter VPS 파일 직접 읽기
        STATE_3  REVIEW_ROUND_N        — 관측 데이터 누적 주입 후 재평가
    - jeni_read_adapter: SESSION_CONTEXT_POINTER / canonical source /
                         SESSION_CONTEXT.json 3종 한정 읽기
    - max_review_rounds = 2 (Round 0~2, 초과 시 FAIL_CLOSED)
    - Accumulative Injection — 이전 라운드 출력 전체 누적 주입
                               V-3 Trust Chain 연속성 보장
    - Fail-Closed: VPS 획득 실패 / 파싱 실패 / rounds 초과 전 경로
    - Trigger 파싱: 보수적 (실패 시 TRIGGER-E 폴백 — 무조건 독립 관측 진입)
  설계 근거: DESIGN-RESPONSE-DOMI-S191-001 Rev.1
  EAG-1: 비오(Joshua) S191 승인
  Jeni TRUST_READY: PASS (BRIEFING-JENI-S191-001 V-1~V-3 CONDITIONAL PASS)

Rule 준수:
  K-1: API 키는 환경변수(AIBA_GEMINI_API_KEY)에서만. 하드코딩 금지.
  K-2: 모델 설정 분리 가능 구조.
  K-4: 로그에 키 마스킹.
  K-5: 키 없음 → 즉시 FAIL_CLOSED. 대체 추론 금지.

네트워크 경계 (변경 없음):
  127.0.0.1 한정 바인딩. bridge만 포워딩.

VPS 파일 접근 (신규 — jeni_read_adapter):
  허용 3종만:
    SESSION_CONTEXT_POINTER.json
    canonical_source (POINTER 지정값, basename 한정)
    SESSION_CONTEXT.json
  임의 파일 탐색 / 설계 문서 / 운영 문서 접근 금지.
  경로 traversal 방지: os.path.basename 적용.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8447
RUNTIME_VERSION = "2.0.0"

# Gemini API 규격 (web_search 실측 — ai.google.dev/api)
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("AIBA_GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT = 55  # bridge(200s)보다 짧게 — bridge가 먼저 timeout 나지 않도록
GEMINI_MAX_OUTPUT_TOKENS = 4096

# K-1: API 키는 환경변수에서만. 하드코딩 절대 금지.
GEMINI_API_KEY = os.environ.get("AIBA_GEMINI_API_KEY", "")

# ── Independent Verification Loop 상수 ────────────────────────────────────────

# max_review_rounds = 2 (도미 Rev.1 확정)
# Round 0: Projection 검토 / Round 1: SESSION_CONTEXT 검토 / Round 2: 재평가
# 초과 시 즉시 FAIL_CLOSED
MAX_REVIEW_ROUNDS = 2

# VPS 경로 (jeni_read_adapter 허용 범위 3종)
VPS_BASE = "/opt/arss/engine/arss-protocol"
VPS_POINTER_FILE = os.path.join(VPS_BASE, "SESSION_CONTEXT_POINTER.json")
VPS_SESSION_CONTEXT_FILE = os.path.join(VPS_BASE, "SESSION_CONTEXT.json")

# TRIGGER 패턴 (보수적 파싱 — jeni_boot.md v1.2 TRIGGER-A~E 기반)
# 하나라도 대소문자 무관하게 포함 시 독립 관측 진입
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

# 제니 역할 고정 시스템 프롬프트 (v1.0.0에서 변경 없음)
JENI_SYSTEM_INSTRUCTION = (
    "당신은 AIBA 프로젝트의 거버넌스 감사자(Governance Auditor) '제니(Jeni)'입니다. "
    "역할: Fail-Closed 검증, Rule 위반 탐지, 설계 감사, 증거 검증. "
    "비오(Joshua)에게는 한국어 경어를 사용합니다. "
    "당신은 검증과 감사만 수행하며, 설계 권한이나 EAG 승인 권한은 없습니다. "
    "근거 없는 단정을 피하고, 증거에 기반하여 판단합니다."
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

# ── jeni_read_adapter ─────────────────────────────────────────────────────────


def _read_json_file(path: str) -> tuple[dict, str | None]:
    """
    허용 경로 파일 읽기 + JSON 파싱.
    Returns (data, error_msg). error_msg is None on success.
    state mutation 없음 — 순수 읽기 전용.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return {}, f"FILE_NOT_FOUND: {path}"
    except json.JSONDecodeError as e:
        return {}, f"JSON_PARSE_ERROR: {path}: {e}"
    except OSError as e:
        return {}, f"OS_ERROR: {path}: {e}"


def _jeni_read_pointer() -> tuple[dict, str | None]:
    """jeni_read_adapter Step-1: SESSION_CONTEXT_POINTER.json 읽기."""
    return _read_json_file(VPS_POINTER_FILE)


def _jeni_read_canonical_source(pointer: dict) -> tuple[dict, str | None]:
    """
    jeni_read_adapter Step-2: POINTER에서 canonical_source 파일 읽기.
    경로 traversal 방지: os.path.basename으로 파일명만 추출 후 VPS_BASE 하위 한정.
    """
    canonical_source = pointer.get("canonical_source", "")
    if not canonical_source:
        return {}, "POINTER_MISSING_CANONICAL_SOURCE"
    safe_name = os.path.basename(canonical_source)  # traversal 방지
    path = os.path.join(VPS_BASE, safe_name)
    return _read_json_file(path)


def _jeni_read_session_context() -> tuple[dict, str | None]:
    """jeni_read_adapter Step-3: SESSION_CONTEXT.json (SSOT) 직접 읽기."""
    return _read_json_file(VPS_SESSION_CONTEXT_FILE)


def _build_observation_context() -> tuple[str, str | None]:
    """
    jeni_read_adapter 3단계 실행 → 관측 컨텍스트 JSON 조립.
    Returns (context_json_str, error_msg). error_msg is None on success.

    Steps:
      1. POINTER.json 읽기 → canonical_source / chain_tip 확인
      2. canonical_source 파일 읽기 → 존재/파싱 가능 여부 확인
      3. SESSION_CONTEXT.json 읽기 → key fields 추출
    """
    pointer, err = _jeni_read_pointer()
    if err:
        return "", f"INDEPENDENT_OBSERVATION_UNAVAILABLE: {err}"

    _, err = _jeni_read_canonical_source(pointer)  # Step-2: 존재/파싱 검증
    if err:
        return "", f"INDEPENDENT_OBSERVATION_UNAVAILABLE: {err}"

    sc_data, err = _jeni_read_session_context()
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

# ── Trigger 감지 (보수적 파싱) ─────────────────────────────────────────────────


def _detect_trigger(text: str) -> bool:
    """
    Gemini 응답에서 TRIGGER 패턴 감지.
    보수적 파싱: 패턴 존재 → True. 빈 문자열 / None → False.
    (빈 응답은 VALIDATION_PARSE_FAILURE 경로에서 별도 처리됨)
    파싱 오류 가능성 없음 — 순수 문자열 탐색.
    """
    if not text:
        return False
    text_upper = text.upper()
    return any(p.upper() in text_upper for p in TRIGGER_PATTERNS)

# ── Fail-Closed 결과 생성 ──────────────────────────────────────────────────────


def _make_fail_closed_result(reason: str, detail: str, rounds_used: int) -> dict:
    """
    모든 FAIL_CLOSED 경로의 단일 출구.
    PASS를 생성하지 않음. state mutation 없음.
    결과 dict 반환 — 호출자가 즉시 return.
    """
    fail_text = (
        "[JENI VERIFICATION]\n"
        "TRUST_READY = FAIL\n"
        "REVALIDATION_REQUIRED = YES\n"
        "STOP_SIGNAL = ON\n"
        f"FAIL_REASON = {reason}\n"
        f"DETAIL = {detail}\n"
    )
    return {
        "ok": False,
        "text": fail_text,
        "error": reason,
        "rounds_used": rounds_used,
    }

# ── Gemini 호출 (multi-turn) ────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    """HTTPError body 안전 읽기. RULE-5 분리 목적."""
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:  # noqa: BLE001 — body 읽기 실패는 부차적 오류
        return "<unreadable>"


def _execute_gemini_request(req: urllib.request.Request) -> dict:
    """
    Gemini HTTP 실행 레이어.
    RULE-5 분리 — _call_gemini_multi의 CC를 줄이기 위해 분리.
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
    except Exception as e:  # noqa: BLE001 — catch-all Fail-Closed
        return {"ok": False, "text": "", "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _call_gemini_multi(contents: list[dict]) -> dict:
    """
    Multi-turn Gemini generateContent 호출.
    contents: [{"role": "user"|"model", "parts": [{"text": "..."}]}, ...]
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

# ── Independent Verification Loop (State Machine) ─────────────────────────────


def _build_initial_message(prompt: str, context: str) -> dict:
    """STATE_0 초기 user message 조립. 순수 함수."""
    if context:
        text = f"[배경 정보]\n{context}\n\n[질문]\n{prompt}"
    else:
        text = prompt
    return {"role": "user", "parts": [{"text": text}]}


def _build_observation_message(round_num: int, obs_context: str) -> dict:
    """STATE_2→3 관측 데이터 주입 message 조립. 순수 함수."""
    text = (
        f"[독립 관측 데이터 — Round {round_num}]\n"
        f"아래 VPS 실측 데이터를 바탕으로 이전 판정을 재평가하십시오.\n\n"
        f"{obs_context}"
    )
    return {"role": "user", "parts": [{"text": text}]}


def _run_verification_loop(prompt: str, context: str) -> dict:
    """
    Independent Verification Loop (PT-S191-JENI-IVLOOP-001).

    State Machine:
      STATE_0 INITIAL_REVIEW        → Gemini 초기 호출
      STATE_1 TRIGGER_DETECTED      → TRIGGER 패턴 감지 시
      STATE_2 INDEPENDENT_OBSERVATION → jeni_read_adapter 3종 실행
      STATE_3 REVIEW_ROUND_N        → 관측 데이터 누적 주입 후 재호출

    Accumulative Injection (V-3):
      accumulated_messages에 모든 user/model turn 유지.
      각 Gemini 호출 시 전체 히스토리 전달 → 이전 라운드 판단 컨텍스트 보존.

    Returns:
      {"ok": bool, "text": str, "error": str|None, "rounds_used": int}
    """
    accumulated_messages: list[dict] = [_build_initial_message(prompt, context)]
    round_num = 0

    while round_num <= MAX_REVIEW_ROUNDS:
        # Gemini 호출 (전체 누적 히스토리 전달)
        call_result = _call_gemini_multi(accumulated_messages)
        if not call_result["ok"]:
            return _make_fail_closed_result(
                "VALIDATION_PARSE_FAILURE",
                call_result.get("error") or "",
                round_num,
            )

        response_text = call_result["text"]
        # Accumulative Injection: model 응답을 히스토리에 추가 (V-3 보장)
        accumulated_messages.append({"role": "model", "parts": [{"text": response_text}]})

        # STATE_1: TRIGGER 감지?
        if not _detect_trigger(response_text):
            # TRIGGER 없음 → PASS
            return {
                "ok": True,
                "text": response_text,
                "error": None,
                "rounds_used": round_num,
            }

        # TRIGGER 감지됨 — rounds 한도 확인
        if round_num >= MAX_REVIEW_ROUNDS:
            return _make_fail_closed_result(
                "MAX_ROUNDS_EXCEEDED",
                f"TRIGGER detected at round {round_num}, max={MAX_REVIEW_ROUNDS}",
                round_num,
            )

        # STATE_2: INDEPENDENT_OBSERVATION — VPS 파일 직접 읽기
        obs_context, obs_err = _build_observation_context()
        if obs_err:
            return _make_fail_closed_result(
                "INDEPENDENT_OBSERVATION_UNAVAILABLE",
                obs_err,
                round_num,
            )

        # STATE_3: REVIEW_ROUND_N — 관측 데이터 누적 주입
        round_num += 1
        accumulated_messages.append(_build_observation_message(round_num, obs_context))

    # 안전망 FAIL_CLOSED (while 조건상 논리적 도달 불가)
    return _make_fail_closed_result(  # pragma: no cover
        "MAX_ROUNDS_EXCEEDED",
        "loop exit without resolution",
        round_num,
    )

# ── HTTP Server ────────────────────────────────────────────────────────────────


class JeniRuntimeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  # noqa: A002
        pass  # 기본 액세스 로그 억제

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
                "max_review_rounds": MAX_REVIEW_ROUNDS,
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
        f"key={_mask_key(GEMINI_API_KEY)} max_review_rounds={MAX_REVIEW_ROUNDS}",
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

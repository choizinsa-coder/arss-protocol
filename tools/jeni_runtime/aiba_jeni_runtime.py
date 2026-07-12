"""
aiba_jeni_runtime.py v4.11.0
AIBA Jeni Runtime — Persistent Autonomous Verification Agent
PT-S193-JENI-PERSIST-001

변경 내역:
  v1.0.0 (S189): FORWARD_ONLY 단일 호출
  v2.0.0 (S191): Independent Verification Loop (텍스트 TRIGGER 기반)
  v3.0.0 (S193): Multi-Turn Tool Loop ([JENI_TOOL_REQUEST] 텍스트 파싱)
  v4.0.0 (S193): Persistent Autonomous Agent 전면 재설계
  v4.1.0 (S199): Gemini 503 자동 재시도 1회 추가
  v4.4.0 (S211): NO_PARTS Exponential Backoff 재시도 3회 추가 (EAG-S211-JENI-001)
  v4.7.0 (S277): write_file + COLLAB_DIR 추가 (EAG-S277-DOMI-JENI-WRITE-001)
  v4.8.0 (S278): SC_FINAL 자동 로드 + JENI_SESSION_BOOT_PROTOCOL 주입
  v4.9.0 (S279): /observe 엔드포인트 추가 (EAG-S279-OBSERVE-001)
  v4.10.0 (S284): 503/429 _retry_http_with_backoff() 통일 (EAG-S284-JENI-RETRY-001)
  v4.11.1 (S289): /observe session_context 버그 수정 (EAG-S289-OBSERVE-FIX-001)
    - S279 유래 결함: _run_observe_loop ptr_text/sc_text MCP 브릿지 래퍼 이중 파싱 누락
    - _ptr_outer["content"] / _sc_outer["content"] 추출 후 재파싱 적용
  v4.11.0 (S288): EAG-S287-RUNTIME-STABILIZE-001 B/C/D 패치 (모델 미변경, A계층 보류)
    - B-J-1+C-5: SC_FINAL 캐시 POINTER hash + SC_FINAL mtime 이중 무효화
    - B-J-2: MAX_MEMORY_TURNS 20→5, MAX_FINDINGS_INJECT 10→3
    - B-J-3: MAX_TOOL_ROUNDS 5→8
    - B-J-4: MAX_TOTAL_SECONDS 120→180, TIMEOUT_PREEMPT 110→170
    - B-J-5: SC_FINAL 로드 실패 시 content=None → Fail-Closed 강제
    - C-1: Circuit Breaker (연속 동일 오류 2회 차단)
    - C-2: GEMINI_MAX_OUTPUT_TOKENS 4096→1500
    - C-4: Per-call 비용 관측 로그 (COST_LOG) + 일일 누적 추적
    - D-3: read_file 결과 20KB I/O 페이로드 캡
    - 제니 J-2: MAX_DAILY_USD 사전 차단기 (env 제어, 디폴트 1.0)
    - 모델/escalate 환경변수 구조 불변 (secrets.env 미변경)
  v4.11.5 (S344): 다중 function_calls 순차 처리 버그 수정 (EAG-S344-JENI-MULTIFC-FIX-001)
    - INC-S342-VERIFICATION-EVIDENCE-MISMATCH-001 근본원인 수정: fc=function_calls[0]만
      처리되고 나머지가 유실되던 결함 → 전체 순회 후 parts 통합 단일 메시지로 전송
  v4.11.6 (S344): Verification Trace Phase 2 연동 (EAG-S344-VTRACE-PHASE2-001)
    - INC-S342-VERIFICATION-EVIDENCE-MISMATCH-001 후속: 제니 응답 끝 JSON 블록을
      VerificationTraceRecord로 파싱/저장(선택적, 비파괴).
  설계 근거: AIBA_RUNTIME_OPTIMIZATION_S287.md v1.3 (EAG 승인본)
  EAG: EAG-S287-RUNTIME-STABILIZE-001 (A계층 보류, B/C/D 선행 — 비오 S288 지시)
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ── 상수 ──────────────────────────────────────────────────────────────────────

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = int(os.environ.get("AIBA_RUNTIME_PORT", "8447"))  # EAG-S401
RUNTIME_VERSION = "4.11.6"

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("AIBA_GEMINI_MODEL", "").strip()
GEMINI_MODEL_ESCALATE = os.environ.get("AIBA_GEMINI_MODEL_ESCALATE", "").strip()
GEMINI_TIMEOUT = int(os.environ.get("AIBA_LLM_TIMEOUT", "55"))  # EAG-S401
GEMINI_MAX_OUTPUT_TOKENS = 2500  # EAG-S316-TOKEN-FIX-001: 1500 → 2500 (효율 우선)

GEMINI_API_KEY = os.environ.get("AIBA_GEMINI_API_KEY", "")

# -- Vendor Abstraction Layer (EAG-S399-JENI-VENDOR-ABSTRACTION-001) --
# New AIBA_LLM_* envs take precedence; when absent, fall back to Gemini envs
# so existing deployments keep identical behaviour (_IS_GEMINI stays True).
LLM_BASE_URL = os.environ.get("AIBA_LLM_BASE_URL", "").strip() or GEMINI_API_BASE
LLM_MODEL = os.environ.get("AIBA_LLM_MODEL", "").strip() or GEMINI_MODEL
LLM_MODEL_ESCALATE = (os.environ.get("AIBA_LLM_MODEL_ESCALATE", "").strip()
                      or GEMINI_MODEL_ESCALATE)
LLM_API_KEY = os.environ.get("AIBA_LLM_API_KEY", "").strip() or GEMINI_API_KEY
LLM_MAX_TOKENS = int(os.environ.get("AIBA_LLM_MAX_TOKENS", "").strip()
                     or GEMINI_MAX_OUTPUT_TOKENS)
_IS_GEMINI = "generativelanguage.googleapis.com" in LLM_BASE_URL

GEMINI_503_RETRY_SLEEP = 2  # 503 재시도 대기 시간(초)
GEMINI_429_RETRY_MAX_SLEEP = 60  # 429 Retry-After 상한(초)

NO_PARTS_RETRY_MAX = 3          # NO_PARTS 재시도 최대 횟수 (EAG-S211-JENI-001)
NO_PARTS_RETRY_BASE_SLEEP = 2   # NO_PARTS 기반 대기 시간(초) — 2s/4s/8s

HTTP_RETRY_MAX = 3              # 503/429 재시도 최대 횟수 (EAG-S284-JENI-RETRY-001)
HTTP_RETRY_BASE_SLEEP = 2       # 503/429 기반 대기 시간(초) — 2s/4s/8s

MAX_TOOL_ROUNDS = 8             # B-J-3: 5 → 8
MAX_TOTAL_SECONDS = int(os.environ.get("AIBA_MAX_TOTAL_SECONDS", "180"))  # EAG-S401         # B-J-4: 120 → 180
TIMEOUT_PREEMPT_SECONDS = int(os.environ.get("AIBA_TIMEOUT_PREEMPT_SECONDS", "170"))  # EAG-S401   # B-J-4: 110 → 170

# C-4: 비용 단가 (env 오버라이드 가능). 디폴트 = gemini-2.5-pro 표준 단가.
GEMINI_COST_RATE_INPUT = float(os.environ.get("AIBA_GEMINI_COST_RATE_INPUT", "1.25"))
GEMINI_COST_RATE_OUTPUT = float(os.environ.get("AIBA_GEMINI_COST_RATE_OUTPUT", "10.00"))

# 제니 J-2: 일일 비용 하드 리밋 (env 제어). 디폴트 $1.0/일 (비오 비용 기준 반영).
MAX_DAILY_USD = float(os.environ.get("AIBA_MAX_DAILY_USD", "1.0"))
# CHANGE_ID: S287-J2-WARN (도미 ④ — 2단계 예산 가드: WARN 임계 = cap 80%)
MAX_DAILY_USD_WARN = float(os.environ.get("AIBA_MAX_DAILY_USD_WARN", str(round(MAX_DAILY_USD * 0.8, 5))))

MAX_FILE_BYTES = 20_000  # D-3: read_file 결과 페이로드 캡 (약 500줄)

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

# [GCB] 전역 서킷브레이커 연동 (EAG-S336-GCB-PHASE2-001)
if ARSS_ROOT not in sys.path:
    sys.path.insert(0, ARSS_ROOT)
try:
    from tools.governance.global_circuit_breaker import (
        gcb_check as _gcb_check,
        report_no_progress as _gcb_report_no_progress,
        report_progress as _gcb_report_progress,
        report_failure as _gcb_report_failure,
    )
except Exception:
    def _gcb_check():
        return False
    def _gcb_report_no_progress(component):
        return None
    def _gcb_report_progress(component):
        return None
    def _gcb_report_failure(component):
        return None

# [VTRACE] Verification Trace Phase 2 연동 (EAG-S344-VTRACE-PHASE2-001)
try:
    from tools.jeni_verify.verification_trace import VerificationTraceRecord
except Exception:
    VerificationTraceRecord = None

# ── Session Context Auto-Load (B-J-1 + C-5 + B-J-5) ──────────────────────────

# B-J-1 + C-5: POINTER hash + SC_FINAL mtime 이중 무효화 캐시
_sc_cache: dict = {
    "content": None,
    "loaded": False,
    "pointer_hash": "",
    "sc_final_mtime": 0.0,
    "loaded_at": 0.0,
}


def _get_pointer_hash() -> str:
    """POINTER.json 내용 hash (변경 감지용)."""
    try:
        with open(SESSION_POINTER_PATH, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _resolve_sc_final_path() -> str:
    """현재 POINTER 기준 SC_FINAL 경로 산출 (mtime 확인용)."""
    try:
        with open(SESSION_POINTER_PATH, encoding="utf-8") as f:
            pointer = json.load(f)
        last_session = pointer.get("last_session") or pointer.get("current_session")
        if last_session is None:
            return ""
        return os.path.join(ARSS_ROOT, f"SESSION_CONTEXT_S{last_session}_FINAL.json")
    except Exception:
        return ""


def _load_session_context() -> str | None:
    """
    CHANGE_ID: S287-BJ1 + S287-C5 + S287-BJ5
    SESSION_CONTEXT_POINTER.json → SC_FINAL 자동 로드.
    B-J-1: 캐시 유효 조건 = loaded AND pointer_hash 일치.
    C-5: SC_FINAL mtime 이중 확인 (POINTER 불변 + SC_FINAL 직접 수정 감지).
    B-J-5: 로드 실패 시 content=None 반환 → caller가 Fail-Closed 처리.
    """
    current_hash = _get_pointer_hash()
    sc_final_path = _resolve_sc_final_path()
    try:
        sc_mtime = os.path.getmtime(sc_final_path) if sc_final_path else 0.0
    except Exception:
        sc_mtime = 0.0

    # 캐시 유효성 (B-J-1 + C-5): hash 일치 AND mtime 1초 이내
    if (_sc_cache["loaded"]
            and _sc_cache["content"] is not None
            and _sc_cache["pointer_hash"] == current_hash
            and abs(_sc_cache["sc_final_mtime"] - sc_mtime) < 1.0):
        return _sc_cache["content"]

    # 캐시 무효화 → 재로드
    try:
        with open(SESSION_POINTER_PATH, encoding="utf-8") as f:
            pointer = json.load(f)
        last_session = pointer.get("last_session") or pointer.get("current_session")
        if last_session is None:
            raise ValueError("POINTER: last_session 키 없음")
        sc_path = os.path.join(
            ARSS_ROOT, f"SESSION_CONTEXT_S{last_session}_FINAL.json")
        with open(sc_path, encoding="utf-8") as f:
            sc_data = json.load(f)
        summary_keys = [
            "session_count", "chain", "next_steps", "agent_focus",
            "pytest_status", "session_reentry", "aif_v1_definition",
        ]
        sc_summary = {k: sc_data[k] for k in summary_keys if k in sc_data}
        sc_text = json.dumps(sc_summary, ensure_ascii=False, indent=2)
        boot_text = ""
        try:
            with open(BOOT_PROTOCOL_PATH, encoding="utf-8") as f:
                boot_text = f.read()
        except Exception:
            pass
        content = (
            "[JENI SESSION BOOT — SC_FINAL 자동 로드]\n"
            f"{sc_text}\n\n"
        )
        if boot_text:
            content += f"[JENI SESSION BOOT PROTOCOL]\n{boot_text}\n\n"
        _sc_cache["content"] = content
        _sc_cache["loaded"] = True
        _sc_cache["pointer_hash"] = current_hash
        _sc_cache["sc_final_mtime"] = sc_mtime
        _sc_cache["loaded_at"] = time.time()
        print(
            f"[JENI_RUNTIME] SC_FINAL loaded: session={last_session} "
            f"chain_tip={sc_data.get('chain', {}).get('tip', 'unknown')} "
            f"(pointer_hash={current_hash[:8]} mtime={sc_mtime:.0f})",
            file=sys.stderr)
        return content
    except Exception as e:
        # B-J-5: 빈 문자열이 아니라 None → Fail-Closed 신호
        _sc_cache["loaded"] = True
        _sc_cache["content"] = None
        _sc_cache["pointer_hash"] = ""
        _sc_cache["sc_final_mtime"] = 0.0
        print(f"[JENI_RUNTIME] CRITICAL: SC_FINAL load FAILED — {e} (FAIL_CLOSED)",
              file=sys.stderr)
        return None


# WRITE_SCOPE = SANDBOX_ONLY (문제 1)
SANDBOX_ROOT = os.environ.get("AIBA_SANDBOX_ROOT") or os.path.join(  # EAG-S401
    ARSS_ROOT, "tools/sandbox/jeni")
SANDBOX_ACTIVE = os.path.join(SANDBOX_ROOT, "active")
MEM_CONVERSATION_DIR = os.path.join(SANDBOX_ACTIVE, "conversation")
MEM_FINDINGS_DIR = os.path.join(SANDBOX_ACTIVE, "findings")
MEM_AUDITS_DIR = os.path.join(SANDBOX_ACTIVE, "audits")
MEM_STATE_DIR = os.path.join(SANDBOX_ACTIVE, "state")
MEM_STATE_FILE = os.path.join(MEM_STATE_DIR, "runtime_state.json")
MEM_TRACES_DIR = os.path.join(SANDBOX_ACTIVE, "traces")

MAX_MEMORY_TURNS = 5       # B-J-2: 20 → 5
MAX_FINDINGS_INJECT = 3    # B-J-2: 10 → 3
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
    "2. 코드 변경 검증 시 grep_scoped 로 실제 코드 패턴을 확인한다. "
    "단, grep_scoped 는 depth=2 제약이 있으며 PATH_DEPTH_EXCEEDED 오류 발생 시 "
    "해당 파일을 read_file 로 직접 읽어 패턴을 확인한다.\n"
    "3. 검증 없이 철학적 원칙만으로 TRUST_NOT_READY 판정 금지. "
    "반드시 실측 근거를 명시한다.\n"
    "4. TRUST_NOT_READY 판정 시 반드시 구체적 가드레일 위반 항목을 명시한다. "
    "미명시 시 TRUST_ADVISORY 로 자동 강등(실투 효력 없음).\n"
    "5. 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용된다.\n\n"
    "증거 수준: RAW(직접 읽음) / INFERRED(추측) / REPORTED(전달받음)\n\n"
    "이전 세션의 검증 이력(findings, audits, runtime_state)이 제공되면 "
    "맥락 연속성을 위해 참고하되, 이미 RESOLVED/CLOSED 처리된 항목이 "
    "현재의 독립적 판단을 편향시키지 않도록 주의하십시오."
    "[판정 우선 출력] 판정 요청 시 [JENI VERIFICATION] 블록을 응답 첫머리에 출력한다. 서론이나 세션 컨텍스트 확인 요약은 판정 이후에 두거나 생략한다. 토큰 한도 내에 판정 결론이 전달되는 것이 최우선이다."
    "\n\n[검증 추적, 선택사항] 판정 후 여유가 있다면, 인용한 근거별로 assertion_id(검증 대상 식별자), evidence_source(원문 파일 경로), evidence_snippet(원문 발취, 최대 200자), verdict(PASS 또는 FAIL 또는 INCONCLUSIVE) 네 항목을 담은 JSON 코드블록을 응답 끝에 추가할 수 있습니다. 이 블록은 선택사항이며, 없어도 판정 자체는 유효합니다."
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


# ── C-4: 비용 관측 로그 + 일일 누적 추적 (제니 J-2 Hard Limit) ────────────────

_daily_cost_tracker: dict = {"date": "", "total_usd": 0.0}

# ── EAG-S308-BUDGET-PERSIST-001: 일일 비용 파일 영속화 ────────────────────────
# 재시작 시 in-memory tracker가 0으로 초기화되어 일일 예산 가드가 무력화되는
# 결함(OI-S306-001) 해소. WF05_BUDGET_STATE.json 선행 패턴 준용.
DAILY_COST_STATE_PATH = os.environ.get(  # EAG-S401
    "AIBA_DAILY_COST_STATE_PATH") or os.path.join(
    ARSS_ROOT, "runtime/governance/budget/JENI_DAILY_COST_STATE.json")
DAILY_COST_SCHEMA = "DAILY_BUDGET_STATE_v1"
_cost_state_lock = threading.Lock()
_cost_state_loaded = False


def _persist_cost_state() -> None:
    """tmp 파일 → fsync → os.replace 원자적 쓰기. 호출자가 lock 보유 전제."""
    try:
        os.makedirs(os.path.dirname(DAILY_COST_STATE_PATH), exist_ok=True)
        payload = {
            "schema": DAILY_COST_SCHEMA,
            "date": _daily_cost_tracker["date"],
            "total_usd": round(_daily_cost_tracker["total_usd"], 6),
            "updated_at": _utc_now_iso(),
        }
        tmp = DAILY_COST_STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, DAILY_COST_STATE_PATH)
    except Exception as e:
        _emit_event({"tag": "COST_STATE_PERSIST_FAIL", "agent": "jeni",
                     "error": str(e)})


def _load_cost_state() -> None:
    """기동 시 1회 파일 복원. Fail-Open: 부재/손상 시 today 0.0으로 시작."""
    global _cost_state_loaded
    today = _today_str()
    try:
        with open(DAILY_COST_STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        stored_date = data.get("date", "")
        stored_total = float(data.get("total_usd", 0.0))
        if stored_date == today:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = stored_total
            _emit_event({"tag": "COST_STATE_RESTORED", "agent": "jeni",
                         "date": today, "total_usd": round(stored_total, 5)})
        else:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = 0.0
            _emit_event({"tag": "COST_STATE_NEW_DAY", "agent": "jeni",
                         "date": today, "prev_date": stored_date})
    except Exception as e:
        _daily_cost_tracker["date"] = today
        _daily_cost_tracker["total_usd"] = 0.0
        _emit_event({"tag": "COST_STATE_FAIL_OPEN", "agent": "jeni",
                     "date": today, "note": str(e)})
    _cost_state_loaded = True


def _emit_event(event: dict) -> None:
    """CHANGE_ID: S287-C4 — 운영 이벤트를 JSON Lines로 stderr 출력 (기계 분석 통일 포맷)."""
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _daily_budget_exceeded() -> bool:
    """제니 J-2: 당일 누적 비용이 MAX_DAILY_USD 초과 시 True (다음 호출 차단).
    EAG-S308-BUDGET-PERSIST-001: 날짜 경계 전환 시 파일에도 즉시 반영."""
    today = _today_str()
    if _daily_cost_tracker["date"] != today:
        with _cost_state_lock:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = 0.0
            _persist_cost_state()
    return _daily_cost_tracker["total_usd"] >= MAX_DAILY_USD


def _log_call_cost(model: str, usage: dict, session: str, round_num: int) -> float:
    """CHANGE_ID: S287-C4 / 도미 ③ — usage 부재 시 WARN(중단 금지). 출력은 JSON Lines."""
    if not usage:
        _emit_event({"tag": "COST_LOG", "level": "WARN", "agent": "jeni",
                     "session": session, "round": round_num, "model": model,
                     "note": "usage metadata missing, cost tracking skipped"})
        return 0.0
    inp = usage.get("promptTokenCount", 0)
    out = usage.get("candidatesTokenCount", 0)
    cost = (inp / 1_000_000 * GEMINI_COST_RATE_INPUT) + (out / 1_000_000 * GEMINI_COST_RATE_OUTPUT)
    today = _today_str()
    # EAG-S308-BUDGET-PERSIST-001: 누적 + 파일 영속화 (lock 보호, 원자적 쓰기)
    with _cost_state_lock:
        if _daily_cost_tracker["date"] != today:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = 0.0
        _daily_cost_tracker["total_usd"] += cost
        _persist_cost_state()
    _emit_event({"tag": "COST_LOG", "agent": "jeni", "session": session,
                 "round": round_num, "model": model, "input": inp, "output": out,
                 "est_usd": round(cost, 5),
                 "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                 "daily_cap": MAX_DAILY_USD})
    # CHANGE_ID: S287-J2-WARN / 도미 ④ — WARN 임계 도달 시 경고 (HARD 차단 전 가시성)
    if _daily_cost_tracker["total_usd"] >= MAX_DAILY_USD_WARN:
        _emit_event({"tag": "BUDGET_WARN", "agent": "jeni",
                     "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                     "warn": MAX_DAILY_USD_WARN, "cap": MAX_DAILY_USD})
    return cost


# ── OAuth Token ───────────────────────────────────────────────────────────────

_token_cache: dict = {"access_token": "", "expires_at": 0.0, "refresh_count": 0}
_MAX_TOKEN_REFRESH = None  # EAG-S211-OAUTH-001: None = 무제한 자동 재발급


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


def _truncate_tool_result(tool_name: str, result_text: str) -> str:
    """CHANGE_ID: S287-D3 — read_file 결과가 MAX_FILE_BYTES 초과 시 절단 + 경고."""
    if tool_name != "read_file":
        return result_text
    encoded = result_text.encode("utf-8")
    if len(encoded) <= MAX_FILE_BYTES:
        return result_text
    truncated = encoded[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
    return (
        truncated
        + "\n\n[WARNING: FILE TOO LARGE — TRUNCATED. "
        "Use grep_scoped to find specific patterns instead of reading the full file.]"
    )


def _execute_function_call(name: str, args: dict) -> tuple:
    if name not in ALLOWED_TOOLS:
        return "", f"TOOL_NOT_ALLOWED: '{name}'"
    if name == "write_file":
        target_path = args.get("target_path", "")
        content = args.get("content", "")
        if not target_path:
            return "", "WRITE_DENIED: target_path required"
        if not _is_write_allowed(target_path):
            return "", f"WRITE_DENIED: path not in jeni whitelist: {target_path}"
        return _call_bridge_tool("write_file", {"target_path": target_path, "content": content})
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
    result_text, err = _call_bridge_tool(name, call_params)
    # CHANGE_ID: S287-D3 (정정) — 원본만 반환. truncate는 _prepare_llm_tool_message에서만.
    return result_text, err


# ── C-1: Circuit Breaker — 연속 동일 오류 조기 종료 ──────────────────────────

# [CB-THRESHOLD-01] (EAG-S317-CB-ZPB-FIX-001):
_CB_THRESHOLDS: dict = {
    "AUTH_ERROR": 1,
    "FILE_ERROR": 2,
    "DEPTH_LIMIT_ERROR": 3,
    "TIMEOUT": 3,
}
_CB_THRESHOLD_DEFAULT = 2

_cb_error_type: str = ""
_cb_error_count: int = 0


def _reset_circuit_breaker() -> None:
    global _cb_error_type, _cb_error_count
    _cb_error_type = ""
    _cb_error_count = 0


def _classify_tool_error(tool_name: str, result_text: str) -> str:
    """도구 오류 유형 분류. 정상 결과는 "" 반환."""
    # OI-S315-002 fix (EAG-S316-CB-FIX-001): PATH_DEPTH_EXCEEDED -> DEPTH_LIMIT_ERROR
    if "PATH_DEPTH_EXCEEDED" in result_text or "PATH_NOT_IN_WHITELIST" in result_text:
        return f"DEPTH_LIMIT_ERROR:{tool_name}"
    if "NOT_A_FILE" in result_text or "DENIED" in result_text:
        return f"FILE_ERROR:{tool_name}"
    if "PERMISSION" in result_text or "403" in result_text:
        return f"AUTH_ERROR:{tool_name}"
    if "TIMEOUT" in result_text or "TIMED_OUT" in result_text:
        return f"TIMEOUT:{tool_name}"
    return ""


def _circuit_breaker_check(tool_name: str, result_text: str, round_num: int) -> bool:
    """CHANGE_ID: S287-C1 — 연속 동일 오류 2회 이상 발생 시 차단(True)."""
    global _cb_error_type, _cb_error_count
    err = _classify_tool_error(tool_name, result_text)
    if err == "":
        _cb_error_type = ""
        _cb_error_count = 0
        return False
    if err == _cb_error_type:
        _cb_error_count += 1
    else:
        _cb_error_type = err
        _cb_error_count = 1
    err_prefix = err.split(":")[0] if ":" in err else err
    threshold = _CB_THRESHOLDS.get(err_prefix, _CB_THRESHOLD_DEFAULT)
    if _cb_error_count >= threshold:
        _emit_event({"tag": "CIRCUIT_BREAKER", "agent": "jeni", "round": round_num,
                     "error_type": err, "count": _cb_error_count,
                     "threshold": threshold, "action": "ABORT"})
        return True
    return False


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


def _extract_and_persist_traces(session: str, response_text: str) -> None:
    # CHANGE_ID: S344-VTRACE-P2 -- 제니 응답 끝 JSON 블록을 VerificationTraceRecord로
    # 파싱/저장한다. 파싱 실패/데이터 없음/예외 발생 시 조용히 종료(비파괴).
    if VerificationTraceRecord is None:
        return
    pattern = r"```json\s*\n(.*?)\n```"
    matches = re.findall(pattern, response_text, re.DOTALL)
    if not matches:
        return
    records = []
    for block in matches:
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            item.setdefault("verifier_agent", "jeni")
            try:
                records.append(VerificationTraceRecord(**item))
            except (TypeError, ValueError):
                continue
    if not records:
        return
    try:
        os.makedirs(MEM_TRACES_DIR, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        fpath = os.path.join(MEM_TRACES_DIR, f"TRACE-{session}-{ts}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _persist_results(session: str, prompt: str, response_text: str,
                     audit_bundle: dict):
    failures = []
    if not _persist_conversation(session, prompt, response_text):
        failures.append("conversation")
    if not _persist_audit(session, audit_bundle):
        failures.append("audit")
    try:
        _extract_and_persist_traces(session, response_text)
    except Exception:
        pass
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


def _make_budget_block_result(detail: str) -> dict:
    """CHANGE_ID: S287-J2 / 도미 ④ — 예산 차단은 거버넌스 판정(TRUST_READY=FAIL)과 구분.
    verification_run=False 로 '검증 미실행(인프라 가드)'임을 명시하여 거버넌스 오인 방지."""
    text = (
        "[JENI RUNTIME — BUDGET GUARD]\n"
        "VERIFICATION_RUN = FALSE\n"
        "REASON = DAILY_BUDGET_EXCEEDED\n"
        f"DETAIL = {detail}\n"
        "NOTE = 제니의 설계 판정이 아니라 인프라 비용 가드에 의한 검증 미실행 상태입니다. "
        "예산 한도 조정 또는 DEP 승인 후 재요청하십시오.\n"
    )
    return {"ok": False, "text": text, "error": "DAILY_BUDGET_EXCEEDED",
            "budget_block": True, "verification_run": False, "rounds_used": 0}


# ── Gemini 호출 ────────────────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:
        return "<unreadable>"


def _execute_gemini_request(req: urllib.request.Request) -> dict:
    """Gemini API 단일 요청 실행.
    503/429 재시도 유지. NO_PARTS Exponential Backoff 재시도.
    C-4: 성공 응답에 usage(usageMetadata) 포함.
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
        parts = _extract_parts(data)
        if parts:
            return {"ok": True, "text": _extract_text_from_parts(parts),
                    "function_calls": _extract_function_calls(parts),
                    "parts": parts, "usage": data.get("usageMetadata", {}),
                    "error": None}

        finish = _extract_finish_reason(data)

        for retry_idx in range(NO_PARTS_RETRY_MAX):
            sleep_sec = NO_PARTS_RETRY_BASE_SLEEP * (2 ** retry_idx)
            if not _budget_ok(sleep_sec):
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "usage": {},
                        "error": "FAIL_CLOSED: NO_PARTS retry would exceed time budget"}
            time.sleep(sleep_sec)
            try:
                with urllib.request.urlopen(_new_req(), timeout=GEMINI_TIMEOUT) as r:
                    rd = json.loads(r.read().decode("utf-8"))
                    rp = _extract_parts(rd)
                    if rp:
                        return {"ok": True, "text": _extract_text_from_parts(rp),
                                "function_calls": _extract_function_calls(rp),
                                "parts": rp, "usage": rd.get("usageMetadata", {}),
                                "error": None}
                    finish = _extract_finish_reason(rd)
            except Exception as re_err:
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "usage": {},
                        "error": f"FAIL_CLOSED: NO_PARTS retry error — {re_err}"}

        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"NO_PARTS: finish_reason={finish} (after_{NO_PARTS_RETRY_MAX}_retries)"}

    def _retry_http_with_backoff(code: int) -> dict:
        tag = f"after_{code}_retry"
        for retry_idx in range(HTTP_RETRY_MAX):
            sleep_sec = HTTP_RETRY_BASE_SLEEP * (2 ** retry_idx)
            if not _budget_ok(sleep_sec):
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "usage": {},
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
                        "usage": {},
                        "error": f"HTTP_{e_r.code}: {_read_http_error_body(e_r)} ({tag})"}
            except Exception as e_r:
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "usage": {},
                        "error": f"FAIL_CLOSED: HTTP_{code} retry error — {e_r} ({tag})"}
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"HTTP_{code}: persisted after {HTTP_RETRY_MAX} retries ({tag})"}

    try:
        with urllib.request.urlopen(_new_req(), timeout=GEMINI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return _parse_response(data)
    except urllib.error.HTTPError as e:
        if e.code in (503, 429):
            return _retry_http_with_backoff(e.code)
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"HTTP_{e.code}: {_read_http_error_body(e)}"}
    except urllib.error.URLError as e:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"FAIL_CLOSED: Gemini unreachable — {e}"}
    except TimeoutError:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"FAIL_CLOSED: Gemini timeout ({GEMINI_TIMEOUT}s)"}
    except Exception as e:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _build_openai_tools() -> list:
    """EAG-S399: wrap Gemini-style declarations into OpenAI tools format."""
    return [{"type": "function", "function": f}
            for f in _build_function_declarations()]


def _openai_usage_to_gemini(usage: dict) -> dict:
    """EAG-S399: normalise OpenAI usage keys to the Gemini names so that
    _log_call_cost stays unmodified (minimal-edit decision)."""
    return {"promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0)}


def _gemini_contents_to_openai_messages(contents: list) -> list:
    """EAG-S399: adapter. Internal loop keeps Gemini contents format;
    this converts it to OpenAI messages just before the HTTP call.
    tool_call_id is threaded via the 'id' field stored on functionCall
    and functionResponse parts."""
    messages = [{"role": "system", "content": JENI_SYSTEM_INSTRUCTION}]
    for msg in contents:
        role = msg.get("role", "user")
        parts = msg.get("parts", [])
        texts = [p["text"] for p in parts if "text" in p]
        fcs = [p["functionCall"] for p in parts if "functionCall" in p]
        frs = [p["functionResponse"] for p in parts if "functionResponse" in p]
        if role == "model":
            entry = {"role": "assistant", "content": "".join(texts) or None}
            if fcs:
                entry["tool_calls"] = [
                    {"id": fc.get("id") or f"call_{i}", "type": "function",
                     "function": {"name": fc.get("name", ""),
                                  "arguments": json.dumps(fc.get("args", {}),
                                                          ensure_ascii=False)}}
                    for i, fc in enumerate(fcs)]
            messages.append(entry)
        elif frs:
            for fr in frs:
                resp = fr.get("response", {})
                if "result" in resp:
                    content = resp.get("result", "")
                else:
                    content = json.dumps(resp, ensure_ascii=False)
                messages.append({"role": "tool",
                                 "tool_call_id": fr.get("id", ""),
                                 "content": content})
        else:
            messages.append({"role": "user", "content": "\n\n".join(texts)})
    return messages


def _parse_openai_response(data: dict) -> dict:
    """EAG-S399: parse an OpenAI-compatible response into the SAME contract
    _call_gemini has always returned ({ok,text,function_calls,parts,usage,error})
    so _run_verification_loop stays untouched."""
    choices = data.get("choices", [])
    if not choices:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {}, "error": "NO_CHOICES"}
    msg = choices[0].get("message", {})
    text = msg.get("content") or ""
    function_calls = []
    parts = []
    if text:
        parts.append({"text": text})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except (json.JSONDecodeError, TypeError):
            args = {}
        fc = {"id": tc.get("id", ""), "name": fn.get("name", ""), "args": args}
        function_calls.append(fc)
        parts.append({"functionCall": fc})
    usage = _openai_usage_to_gemini(data.get("usage", {}) or {})
    finish_reason = choices[0].get("finish_reason", "")

    # EAG-S401: TRUNCATION GUARD.
    # A reasoning model can burn the whole output budget on reasoning and come
    # back with finish_reason="length" and NO content. Returning that as a
    # successful empty answer makes the verification loop treat "" as the final
    # verdict, and a model that was CUT OFF gets scored as a model that MISSED.
    # RAW: GLM-5.2 emitted exactly LLM_MAX_TOKENS output tokens and no content.
    # Same class as RC-E (EAG-S378). Fail-closed instead: ok=False routes to
    # _make_fail_closed_result("VALIDATION_PARSE_FAILURE"), which the scorer
    # already classifies as INFRA (excluded), never as a governance verdict.
    if finish_reason == "length":
        return {"ok": False, "text": text, "function_calls": function_calls,
                "parts": parts, "usage": usage,
                "error": "MAX_TOKENS_TRUNCATED: finish_reason=length "
                         "content_len=%d tool_calls=%d max_tokens=%d"
                         % (len(text), len(function_calls), LLM_MAX_TOKENS)}

    if not text and not function_calls:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": usage,
                "error": "EMPTY_RESPONSE: no content and no tool_calls "
                         "(finish_reason=%s)" % (finish_reason or "unknown")}

    return {"ok": True, "text": text, "function_calls": function_calls,
            "parts": parts,
            "usage": usage,
            "error": None}


def _call_llm_openai(contents: list, escalate: bool = False) -> dict:
    """EAG-S399: OpenAI-compatible vendor path. POST {base}/chat/completions.
    Same return contract as the native path. 503/429 exponential backoff."""
    if not LLM_API_KEY:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {}, "error": "FAIL_CLOSED: AIBA_LLM_API_KEY not configured"}
    model = LLM_MODEL_ESCALATE if escalate else LLM_MODEL
    body = {"model": model,
            "messages": _gemini_contents_to_openai_messages(contents),
            "tools": _build_openai_tools(),
            "temperature": 0,
            "max_tokens": LLM_MAX_TOKENS}
    raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = LLM_BASE_URL.rstrip("/") + "/chat/completions"
    started = time.time()
    last_err = "UNKNOWN"
    for attempt in range(HTTP_RETRY_MAX + 1):
        if attempt:
            sleep_sec = HTTP_RETRY_BASE_SLEEP * (2 ** (attempt - 1))
            if (time.time() - started) + sleep_sec >= min(GEMINI_TIMEOUT, MAX_TOTAL_SECONDS):
                return {"ok": False, "text": "", "function_calls": [], "parts": [],
                        "usage": {},
                        "error": f"FAIL_CLOSED: retry budget exceeded ({last_err})"}
            time.sleep(sleep_sec)
        req = urllib.request.Request(
            url, data=raw_body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {LLM_API_KEY}",
                     "Content-Length": str(len(raw_body))}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=GEMINI_TIMEOUT) as r:
                return _parse_openai_response(json.loads(r.read().decode("utf-8")))
        except urllib.error.HTTPError as e:
            if e.code in (503, 429):
                last_err = f"HTTP_{e.code}"
                continue
            return {"ok": False, "text": "", "function_calls": [], "parts": [],
                    "usage": {},
                    "error": f"HTTP_{e.code}: {_read_http_error_body(e)}"}
        except Exception as e:
            return {"ok": False, "text": "", "function_calls": [], "parts": [],
                    "usage": {}, "error": f"FAIL_CLOSED: LLM unreachable - {e}"}
    return {"ok": False, "text": "", "function_calls": [], "parts": [],
            "usage": {},
            "error": f"{last_err}: persisted after {HTTP_RETRY_MAX} retries"}


def _call_gemini(contents: list, escalate: bool = False) -> dict:
    """EAG-S399: vendor dispatch. Signature unchanged (existing TC mocks intact).
    Gemini path preserved verbatim in _call_gemini_native."""
    if _IS_GEMINI:
        return _call_gemini_native(contents, escalate)
    return _call_llm_openai(contents, escalate)


def _call_gemini_native(contents: list, escalate: bool = False) -> dict:
    if not GEMINI_API_KEY:
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "usage": {},
                "error": "FAIL_CLOSED: AIBA_GEMINI_API_KEY not configured"}
    _model = GEMINI_MODEL_ESCALATE if escalate else GEMINI_MODEL
    body = {
        "system_instruction": {"parts": [{"text": JENI_SYSTEM_INSTRUCTION}]},
        "contents": contents,
        "tools": [{"functionDeclarations": _build_function_declarations()}],
        "generationConfig": {"temperature": 0,
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


def _build_function_response_message(name: str, result_text: str, error,
                                     tool_call_id: str = "") -> dict:
    # EAG-S399: optional tool_call_id threading. Default "" keeps the exact
    # legacy Gemini shape (existing TCs unchanged).
    response_payload = {"error": error} if error else {"result": result_text}
    fr = {"name": name, "response": response_payload}
    if tool_call_id:
        fr["id"] = tool_call_id
    return {"role": "user", "parts": [{"functionResponse": fr}]}


def _prepare_llm_tool_message(name: str, result_text: str, error,
                              tool_call_id: str = "") -> dict:
    """CHANGE_ID: S287-D3 — LLM 전달 직전 토큰 보호 전담 (책임 분리).
    _execute_function_call은 원본만 반환하고, D-3 truncate는 오직 여기서만 수행한다.
    /observe 등 내부 JSON 파싱 경로는 이 함수를 거치지 않으므로 절단되지 않는다."""
    if not error:
        result_text = _truncate_tool_result(name, result_text)
    return _build_function_response_message(name, result_text, error, tool_call_id)


# ── Observe Loop (EAG-S279-OBSERVE-001) ──────────────────────────────────────


def _run_observe_loop(targets: list, session: str = "S000") -> dict:
    results: dict = {}
    errors: dict = {}

    for target in targets:
        try:
            if target == "session_context":
                ptr_text, ptr_err = _execute_function_call(
                    "read_file",
                    {"path": "/opt/arss/engine/arss-protocol/SESSION_CONTEXT_POINTER.json"}
                )
                if ptr_err:
                    errors[target] = f"POINTER_READ_FAILED: {ptr_err}"
                    continue
                import json as _json
                # S289-FIX (EAG-S289-OBSERVE-FIX-001):
                # _call_bridge_tool read_file 반환값은 MCP 브릿지 래퍼 포함:
                #   {"status":"ALLOW","path":"...","content":"<실제 파일 JSON>"}
                # outer["content"] 추출 후 재파싱해야 실제 POINTER 키에 접근 가능.
                _ptr_outer = _json.loads(ptr_text)
                _ptr_content = (
                    _ptr_outer.get("content", ptr_text)
                    if isinstance(_ptr_outer, dict) and "status" in _ptr_outer
                    else ptr_text
                )
                pointer = _json.loads(_ptr_content)
                last_session = pointer.get("last_session") or pointer.get("current_session")
                if last_session is None:
                    errors[target] = "POINTER: last_session 키 없음"
                    continue
                sc_path = (
                    f"/opt/arss/engine/arss-protocol/"
                    f"SESSION_CONTEXT_S{last_session}_FINAL.json"
                )
                sc_text, sc_err = _execute_function_call("read_file", {"path": sc_path})
                if sc_err:
                    errors[target] = f"SC_FINAL_READ_FAILED: {sc_err}"
                    continue
                # S289-FIX: 동일 MCP 브릿지 래퍼 구조 → content 추출 후 재파싱
                _sc_outer = _json.loads(sc_text)
                _sc_content = (
                    _sc_outer.get("content", sc_text)
                    if isinstance(_sc_outer, dict) and "status" in _sc_outer
                    else sc_text
                )
                sc_data = _json.loads(_sc_content)
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

    # [GCB] 진입 게이트: 전역 서킷브레이커 TRIPPED 시 진입 차단 (EAG-S336-GCB-PHASE2-001)
    try:
        if _gcb_check():
            return _make_fail_closed_result(
                "GCB_GLOBAL_TRIP",
                "Global Circuit Breaker is TRIPPED. EAG reset required. No auto-resume.",
                0, _make_audit_bundle(0, []))
    except Exception:
        pass

    # CHANGE_ID: S287-J2 / 제니 J-2 + 도미 ④ — 일일 예산 HARD 차단 (이벤트 로그 후 Fail-Closed)
    if _daily_budget_exceeded():
        _emit_event({"tag": "BUDGET_BLOCK", "agent": "jeni",
                     "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                     "cap": MAX_DAILY_USD, "action": "FAIL_CLOSED"})
        return _make_budget_block_result(
            f"daily_total={_daily_cost_tracker['total_usd']:.5f} >= cap={MAX_DAILY_USD:.2f} USD")

    # B-J-5: SC_FINAL 로드 실패 시 Fail-Closed
    sc_context = _load_session_context()
    if sc_context is None:
        return _make_fail_closed_result(
            "SC_CONTEXT_UNAVAILABLE",
            "SESSION_CONTEXT load failed. Manual recovery required.",
            0, _make_audit_bundle(0, []))

    _reset_circuit_breaker()  # C-1: 루프 시작 시 초기화
    memory = _load_memory_context()
    memory_preamble = _build_memory_preamble(memory)

    accumulated: list = [_build_initial_message(prompt, context, memory_preamble, sc_context)]
    audit_trail: list = []
    round_num = 0
    final_result = None

    while round_num <= MAX_TOOL_ROUNDS:
        elapsed = time.time() - loop_start
        if elapsed >= TIMEOUT_PREEMPT_SECONDS:
            try:
                _gcb_report_no_progress("jeni")
            except Exception:
                pass
            final_result = _make_fail_closed_result(
                "TIMEOUT_BUDGET_EXCEEDED",
                f"elapsed={elapsed:.1f}s >= preempt={TIMEOUT_PREEMPT_SECONDS}s",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        call_result = _call_gemini(accumulated, escalate=escalate)
        if not call_result["ok"]:
            try:
                _gcb_report_failure("jeni")
            except Exception:
                pass
            final_result = _make_fail_closed_result(
                "VALIDATION_PARSE_FAILURE", call_result.get("error") or "",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        # C-4: 비용 로그 + 일일 누적
        _log_call_cost(
            LLM_MODEL_ESCALATE if escalate else LLM_MODEL,
            call_result.get("usage", {}), session, round_num)

        model_parts = call_result["parts"]
        accumulated.append({"role": "model", "parts": model_parts})

        function_calls = call_result["function_calls"]
        if function_calls:
            if round_num >= MAX_TOOL_ROUNDS:
                try:
                    _gcb_report_no_progress("jeni")
                except Exception:
                    pass
                final_result = _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"function_call at round {round_num}, max={MAX_TOOL_ROUNDS}",
                    round_num, _make_audit_bundle(round_num, audit_trail))
                break

            all_parts = []
            cb_triggered = False
            for fc in function_calls:
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

                # C-1: Circuit Breaker (도구 결과 직후)
                cb_text = tool_err if tool_err else ""
                if _circuit_breaker_check(name, cb_text or "", round_num + 1):
                    tool_msg = _prepare_llm_tool_message(
                        name, result_text, tool_err, fc.get("id", ""))
                    all_parts.extend(tool_msg["parts"])
                    cb_triggered = True
                    break

                tool_msg = _prepare_llm_tool_message(
                    name, result_text, tool_err, fc.get("id", ""))
                all_parts.extend(tool_msg["parts"])

            round_num += 1

            if cb_triggered:
                try:
                    _gcb_report_failure("jeni")
                except Exception:
                    pass
                final_result = _make_fail_closed_result(
                    "CIRCUIT_BREAKER_TRIGGERED",
                    f"Consecutive same error x2: {_cb_error_type}. Escalate to Caddy.",
                    round_num, _make_audit_bundle(round_num, audit_trail))
                break

            if all_parts:
                accumulated.append({"role": "user", "parts": all_parts})
            continue

        try:
            _gcb_report_progress("jeni")
        except Exception:
            pass
        final_result = {"ok": True, "text": call_result["text"], "error": None,
                        "rounds_used": round_num,
                        "audit": _make_audit_bundle(round_num, audit_trail)}
        break

    if final_result is None:  # pragma: no cover
        try:
            _gcb_report_failure("jeni")
        except Exception:
            pass
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


# ── Model Deprecation Probe (EAG-S363-MODEL-PROBE-IMPL-001) ───────────────
# is_probe 격리: _call_gemini/서킷브레이커/일일예산가드 경로를 거치지 않는 독립 함수.
# 최소 페이로드 실호출로 primary/escalate 모델 가용성만 확인.


def _probe_single_model(model_name: str) -> dict:
    """단일 모델 최소 실호출 probe → {model, http_status, body}. 격리 경로."""
    if not model_name:
        return {"model": model_name, "http_status": 0, "body": "model id empty"}
    if not GEMINI_API_KEY:
        return {"model": model_name, "http_status": 0,
                "body": "API key not configured"}
    payload = {
        "contents": [{"role": "user", "parts": [{"text": "ping"}]}],
        "generationConfig": {"maxOutputTokens": 1, "temperature": 0},
    }
    raw = json.dumps(payload).encode("utf-8")
    url = f"{GEMINI_API_BASE}/{model_name}:generateContent"
    req = urllib.request.Request(
        url, data=raw,
        headers={"Content-Type": "application/json",
                 "x-goog-api-key": GEMINI_API_KEY,
                 "Content-Length": str(len(raw))}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return {"model": model_name,
                    "http_status": getattr(r, "status", 200), "body": ""}
    except urllib.error.HTTPError as e:
        return {"model": model_name, "http_status": e.code,
                "body": _read_http_error_body(e)}
    except Exception as e:
        return {"model": model_name, "http_status": 0,
                "body": f"probe_error: {e}"}


def _run_model_probe() -> dict:
    """primary + escalate 실호출 가용성 probe. 서킷브레이커/예산 미간섭."""
    results = []
    r_primary = _probe_single_model(GEMINI_MODEL)
    r_primary["model_type"] = "primary"
    results.append(r_primary)
    r_escalate = _probe_single_model(GEMINI_MODEL_ESCALATE)
    r_escalate["model_type"] = "escalate"
    results.append(r_escalate)
    return {"agent": "jeni", "probed_at": _utc_now_iso(), "results": results}


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
                "model": LLM_MODEL, "model_escalate": LLM_MODEL_ESCALATE,
                "llm_base_url": LLM_BASE_URL, "is_gemini": _IS_GEMINI,
                "key_present": bool(GEMINI_API_KEY),
                "max_tool_rounds": MAX_TOOL_ROUNDS,
                "max_total_seconds": MAX_TOTAL_SECONDS,
                "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
                "persistent_memory": True, "function_calling": True,
                "gemini_503_retry": True,
                "http_retry_backoff": "3x_2_4_8",
                "sc_context_loaded": _sc_cache["loaded"],
                "sc_cache_invalidation": "pointer_hash+sc_final_mtime",
                "circuit_breaker": True,
                "cost_log": True,
                "max_daily_usd": MAX_DAILY_USD,
                "daily_cost_total": round(_daily_cost_tracker["total_usd"], 5),
                "payload_cap_bytes": MAX_FILE_BYTES,
                "observe_endpoint": True})
            return
        if self.path == "/probe":
            self._send_json(200, _run_model_probe())
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
        self._send_json(200, result)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _validate_model_config() -> None:
    """기동 직전 1회 실행 — 모델 env 미설정/공백 시 FAIL_CLOSED (SSOT=secrets.env).
    EAG-S362-MODEL-SSOT-IMPL-001."""
    if not LLM_MODEL:
        raise RuntimeError(
            "FAIL_CLOSED: AIBA_LLM_MODEL/AIBA_GEMINI_MODEL not set. Check /etc/aiba/secrets.env (model SSOT).")
    if not LLM_MODEL_ESCALATE:
        raise RuntimeError(
            "FAIL_CLOSED: AIBA_LLM_MODEL_ESCALATE/AIBA_GEMINI_MODEL_ESCALATE not set. Check /etc/aiba/secrets.env (model SSOT).")


def main():
    import signal

    def _handle_shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    _validate_model_config()  # EAG-S362: secrets.env SSOT, 모델 미설정 시 FAIL_CLOSED
    _ensure_memory_dirs()
    _load_cost_state()  # EAG-S308-BUDGET-PERSIST-001: 일일 비용 파일 복원

    print(f"[JENI_RUNTIME] starting v{RUNTIME_VERSION} model={GEMINI_MODEL} "
          f"key={_mask_key(GEMINI_API_KEY)} max_tool_rounds={MAX_TOOL_ROUNDS} "
          f"max_total_seconds={MAX_TOTAL_SECONDS} max_output_tokens={GEMINI_MAX_OUTPUT_TOKENS} "
          f"circuit_breaker=True cost_log=True max_daily_usd={MAX_DAILY_USD} "
          f"persistent_memory=True function_calling=True sc_auto_load=True", file=sys.stderr)
    if not GEMINI_API_KEY:
        print("[JENI_RUNTIME] WARN: AIBA_GEMINI_API_KEY not set — /ask will FAIL_CLOSED",
              file=sys.stderr)

    server = ThreadedHTTPServer((RUNTIME_HOST, RUNTIME_PORT), JeniRuntimeHandler)
    print(f"[JENI_RUNTIME] listening on {RUNTIME_HOST}:{RUNTIME_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

"""
aiba_domi_runtime.py v1.6.1
AIBA Domi Runtime — Persistent Autonomous Design Agent
PT-S194-DOMI-RUNTIME-001

변경 내역:
  v1.0.0 (S194): 최초 생성
  v1.3.0 (S277): write_file + COLLAB_DIR 추가
  v1.4.0 (S278): SC_FINAL 자동 로드 + DOMI_SESSION_BOOT_PROTOCOL 주입
  v1.5.0 (S279): /observe 엔드포인트 추가 (EAG-S279-OBSERVE-001)
  v1.6.0 (S288): EAG-S287-RUNTIME-STABILIZE-001 B/C/D 패치 (모델 미변경, A계층 보류)
    - B-D-1+C-5: SC_FINAL 캐시 POINTER hash + mtime 이중 무효화
    - B-D-1b: SC 로드 실패 시 content=None → Fail-Closed (BOOT_PROTOCOL 명세 일치, P-08 해소)
    - B-D-2: MAX_TOOL_ROUNDS 5→8, MAX_TOTAL_SECONDS 120→180, TIMEOUT_PREEMPT 110→170
    - B-D-3+D-4: DOMI_SYSTEM_INSTRUCTION 최상단 OBS_PLAN 의무
    - B-D-4: VPS 실측 의무 0번 규칙 (경로 명시 시 즉시 read_file)
    - B-D-5: NOT_A_FILE 복구 지시
    - C-1: Circuit Breaker (연속 동일 오류 2회 차단)
    - C-2: OPENAI_MAX_OUTPUT_TOKENS 4096→2048 + OUTPUT_TRUNCATED 명시 지시
    - C-4: Per-call 비용 관측 로그 (COST_LOG, usage 부재 시 경고) + 일일 누적
    - D-1: visited_paths 중복 탐색 차단 (실행순서: 중복검사→실행→진척측정→visited추가)
    - D-2: Zero Progress Breaker (2라운드 무진전 조기 종료)
    - D-3: read_file 결과 20KB I/O 페이로드 캡 (양 런타임 일관성 — 교차리뷰 안건)
    - 도미 ④: 2단계 예산 가드 (WARN/HARD, verification과 구분)
    - 모델/escalate 환경변수 구조 불변 (secrets.env 미변경)
  설계 근거: AIBA_RUNTIME_OPTIMIZATION_S287.md v1.3 (EAG 승인본)
  EAG: EAG-S287-RUNTIME-STABILIZE-001 (A계층 보류, B/C/D 선행 — 비오 S288 지시)
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
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
RUNTIME_PORT = 8448
RUNTIME_VERSION = "1.7.11"

OPENAI_API_URL = "https://api.deepseek.com/v1/chat/completions"
OPENAI_MODEL = os.environ.get("AIBA_DOMI_MODEL", "gpt-4o-mini")
OPENAI_MODEL_ESCALATE = os.environ.get("AIBA_DOMI_MODEL_ESCALATE", "gpt-4o")
OPENAI_TIMEOUT = 55
OPENAI_MAX_OUTPUT_TOKENS = 4096  # EAG-S316-TOKEN-FIX-001: 2048 → 4096 (효율 우선)
OPENAI_HTTP_RETRY_MAX = 3        # EAG-S305-DOMI-RETRY-001: 503/429 재시도
OPENAI_HTTP_RETRY_BASE_SLEEP = 2 # 2s/4s/8s 지수 백오프

OPENAI_API_KEY = os.environ.get("AIBA_DOMI_API_KEY", "")

MAX_TOOL_ROUNDS = 8             # B-D-2: 5 → 8
MAX_TOTAL_SECONDS = 180         # B-D-2: 120 → 180
TIMEOUT_PREEMPT_SECONDS = 170   # B-D-2: 110 → 170

# C-4: 비용 단가 (env 오버라이드). 디폴트 = 현재 모델 gpt-4o-mini 실단가 (정확 측정).
DOMI_COST_RATE_INPUT = float(os.environ.get("AIBA_DOMI_COST_RATE_INPUT", "0.15"))
DOMI_COST_RATE_OUTPUT = float(os.environ.get("AIBA_DOMI_COST_RATE_OUTPUT", "0.60"))

# 도미 ④ / 제니 J-2: 일일 예산 가드 (env 제어). 디폴트 $1.0/일.
MAX_DAILY_USD = float(os.environ.get("AIBA_MAX_DAILY_USD", "1.0"))
# CHANGE_ID: S287-J2-WARN — 2단계 가드 WARN 임계 = cap 80%
MAX_DAILY_USD_WARN = float(os.environ.get("AIBA_MAX_DAILY_USD_WARN", str(round(MAX_DAILY_USD * 0.8, 5))))

MAX_FILE_BYTES = 20_000  # D-3: read_file 페이로드 캡

# ── Required Environment Variables — Hard-Stop (EAG-S290-HARDSTOP-001) ─────
# Fail-Closed 원칙: 아래 변수 중 하나라도 미설정 시 기동 거부 + FATAL 진단 출력.
# Required: 모델명·비용단가·일일예산·API키 — 모두 예산가드 정확성에 직결.
# Optional: MODEL_ESCALATE(gpt-4o 디폴트), MAX_DAILY_USD_WARN(80% 디폴트) 등.
_REQUIRED_ENVS = [
    "AIBA_DOMI_MODEL",             # 비용 단가 기준 모델명
    "AIBA_DOMI_COST_RATE_INPUT",   # 입력 토큰 단가 (USD/1M tokens)
    "AIBA_DOMI_COST_RATE_OUTPUT",  # 출력 토큰 단가 (USD/1M tokens)
    "AIBA_MAX_DAILY_USD",          # 일일 예산 한도 (USD)
    "AIBA_DOMI_API_KEY",           # Domi API 인증키
]


def _check_required_envs() -> None:
    """EAG-S290-HARDSTOP-001: Required env 미설정 시 기동 거부 (Fail-Closed 원칙).
    누락 변수를 명시적으로 출력하여 운영자가 즉시 조치 가능하도록 함."""
    missing = [k for k in _REQUIRED_ENVS if not os.environ.get(k)]
    if missing:
        print("[DOMI_RUNTIME] FATAL: Required environment variables not set.",
              file=sys.stderr)
        for k in missing:
            print(f"  Missing: {k}", file=sys.stderr)
        print(
            "  → Set missing variables in /etc/aiba/secrets.env "
            "and restart aiba-domi-runtime.service",
            file=sys.stderr,
        )
        sys.exit(1)


BRIDGE_BASE = "http://127.0.0.1:8443"

# -- ROOL 2단계 상수 (EAG-S297-ROOL2-IMPL-001) --------------------------------
# 제니 TRUST-ADVISORY: ROOL_TIMEOUT -- 네트워크 하드 타임아웃 5초 강제.
OBSERVE_BEGIN_ENDPOINT = BRIDGE_BASE + "/observe/begin"
OBSERVE_READ_ENDPOINT = BRIDGE_BASE + "/observe/read"
OBSERVATION_PURPOSE = "design"
ROOL_TIMEOUT = 5
BRIDGE_TOKEN_ENDPOINT = f"{BRIDGE_BASE}/token"
BRIDGE_TOKEN_TTL = 3600
BRIDGE_TIMEOUT = 15

DOMI_CLIENT_ID = os.environ.get("AIBA_DOMI_CLIENT_ID", "")
DOMI_CLIENT_SECRET = os.environ.get("AIBA_DOMI_CLIENT_SECRET", "")

ARSS_ROOT = "/opt/arss/engine/arss-protocol"

BOOT_PROTOCOL_PATH = os.path.join(
    ARSS_ROOT, "tools/design/DOMI_SESSION_BOOT_PROTOCOL.md")
SESSION_POINTER_PATH = os.path.join(ARSS_ROOT, "SESSION_CONTEXT_POINTER.json")

# ── Session Context Auto-Load (B-D-1 + C-5 + B-D-1b Fail-Closed) ─────────────

_sc_cache: dict = {
    "content": None,
    "loaded": False,
    "pointer_hash": "",
    "sc_final_mtime": 0.0,
    "loaded_at": 0.0,
}


def _get_pointer_hash() -> str:
    """POINTER.json 내용 hash."""
    try:
        with open(SESSION_POINTER_PATH, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception:
        return ""


def _resolve_sc_final_path() -> str:
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
    CHANGE_ID: S287-BD1 + S287-C5 + S287-BD1b
    B-D-1: POINTER hash 기반 캐시 무효화. C-5: SC_FINAL mtime 이중 확인.
    B-D-1b: 로드 실패 시 content=None → Fail-Closed (BOOT_PROTOCOL 명세 일치).
    """
    current_hash = _get_pointer_hash()
    sc_final_path = _resolve_sc_final_path()
    try:
        sc_mtime = os.path.getmtime(sc_final_path) if sc_final_path else 0.0
    except Exception:
        sc_mtime = 0.0

    if (_sc_cache["loaded"]
            and _sc_cache["content"] is not None
            and _sc_cache["pointer_hash"] == current_hash
            and abs(_sc_cache["sc_final_mtime"] - sc_mtime) < 1.0):
        return _sc_cache["content"]

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
            "[DOMI SESSION BOOT — SC_FINAL 자동 로드]\n"
            f"{sc_text}\n\n"
        )
        if boot_text:
            content += f"[DOMI SESSION BOOT PROTOCOL]\n{boot_text}\n\n"
        _sc_cache["content"] = content
        _sc_cache["loaded"] = True
        _sc_cache["pointer_hash"] = current_hash
        _sc_cache["sc_final_mtime"] = sc_mtime
        _sc_cache["loaded_at"] = time.time()
        print(
            f"[DOMI_RUNTIME] SC_FINAL loaded: session={last_session} "
            f"chain_tip={sc_data.get('chain', {}).get('tip', 'unknown')} "
            f"(pointer_hash={current_hash[:8]} mtime={sc_mtime:.0f})",
            file=sys.stderr)
        return content
    except Exception as e:
        _sc_cache["loaded"] = True
        _sc_cache["content"] = None
        _sc_cache["pointer_hash"] = ""
        _sc_cache["sc_final_mtime"] = 0.0
        print(f"[DOMI_RUNTIME] CRITICAL: SC_FINAL load FAILED — {e} (FAIL_CLOSED)",
              file=sys.stderr)
        return None


# WRITE_SCOPE = SANDBOX_ONLY
SANDBOX_ROOT = os.path.join(ARSS_ROOT, "tools/sandbox/domi")
SANDBOX_ACTIVE = os.path.join(SANDBOX_ROOT, "active")
MEM_CONVERSATION_DIR = os.path.join(SANDBOX_ACTIVE, "conversation")
MEM_FINDINGS_DIR = os.path.join(SANDBOX_ACTIVE, "findings")
MEM_DESIGNS_DIR = os.path.join(SANDBOX_ACTIVE, "designs")
MEM_AUDITS_DIR = os.path.join(SANDBOX_ACTIVE, "audits")
MEM_STATE_DIR = os.path.join(SANDBOX_ACTIVE, "state")
MEM_STATE_FILE = os.path.join(MEM_STATE_DIR, "runtime_state.json")

MAX_MEMORY_TURNS = 5
MAX_FINDINGS_INJECT = 3
MAX_DESIGNS_INJECT = 2
MAX_AUDITS_INJECT = 2

SANDBOX_QUOTA_BYTES = 50 * 1024 * 1024  # 50MB

COLLAB_DIR = os.path.join(ARSS_ROOT, "tools/sandbox/common/collab")

ALLOWED_TOOLS = frozenset({
    "read_file", "list_dir", "grep_scoped", "read_log", "get_runtime_snapshot",
    "write_file",
})

DOMI_SYSTEM_INSTRUCTION = (
    # CHANGE_ID: S287-BD3 + S287-D4 — OBS_PLAN 의무 (최상단)
    "[설계 계획 — 도구 호출 전 필수 출력]\n"
    "도구를 호출하기 전, 아래 형식의 관측 계획을 반드시 먼저 텍스트로 출력한다:\n"
    "  OBS_PLAN:\n"
    "  - 설계 목표: (무엇을 만드는가, 1줄)\n"
    "  - 읽을 파일 1: (정확한 경로) → 확인할 사실: (변수명/클래스명/설정값 등 단일 사실)\n"
    "  - 읽을 파일 2: (정확한 경로) → 확인할 사실: (단일 사실)\n"
    "  - 최대 Tool Budget: N 라운드\n"
    "  - 종료 조건: 위 '확인할 사실'이 모두 확보된 즉시, 잔여 Budget과 무관하게\n"
    "               [DESIGN] 출력을 시작한다. '충분히 이해함', '파악 완료' 등\n"
    "               주관적 표현 종료 조건 금지.\n"
    "계획 없이 도구 호출 금지. 계획 후에도 중복 경로 재방문 금지.\n\n"
    # 기존 정체성
    "당신은 AIBA 프로젝트의 설계 담당 에이전트(Design Architect) '도미(Domi)'입니다. "
    "역할: 시스템 설계, 아키텍처 결정, 프로토콜 설계, Bridge/Runtime/MCP 설계. "
    "비오(Joshua)에게는 한국어 경어를 사용합니다. "
    "당신은 설계만 수행하며, 실행 권한이나 EAG 승인 권한은 없습니다. "
    "코드를 직접 배포하거나 파일을 변경하지 않습니다.\n\n"
    "[VPS 실측 의무 — 설계 전 반드시 이행]\n"
    # CHANGE_ID: S287-BD4 — 경로 우선 탐색 (0번 규칙)
    "0. 설계 요청에 파일 경로가 명시된 경우, list_dir 탐색 없이 "
    "해당 경로를 즉시 read_file 로 읽는다. 경로 미명시 시에만 1번부터 시작한다.\n"
    "1. list_dir 로 디렉토리 구조를 파악한다 (경로 미명시 시에만).\n"
    "2. 설계 대상 파일을 read_file 로 반드시 직접 읽는다. "
    "list_dir 만으로 설계를 시작하는 것은 금지된다.\n"
    "3. grep_scoped 로 관련 코드 패턴을 확인한다. "
    "단, grep_scoped 는 depth=2 제약이 있으며 PATH_DEPTH_EXCEEDED 오류 발생 시 "
    "해당 파일을 read_file 로 직접 읽어 패턴을 확인한다.\n"
    "4. 실측 없이 추측한 설계는 INFERRED 로 명시하고 "
    "신뢰도가 낮음을 경고한다.\n"
    "5. 경로는 /opt/arss/engine/arss-protocol/ 하위만 허용된다.\n"
    # CHANGE_ID: S287-BD5 — NOT_A_FILE 복구
    "6. read_file 결과 NOT_A_FILE 또는 파일 없음 오류 발생 시: "
    "해당 경로의 부모 디렉토리를 list_dir 로 확인하여 올바른 경로를 탐색한다. "
    "동일 경로에 2회 이상 실패 시 관측 계획을 재수립한다.\n\n"
    "증거 수준: RAW(직접 읽음) / INFERRED(추측) / REPORTED(전달받음)\n\n"
    "출력 형식:\n"
    "[DESIGN]\n"
    "근거 파일: (read_file 로 읽은 파일 목록)\n"
    "evidence_level: RAW | INFERRED | REPORTED\n"
    "(설계 내용)\n\n"
    "[SELF-CRITIQUE]\n"
    "(미확인 사항, 한계, 추가 검증 필요 항목)\n"
    # CHANGE_ID: S287-C2 — 출력 절단 경고
    "출력이 길이 제한으로 절단될 경우 [SELF-CRITIQUE] 마지막에 "
    "'[OUTPUT_TRUNCATED: 설계 일부 누락. 재의뢰 필요]'를 명시한다.\n\n"
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
        {"type": "function", "function": {
            "name": "write_file",
            "description": "VPS 파일 쓰기. 허용 경로: tools/sandbox/domi/** 또는 tools/sandbox/common/collab/**. 에이전트 간 토론 결과를 collab/에 기록할 때 사용.",
            "parameters": {"type": "object", "properties": {
                "target_path": {"type": "string", "description": "쓸 파일의 절대 경로"},
                "content": {"type": "string", "description": "파일 내용"}},
                "required": ["target_path", "content"]}}},
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


# ── C-4: 비용 관측 로그 + 일일 누적 추적 (도미 ③ + 도미 ④) ────────────────────

_daily_cost_tracker: dict = {"date": "", "total_usd": 0.0}

# ── EAG-S308-BUDGET-PERSIST-001: 일일 비용 파일 영속화 ────────────────────────
# 재시작 시 in-memory tracker가 0으로 초기화되어 일일 예산 가드가 무력화되는
# 결함(OI-S306-001) 해소. WF05_BUDGET_STATE.json 선행 패턴 준용.
DAILY_COST_STATE_PATH = os.path.join(
    ARSS_ROOT, "runtime/governance/budget/DOMI_DAILY_COST_STATE.json")
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
        _emit_event({"tag": "COST_STATE_PERSIST_FAIL", "agent": "domi",
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
            _emit_event({"tag": "COST_STATE_RESTORED", "agent": "domi",
                         "date": today, "total_usd": round(stored_total, 5)})
        else:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = 0.0
            _emit_event({"tag": "COST_STATE_NEW_DAY", "agent": "domi",
                         "date": today, "prev_date": stored_date})
    except Exception as e:
        _daily_cost_tracker["date"] = today
        _daily_cost_tracker["total_usd"] = 0.0
        _emit_event({"tag": "COST_STATE_FAIL_OPEN", "agent": "domi",
                     "date": today, "note": str(e)})
    _cost_state_loaded = True


def _emit_event(event: dict) -> None:
    """CHANGE_ID: S287-C4 — 운영 이벤트를 JSON Lines로 stderr 출력 (기계 분석 통일 포맷)."""
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _daily_budget_exceeded() -> bool:
    """도미 ④: 당일 누적 비용이 MAX_DAILY_USD 초과 시 True.
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
        _emit_event({"tag": "COST_LOG", "level": "WARN", "agent": "domi",
                     "session": session, "round": round_num, "model": model,
                     "note": "usage metadata missing, cost tracking skipped"})
        return 0.0
    inp = usage.get("prompt_tokens", 0)
    out = usage.get("completion_tokens", 0)
    cost = (inp / 1_000_000 * DOMI_COST_RATE_INPUT) + (out / 1_000_000 * DOMI_COST_RATE_OUTPUT)
    today = _today_str()
    # EAG-S308-BUDGET-PERSIST-001: 누적 + 파일 영속화 (lock 보호, 원자적 쓰기)
    with _cost_state_lock:
        if _daily_cost_tracker["date"] != today:
            _daily_cost_tracker["date"] = today
            _daily_cost_tracker["total_usd"] = 0.0
        _daily_cost_tracker["total_usd"] += cost
        _persist_cost_state()
    _emit_event({"tag": "COST_LOG", "agent": "domi", "session": session,
                 "round": round_num, "model": model, "input": inp, "output": out,
                 "est_usd": round(cost, 5),
                 "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                 "daily_cap": MAX_DAILY_USD})
    # CHANGE_ID: S287-J2-WARN / 도미 ④ — WARN 임계 도달 시 경고
    if _daily_cost_tracker["total_usd"] >= MAX_DAILY_USD_WARN:
        _emit_event({"tag": "BUDGET_WARN", "agent": "domi",
                     "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                     "warn": MAX_DAILY_USD_WARN, "cap": MAX_DAILY_USD})
    return cost


# ── C-1: Circuit Breaker ──────────────────────────────────────────────────────

# [CB-THRESHOLD-01] (EAG-S317-CB-ZPB-FIX-001):
_CB_THRESHOLDS: dict = {
    "AUTH_ERROR": 1,
    "FILE_ERROR": 2,
    "DEPTH_LIMIT_ERROR": 3,
    "TIMEOUT": 3,
    "DUPLICATE": 3,
}
_CB_THRESHOLD_DEFAULT = 2

_cb_error_type: str = ""
_cb_error_count: int = 0


def _reset_circuit_breaker() -> None:
    global _cb_error_type, _cb_error_count
    _cb_error_type = ""
    _cb_error_count = 0


def _classify_tool_error(tool_name: str, result_text: str) -> str:
    # OI-S315-002 fix (EAG-S316-CB-FIX-001): PATH_DEPTH_EXCEEDED -> DEPTH_LIMIT_ERROR
    if "PATH_DEPTH_EXCEEDED" in result_text or "PATH_NOT_IN_WHITELIST" in result_text:
        return f"DEPTH_LIMIT_ERROR:{tool_name}"
    if "NOT_A_FILE" in result_text or "DENIED" in result_text:
        return f"FILE_ERROR:{tool_name}"
    if "PERMISSION" in result_text or "403" in result_text:
        return f"AUTH_ERROR:{tool_name}"
    if "TIMEOUT" in result_text or "TIMED_OUT" in result_text:
        return f"TIMEOUT:{tool_name}"
    if "DUPLICATE_ACTION" in result_text:
        return f"DUPLICATE:{tool_name}"
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
        _emit_event({"tag": "CIRCUIT_BREAKER", "agent": "domi", "round": round_num,
                     "error_type": err, "count": _cb_error_count,
                     "threshold": threshold, "action": "ABORT"})
        return True
    return False


# ── D-1: visited_paths 중복 차단 + D-2: Zero Progress Breaker ─────────────────

_visited_paths: set = set()
_progress_tracker: dict = {
    "new_files_read": 0,
    "new_facts_found": 0,
    "consecutive_no_progress": 0,
}


def _reset_loop_state() -> None:
    """루프 시작 시 D-1/D-2/C-1 상태 초기화."""
    _visited_paths.clear()
    _progress_tracker["new_files_read"] = 0
    _progress_tracker["new_facts_found"] = 0
    _progress_tracker["consecutive_no_progress"] = 0
    _reset_circuit_breaker()


def _is_error_response(text: str) -> bool:
    """ZPB 진척 판정용 오류 응답 감지."""
    if not text:
        return True
    markers = ("NOT_A_FILE", "DENIED", "PATH_NOT_ALLOWED", "TOOL_NOT_ALLOWED",
               "DUPLICATE_ACTION", "PERMISSION", "403", "TOOL_CALL_FAILED",
               "BRIDGE_ERROR", "TOOL_AUTH")
    return any(m in text for m in markers)


def _check_duplicate_action(tool_name: str, path_arg: str) -> str | None:
    """
    CHANGE_ID: S287-D1 — 중복 검사만 수행 (visited 추가는 진척 측정 후 별도).
    실행 순서: 중복검사(여기) → 도구실행 → 진척측정 → visited 추가.
    """
    if tool_name in ("read_file", "list_dir") and path_arg:
        if path_arg in _visited_paths:
            return (
                f"DUPLICATE_ACTION: {path_arg}는 이미 탐색한 경로입니다. "
                "다른 경로를 탐색하거나 지금 바로 [DESIGN]을 출력하십시오."
            )
    return None


def _measure_round_progress(tool_name: str, result_text: str, path_arg: str = "") -> bool:
    """
    CHANGE_ID: S287-D2 — 진척 측정 (visited 추가 전 호출).
    True 반환 시 → 2라운드 연속 무진전 → ZPB 발동.
    """
    made_progress = False
    if tool_name == "read_file":
        # S304-FIX (EAG-S304-DOMI-ZPB-FIX-001): _is_error_response가 성공한 read의
        # 파일 내용 속 "403"/"DENIED" 토큰을 오분류하여 허위 무진척 -> ZPB.
        # 에러 시 caller가 progress_text=""를 넘겨 len>100에서 자동 탈락하므로
        # 마커 스캔 제거. CB _classify_tool_error와 동일 종류 결함의 형제 수정.
        if (result_text  # [ZPB-ALGO-01] EAG-S317-CB-ZPB-FIX-001
                and path_arg not in _visited_paths):
            _progress_tracker["new_files_read"] += 1
            made_progress = True
    elif tool_name == "grep_scoped":
        # EAG-S292-ZPB-FIX-001: 정상 완료(오류 없음)이면 결과 0건도 진척으로 인정.
        # S304-FIX (EAG-S304-DOMI-ZPB-FIX-001): _is_error_response가 성공 grep 결과의
        # 마커 토큰을 오분류하므로, caller의 "에러 시 빈 문자열" 규약에 의존하여
        # 비어있지 않으면(성공) 진척으로 판정.
        if result_text:
            _progress_tracker["new_facts_found"] += 1
            made_progress = True

    if not made_progress:
        _progress_tracker["consecutive_no_progress"] += 1
    else:
        _progress_tracker["consecutive_no_progress"] = 0
    return _progress_tracker["consecutive_no_progress"] >= 2


# ── OAuth Token ───────────────────────────────────────────────────────────────

# -- ROOL 2단계 함수 (EAG-S297-ROOL2-IMPL-001) --------------------------------


def _begin_observation(session_id: str):
    """
    POST /observe/begin -> observation_id(str) 반환. 실패 시 None.
    호출자(_run_design_loop)에서 None -> FAIL-CLOSED 처리.
    제니 TRUST-ADVISORY: ROOL_TIMEOUT 5초 강제, 예외 시 Fail-Closed.
    CHANGE_ID: S297-ROOL2-BEGIN
    """
    token, err = _get_access_token()
    if err:
        _emit_event({"tag": "ROOL_BEGIN_FAIL", "agent": "domi",
                     "session": session_id, "reason": "OAUTH_FAILED:" + str(err)})
        return None
    try:
        body = json.dumps({"session": session_id}).encode()
        req = urllib.request.Request(
            OBSERVE_BEGIN_ENDPOINT, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token,
                     "Content-Length": str(len(body))}, method="POST")
        with urllib.request.urlopen(req, timeout=ROOL_TIMEOUT) as r:
            resp = json.loads(r.read().decode())
        if resp.get("status") == "ALLOW":
            obs_id = resp.get("observation_id", "")
            _emit_event({"tag": "ROOL_BEGIN", "agent": "domi",
                         "session": session_id,
                         "observation_id": obs_id[:12] + "..."})
            return obs_id
        _emit_event({"tag": "ROOL_BEGIN_FAIL", "agent": "domi",
                     "session": session_id,
                     "reason": resp.get("reason", "UNKNOWN")})
        return None
    except urllib.error.HTTPError as e:
        if e.code == 401:
            # 브리지 재시작 후 토큰 만료: 무효화 후 1회 재시도 (EAG-S311-DOMI-ROOL-FAILOPEN-001)
            _invalidate_token()
            token2, err2 = _get_access_token()
            if not err2:
                try:
                    body2 = json.dumps({"session": session_id}).encode()
                    req2 = urllib.request.Request(
                        OBSERVE_BEGIN_ENDPOINT, data=body2,
                        headers={"Content-Type": "application/json",
                                 "Authorization": "Bearer " + token2,
                                 "Content-Length": str(len(body2))}, method="POST")
                    with urllib.request.urlopen(req2, timeout=ROOL_TIMEOUT) as r2:
                        resp2 = json.loads(r2.read().decode())
                    if resp2.get("status") == "ALLOW":
                        obs_id2 = resp2.get("observation_id", "")
                        _emit_event({"tag": "ROOL_BEGIN", "agent": "domi",
                                     "session": session_id,
                                     "observation_id": obs_id2[:12] + "...",
                                     "note": "401_token_refresh_retry"})
                        return obs_id2
                except Exception:
                    pass
        _emit_event({"tag": "ROOL_BEGIN_FAIL", "agent": "domi",
                     "session": session_id, "reason": "HTTP_" + str(e.code)})
        return None
    except TimeoutError:
        _emit_event({"tag": "ROOL_BEGIN_FAIL", "agent": "domi",
                     "session": session_id,
                     "reason": "TIMEOUT:" + str(ROOL_TIMEOUT) + "s (FAIL_CLOSED)"})
        return None
    except Exception as e:
        _emit_event({"tag": "ROOL_BEGIN_FAIL", "agent": "domi",
                     "session": session_id, "reason": "EXCEPTION:" + str(e)})
        return None


def _call_rool_tool(observation_id: str, session_id: str, path: str) -> tuple:
    """
    POST /observe/read -> (result_text, error).
    제니 TRUST-ADVISORY: ROOL_TIMEOUT 5초 강제, 예외 시 ("", error) Fail-Closed.
    CHANGE_ID: S297-ROOL2-READ
    """
    token, err = _get_access_token()
    if err:
        return "", "ROOL_AUTH_FAILED: " + str(err)
    try:
        body = json.dumps({
            "observation_id": observation_id,
            "session": session_id,
            "path": path,
            "purpose": "OBSERVATION",
        }).encode()
        req = urllib.request.Request(
            OBSERVE_READ_ENDPOINT, data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token,
                     "Content-Length": str(len(body))}, method="POST")
        with urllib.request.urlopen(req, timeout=ROOL_TIMEOUT) as r:
            resp = json.loads(r.read().decode())
        if resp.get("isError"):
            content_text = resp.get("content", [{}])[0].get("text", "")
            return "", "ROOL_DENIED: " + content_text
        return resp.get("content", [{}])[0].get("text", ""), None
    except urllib.error.HTTPError as e:
        return "", "ROOL_HTTP_" + str(e.code)
    except TimeoutError:
        return "", ("ROOL_TIMEOUT: /observe/read exceeded "
                    + str(ROOL_TIMEOUT) + "s (FAIL_CLOSED)")
    except Exception as e:
        return "", "ROOL_ERROR: " + str(e)


_token_cache: dict = {"access_token": "", "expires_at": 0.0, "refresh_count": 0}
_MAX_TOKEN_REFRESH = None


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


def _execute_function_call(name: str, args: dict,
                            observation_id: str = "",
                            session_id: str = "") -> tuple:
    # CHANGE_ID: S297-ROOL2-EXECUTE -- observation_id/session_id 추가 (하위 호환)
    if name not in ALLOWED_TOOLS:
        return "", f"TOOL_NOT_ALLOWED: '{name}'"
    if name == "write_file":
        target_path = args.get("target_path", "")
        content = args.get("content", "")
        if not target_path:
            return "", "WRITE_DENIED: target_path required"
        if not _is_write_allowed(target_path):
            return "", f"WRITE_DENIED: path not in domi whitelist: {target_path}"
        return _call_bridge_tool("write_file", {"target_path": target_path, "content": content})
    # ROOL 2단계 (EAG-S297-ROOL2-IMPL-001): read_file -- ROOL 게이트 경유
    # CHANGE_ID: S297-ROOL2-READ-BRANCH
    # CHANGE_ID: S311-ROOL-READ-FAILOPEN (EAG-S311-ROOL-READ-FAILOPEN-001)
    # observation_id 있음 = ROOL /observe/read (실패 시 bridge Fail-Open → CB 차단)
    # observation_id 없음 = 기존 bridge 유지 (하위 호환)
    if name == "read_file":
        path = args.get("path", "")
        if path and not _is_path_allowed(path):
            return "", "PATH_NOT_ALLOWED: '" + path + "'"
        if observation_id:
            rool_result, rool_err = _call_rool_tool(observation_id, session_id, path)
            if rool_err:
                # Fail-Open: ROOL read 실패 → bridge 경로로 조용히 전환 (CB 차단)
                _emit_event({"tag": "ROOL_READ_FAIL_OPEN", "agent": "domi",
                             "session": session_id, "path": path,
                             "error": str(rool_err)[:120]})
                fo_params: dict = {"purpose": "OBSERVATION"}
                if path:
                    fo_params["path"] = path
                return _call_bridge_tool("read_file", fo_params)
            return rool_result, None
        call_params_rf: dict = {"purpose": "OBSERVATION"}
        if path:
            call_params_rf["path"] = path
        return _call_bridge_tool("read_file", call_params_rf)
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


def _make_budget_block_result(detail: str) -> dict:
    """CHANGE_ID: S287-J2 / 도미 ④ — 예산 차단을 설계 판정(DESIGN_READY=FAIL)과 구분."""
    text = (
        "[DOMI RUNTIME — BUDGET GUARD]\n"
        "DESIGN_RUN = FALSE\n"
        "REASON = DAILY_BUDGET_EXCEEDED\n"
        f"DETAIL = {detail}\n"
        "NOTE = 도미의 설계 판정이 아니라 인프라 비용 가드에 의한 설계 미실행 상태입니다. "
        "예산 한도 조정 또는 DEP 승인 후 재요청하십시오.\n"
    )
    return {"ok": False, "text": text, "error": "DAILY_BUDGET_EXCEEDED",
            "budget_block": True, "design_run": False, "rounds_used": 0}


# ── OpenAI 호출 ────────────────────────────────────────────────────────────────


def _read_http_error_body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8")[:500]
    except Exception:
        return "<unreadable>"


def _execute_openai_request(req: urllib.request.Request, loop_start: float = None) -> dict:
    # EAG-S305-DOMI-RETRY-001: 503/429 재시도(a) + 예산가드(e). 제니 정합.
    started_at = time.time()
    _orig_url = req.full_url
    _orig_data = req.data
    _orig_headers = dict(req.headers)

    def _new_req():
        return urllib.request.Request(
            _orig_url, data=_orig_data, headers=_orig_headers, method="POST")

    def _retry_budget_ok(next_backoff):
        base = loop_start if loop_start is not None else started_at
        elapsed = time.time() - base
        return (elapsed + OPENAI_TIMEOUT + next_backoff) < TIMEOUT_PREEMPT_SECONDS

    def _parse_ok(data):
        message = _extract_message(data)
        if not message:
            finish = _extract_finish_reason(data)
            return {"ok": False, "text": "", "tool_calls": [], "message": {},
                    "usage": {}, "error": f"NO_MESSAGE: finish_reason={finish}"}
        return {"ok": True, "text": _extract_text_from_message(message),
                "tool_calls": _extract_tool_calls(message),
                "message": message, "usage": data.get("usage", {}), "error": None}

    def _retry_http_with_backoff(code):
        tag = f"after_{code}_retry"
        for retry_idx in range(OPENAI_HTTP_RETRY_MAX):
            sleep_sec = OPENAI_HTTP_RETRY_BASE_SLEEP * (2 ** retry_idx)
            if not _retry_budget_ok(sleep_sec):
                return {"ok": False, "text": "", "tool_calls": [], "message": {},
                        "usage": {},
                        "error": f"FAIL_CLOSED: HTTP_{code} retry would exceed time budget ({tag})"}
            if _daily_budget_exceeded():
                return {"ok": False, "text": "", "tool_calls": [], "message": {},
                        "usage": {},
                        "error": f"FAIL_CLOSED: HTTP_{code} retry blocked by daily budget ({tag})"}
            time.sleep(sleep_sec)
            try:
                with urllib.request.urlopen(_new_req(), timeout=OPENAI_TIMEOUT) as resp_r:
                    data_r = json.loads(resp_r.read().decode("utf-8"))
                    return _parse_ok(data_r)
            except urllib.error.HTTPError as e_r:
                if e_r.code in (503, 429):
                    code = e_r.code
                    tag = f"after_{code}_retry"
                    continue
                return {"ok": False, "text": "", "tool_calls": [], "message": {},
                        "usage": {}, "error": f"HTTP_{e_r.code}: {_read_http_error_body(e_r)} ({tag})"}
            except Exception as e_r:
                return {"ok": False, "text": "", "tool_calls": [], "message": {},
                        "usage": {}, "error": f"FAIL_CLOSED: HTTP_{code} retry error — {e_r} ({tag})"}
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": f"HTTP_{code}: persisted after {OPENAI_HTTP_RETRY_MAX} retries ({tag})"}

    try:
        with urllib.request.urlopen(_new_req(), timeout=OPENAI_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return _parse_ok(data)
    except urllib.error.HTTPError as e:
        if e.code in (503, 429):
            return _retry_http_with_backoff(e.code)
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": f"HTTP_{e.code}: {_read_http_error_body(e)}"}
    except urllib.error.URLError as e:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": f"FAIL_CLOSED: OpenAI unreachable — {e}"}
    except TimeoutError:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": f"FAIL_CLOSED: OpenAI timeout ({OPENAI_TIMEOUT}s)"}
    except Exception as e:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": f"FAIL_CLOSED: unexpected error — {e}"}


def _call_openai(messages: list, escalate: bool = False, loop_start: float = None) -> dict:
    if not OPENAI_API_KEY:
        return {"ok": False, "text": "", "tool_calls": [], "message": {},
                "usage": {}, "error": "FAIL_CLOSED: AIBA_OPENAI_API_KEY not configured"}
    _model = OPENAI_MODEL_ESCALATE if escalate else OPENAI_MODEL
    body = {
        "model": _model,
        "messages": messages,
        "tools": _build_tools(),
        "max_tokens": OPENAI_MAX_OUTPUT_TOKENS,
    }
    raw_body = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        OPENAI_API_URL, data=raw_body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OPENAI_API_KEY}",
                 "Content-Length": str(len(raw_body))}, method="POST")
    return _execute_openai_request(req, loop_start)


# ── Message 조립 ──────────────────────────────────────────────────────────────


def _build_initial_messages(prompt: str, context: str, memory_preamble: str,
                            sc_context: str = "") -> list:
    segments = []
    if sc_context:
        segments.append(sc_context)
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


def _prepare_llm_tool_message(tool_name: str, tool_call_id: str, result_text: str, error) -> dict:
    """CHANGE_ID: S287-D3 — LLM 전달 직전 토큰 보호 전담 (책임 분리).
    _execute_function_call은 원본만 반환하고, D-3 truncate는 오직 여기서만 수행한다.
    /observe 등 내부 JSON 파싱 경로는 이 함수를 거치지 않으므로 절단되지 않는다."""
    if not error:
        result_text = _truncate_tool_result(tool_name, result_text)
    return _build_tool_response_message(tool_call_id, result_text, error)


# ── Observe Loop (EAG-S279-OBSERVE-001) ──────────────────────────────────────


def _run_observe_loop(targets: list, session: str = "S000") -> dict:
    # [S299-ROOL3-OBSERVE-001] ROOL Observation Session 시작
    obs_id = _begin_observation(session)
    if obs_id is None:
        return {
            "ok": False,
            "session": session,
            "results": {},
            "errors": {"__rool__": "ROOL_BEGIN_FAILED: /observe/begin \uc2e4\ud328"},
        }
    results: dict = {}
    errors: dict = {}

    for target in targets:
        try:
            if target == "session_context":
                ptr_text, ptr_err = _execute_function_call(
                    "read_file",
                    {"path": "/opt/arss/engine/arss-protocol/SESSION_CONTEXT_POINTER.json"},
                    obs_id,
                    session,
                )
                if ptr_err:
                    errors[target] = f"POINTER_READ_FAILED: {ptr_err}"
                    continue
                import json as _json
                # [S299-PARSE-FIX] bridge _handle_read_tool 래퍼 {status,content} 언랩
                _ptr_wrap = _json.loads(ptr_text)
                pointer = _json.loads(_ptr_wrap.get("content", "{}")) \
                    if isinstance(_ptr_wrap, dict) and "content" in _ptr_wrap \
                    else _ptr_wrap
                last_session = pointer.get("last_session") or pointer.get("current_session")
                if last_session is None:
                    errors[target] = "POINTER: last_session 키 없음"
                    continue
                sc_path = (
                    f"/opt/arss/engine/arss-protocol/"
                    f"SESSION_CONTEXT_S{last_session}_FINAL.json"
                )
                sc_text, sc_err = _execute_function_call(
                    "read_file", {"path": sc_path},
                    obs_id, session)
                if sc_err:
                    errors[target] = f"SC_FINAL_READ_FAILED: {sc_err}"
                    continue
                # [S299-PARSE-FIX] bridge _handle_read_tool 래퍼 {status,content} 언랩
                _sc_wrap = _json.loads(sc_text)
                sc_data = _json.loads(_sc_wrap.get("content", "{}")) \
                    if isinstance(_sc_wrap, dict) and "content" in _sc_wrap \
                    else _sc_wrap
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


def _run_design_loop(prompt: str, context: str, session: str = "S000", escalate: bool = False, max_rounds=None) -> dict:
    loop_start = time.time()

    # CHANGE_ID: S287-J2 / 도미 ④ — 일일 예산 HARD 차단 (이벤트 로그 후 Fail-Closed)
    if _daily_budget_exceeded():
        _emit_event({"tag": "BUDGET_BLOCK", "agent": "domi",
                     "daily_total": round(_daily_cost_tracker["total_usd"], 5),
                     "cap": MAX_DAILY_USD, "action": "FAIL_CLOSED"})
        return _make_budget_block_result(
            f"daily_total={_daily_cost_tracker['total_usd']:.5f} >= cap={MAX_DAILY_USD:.2f} USD")

    # B-D-1b: SC_FINAL 로드 실패 시 Fail-Closed
    sc_context = _load_session_context()
    if sc_context is None:
        return _make_fail_closed_result(
            "SC_CONTEXT_UNAVAILABLE",
            "SESSION_CONTEXT load failed. Manual recovery required.",
            0, _make_audit_bundle(0, []))

    # ROOL 2단계: OI-S311-001 해소 — 브리지 _get_read_hmac_secret() lazy 전환 완료
    # EAG-S313-ROOL-REACTIVATE-001
    obs_id = _begin_observation(session)
    if obs_id is None:
        _emit_event({"tag": "ROOL_BEGIN_FAIL_OPEN", "agent": "domi", "session": session,
                     "note": "ROOL begin 실패. bridge 경로로 Fail-Open."})

    _reset_loop_state()  # D-1/D-2/C-1 초기화
    memory = _load_memory_context()
    memory_preamble = _build_memory_preamble(memory)

    accumulated: list = _build_initial_messages(prompt, context, memory_preamble, sc_context)
    audit_trail: list = []
    round_num = 0
    final_result = None

    _effective_rounds = (
        max_rounds if (isinstance(max_rounds, int) and 1 <= max_rounds <= 20)
        else MAX_TOOL_ROUNDS
    )  # EAG-S318-ROUNDS-SCALE-001
    while round_num <= _effective_rounds:
        elapsed = time.time() - loop_start
        if elapsed >= TIMEOUT_PREEMPT_SECONDS:
            final_result = _make_fail_closed_result(
                "TIMEOUT_BUDGET_EXCEEDED",
                f"elapsed={elapsed:.1f}s >= preempt={TIMEOUT_PREEMPT_SECONDS}s",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        call_result = _call_openai(accumulated, escalate=escalate, loop_start=loop_start)
        if not call_result["ok"]:
            final_result = _make_fail_closed_result(
                "DESIGN_PARSE_FAILURE", call_result.get("error") or "",
                round_num, _make_audit_bundle(round_num, audit_trail))
            break

        # C-4: 비용 로그 + 일일 누적
        _log_call_cost(
            OPENAI_MODEL_ESCALATE if escalate else OPENAI_MODEL,
            call_result.get("usage", {}), session, round_num)

        model_message = call_result["message"]
        accumulated.append(model_message)

        tool_calls = call_result["tool_calls"]
        if tool_calls:
            if round_num >= MAX_TOOL_ROUNDS:
                final_result = _make_fail_closed_result(
                    "MAX_ROUNDS_EXCEEDED",
                    f"tool_call at round {round_num}, max={_effective_rounds}",
                    round_num, _make_audit_bundle(round_num, audit_trail))
                break

            cb_break = False
            zpb_break = False
            for tc in tool_calls:
                name = tc["name"]
                args = tc.get("args", {})
                path = args.get("path", "")

                # CHANGE_ID: S287-D1 — 실행 순서: ① 중복검사
                dup_err = _check_duplicate_action(name, path)
                t_start = time.time()
                if dup_err:
                    result_text, tool_err = "", dup_err
                else:
                    # ② 도구 실행 (CHANGE_ID: S297-ROOL2-LOOP-EXEC -- obs_id/session 전달)
                    result_text, tool_err = _execute_function_call(
                        name, args, obs_id, session)
                duration_ms = int((time.time() - t_start) * 1000)

                audit_trail.append(_make_tool_audit_entry(
                    round_num=round_num + 1, tool=name,
                    status="ALLOW" if not tool_err else "DENY",
                    duration_ms=duration_ms, path=path))
                # 모든 tool_call에 응답 (OpenAI 규약)
                accumulated.append(
                    _prepare_llm_tool_message(name, tc["id"], result_text, tool_err))

                # C-1: Circuit Breaker
                # S304-FIX (EAG-S304-DOMI-CB-FIX-001): 성공한 tool 결과(result_text=
                # 파일내용)를 분류기에 넘기면 파일 내용 속 "TIMEOUT"/"403"/"DENIED"
                # 토큰이 에러로 오분류되어 허위 CB가 발동함. 실제 실패(tool_err)에서만 분류.
                cb_text = tool_err if tool_err else ""
                if _circuit_breaker_check(name, cb_text or "", round_num + 1):
                    cb_break = True

                # CHANGE_ID: S287-D2 — ③ 진척 측정 (visited 추가 전)
                progress_text = "" if tool_err else result_text
                if _measure_round_progress(name, progress_text, path):
                    zpb_break = True

                # CHANGE_ID: S287-D1 — ④ visited 추가 (진척 측정 후, 중복 아닐 때만)
                if name in ("read_file", "list_dir") and path and not dup_err:
                    _visited_paths.add(path)

            if cb_break:
                final_result = _make_fail_closed_result(
                    "CIRCUIT_BREAKER_TRIGGERED",
                    f"Consecutive same error x2: {_cb_error_type}. Escalate to Caddy.",
                    round_num + 1, _make_audit_bundle(round_num + 1, audit_trail))
                break
            if zpb_break:
                _emit_event({"tag": "ZERO_PROGRESS_BREAKER", "agent": "domi",
                             "round": round_num + 1, "action": "FAIL_CLOSED"})
                final_result = _make_fail_closed_result(
                    "ZERO_PROGRESS_BREAKER",
                    "2라운드 연속 새로운 증거 없음. 확보 정보로 [DESIGN] 출력 또는 에스컬레이션.",
                    round_num + 1, _make_audit_bundle(round_num + 1, audit_trail))
                break

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
                "model": OPENAI_MODEL, "model_escalate": OPENAI_MODEL_ESCALATE,
                "key_present": bool(OPENAI_API_KEY),
                "max_tool_rounds": MAX_TOOL_ROUNDS,
                "max_tool_rounds_effective": MAX_TOOL_ROUNDS,  # EAG-S318-ROUNDS-SCALE-001
                "max_total_seconds": MAX_TOTAL_SECONDS,
                "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
                "persistent_memory": True, "function_calling": True,
                "sc_context_loaded": _sc_cache["loaded"],
                "sc_cache_invalidation": "pointer_hash+sc_final_mtime",
                "obs_plan": True,
                "visited_paths_guard": True,
                "zero_progress_breaker": True,
                "circuit_breaker": True,
                "cost_log": True,
                "max_daily_usd": MAX_DAILY_USD,
                "daily_cost_total": round(_daily_cost_tracker["total_usd"], 5),
                "payload_cap_bytes": MAX_FILE_BYTES,
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
        max_rounds = req_body.get("max_rounds", None)  # EAG-S318-ROUNDS-SCALE-001
        if not prompt:
            self._send_json(400, {"ok": False, "error": "prompt required"})
            return
        result = _run_design_loop(prompt, context, session, escalate=escalate, max_rounds=max_rounds)
        if not result.get("ok"):
            print(f"[DOMI_RUNTIME] FAIL: {result.get('error', 'unknown')}",
                  file=sys.stderr, flush=True)
        self._send_json(200, result)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    import signal

    def _handle_shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    _check_required_envs()  # EAG-S290-HARDSTOP-001: 기동 전 필수 env 검증
    _ensure_memory_dirs()
    _load_cost_state()  # EAG-S308-BUDGET-PERSIST-001: 일일 비용 파일 복원

    print(f"[DOMI_RUNTIME] starting v{RUNTIME_VERSION} model={OPENAI_MODEL} "
          f"key={_mask_key(OPENAI_API_KEY)} max_tool_rounds={MAX_TOOL_ROUNDS} "
          f"max_total_seconds={MAX_TOTAL_SECONDS} max_output_tokens={OPENAI_MAX_OUTPUT_TOKENS} "
          f"obs_plan=True visited_guard=True zpb=True circuit_breaker=True "
          f"cost_log=True max_daily_usd={MAX_DAILY_USD} "
          f"persistent_memory=True function_calling=True sc_auto_load=True", file=sys.stderr)
    if not OPENAI_API_KEY:
        print("[DOMI_RUNTIME] WARN: AIBA_OPENAI_API_KEY not set — /ask will FAIL_CLOSED",
              file=sys.stderr)

    server = ThreadedHTTPServer((RUNTIME_HOST, RUNTIME_PORT), DomiRuntimeHandler)
    print(f"[DOMI_RUNTIME] listening on {RUNTIME_HOST}:{RUNTIME_PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()

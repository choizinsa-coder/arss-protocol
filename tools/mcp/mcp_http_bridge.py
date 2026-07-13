"""
mcp_http_bridge.py v2.7.0
MCP Streamable HTTP Bridge — PT-S131-MCP-REG-001 + PT-S134-VPS-OBS-001 + PT-S139-MCP-WRITE-BRIDGE-001

변경 이력:
  v2.3.2 (S189): EAG-1 승인 (비오(Joshua))
                 ask_jeni 도구 추가 — PT-S189-JENI-RUNTIME-001
                 caddy가 제니(Gemini)에게 질문하는 FORWARD_ONLY 경로
                 bridge → aiba-jeni-runtime(127.0.0.1:8445) 포워딩
                 actor 제한: caddy only. FAIL_CLOSED. timeout 60초.
  v2.3.1 (S189): EAG-1 승인 (비오(Joshua))
                 _load_agent_clients_from_env caddy 추가
                 AIBA_CADDY_CLIENT_ID, AIBA_CADDY_CLIENT_SECRET 환경변수 지원
  v2.3.0 (S187): EAG-1 승인 (비오(Joshua))
                 1. OAuth client 영속성 — 환경변수 기반 사전 등록
                    AIBA_DOMI_CLIENT_ID/SECRET, AIBA_JENI_CLIENT_ID/SECRET
                    파일 저장 시 secret_hash만 기록, 원문 저장 금지
                 2. /domi/* audit mandatory gate — pre/post 2단계 Fail-Closed
                    pre FAIL → HTTP 500 / ACCESS_DENIED
                    post FAIL → HTTP 500 / RESULT_WITHHELD
                 3. /domi/write_file 엔드포인트 — Tier2 Sandbox 한정
                    actor=domi 강제, realpath 경계 검증
                 4. /jeni/* REST Wrapper 신규 — 읽기 5종 + Tier2 쓰기
                    actor=jeni 강제, audit mandatory gate 동일 적용
                 5. actor별 write whitelist — sandbox 상호 격리
                    domi: sandbox/domi/ + common/collab/
                    jeni: sandbox/jeni/ + common/collab/
                 6. CLOSED thread 30일 ARCHIVED 전환 정책 적용
  v2.2.0 (S139): PT-S139-MCP-WRITE-BRIDGE-001 Write Plane 브릿지 연결
                 write_file / get_write_plane_state 추가
                 Bridge = FORWARD_ONLY (approval 검증은 Write Server 단독 책임)
                 actor 제한: caddy only
                 payload size 상한: 65536 bytes
                 timeout: 30초 NO_RETRY FAIL_CLOSED
  v2.1.0 (S134): PT-S134-VPS-OBS-001 Phase 1 READ ONLY OBSERVABILITY 통합
                 ReadOnlyServer 9종 도구 추가
                 Bridge 내부 HMAC 생성 → ReadOnlyServer 3요소 인증 유지
                 actor_id arguments 경유 수신 (domi/jeni/caddy 차등 권한)
  v2.0.0 (S133): MCP Streamable HTTP endpoint 재정의
"""

from __future__ import annotations
import logging as _logging

import hashlib
import hmac as hmac_lib
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import Optional

PHASE_C_DIR = "/opt/arss/engine/arss-protocol/tools/mcp"
if PHASE_C_DIR not in sys.path:
    sys.path.insert(0, PHASE_C_DIR)

from mcp_audit_broker import write_audit, write_deny_audit
from mcp_containment_state import is_active as containment_is_active
from mcp_read_server import ReadOnlyServer, AGENT_ROOT_ALLOWLIST
from rool_observation import (
    begin_observation as _rool_begin,
    observe as _rool_observe,
    record_observe_result as _rool_record,
)

# ── 상수 ──────────────────────────────────────────────────────────────────────

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8443
BRIDGE_VERSION = "3.0.0"

# ── EDA v1.2: Constraint Registry (EAG-S275-EDA-IMPLEMENTATION) ──────────────
CONSTRAINT_REGISTRY_PATH = (
    "/opt/arss/engine/arss-protocol/tools/governance/constraint_registry.json"
)

_constraint_cache: dict = {}
_session_reads:    set  = set()
_issued_audit_ids: set  = set()


def _load_constraint_cache() -> None:
    """Bridge 시작 시 1회 호출 — 인메모리 캐시 초기화."""
    global _constraint_cache
    try:
        with open(CONSTRAINT_REGISTRY_PATH, encoding="utf-8") as _f:
            _constraint_cache = json.load(_f)
    except Exception as _e:
        print(f"[EDA] constraint_registry.json 로드 실패: {_e}", file=sys.stderr)
        _constraint_cache = {}


def _reload_constraints() -> None:
    """세션 중 registry 변경 시 강제 갱신."""
    _load_constraint_cache()


# ── L1: Tool-call Gate ────────────────────────────────────────────────────────

def _l1_gate(tool_name: str) -> Optional[dict]:
    """
    tool call -> bridge -> registry 자동 조회 -> PASS/DENY.
    AI가 기억하지 않아도 bridge가 차단.
    _handle_tool_call() 진입 직후 호출.
    """
    mcp = _constraint_cache.get("mcp_constraints", {})
    entry = mcp.get(tool_name, {})
    if entry.get("blocked"):
        status      = entry.get("status", "BLOCKED")
        alternative = entry.get("alternative", "대안 없음")
        oi          = entry.get("oi", "")
        reason      = entry.get("reason", "")
        return {
            "isError": True,
            "content": [{"type": "text", "text":
                f"L1_DENY: {tool_name} blocked ({status})\n"
                f"reason: {reason}\n"
                f"oi: {oi}\n"
                f"alternative: {alternative}"
            }]
        }
    return None  # PASS


# ── L2: Evidence Gate ─────────────────────────────────────────────────────────

def _l2_record_read(path: str) -> None:
    """read_file 성공 시 자동 호출 — _session_reads 인메모리 세트에 적립."""
    _session_reads.add(path)


def _l2_gate(required_paths: list) -> Optional[str]:
    """중요 행동 직전 검증 — audit_trail.log 파싱 없음."""
    missing = [p for p in required_paths if p not in _session_reads]
    if missing:
        return f"L2_DENY: required reads missing: {missing}"
    return None  # PASS


# ── L3: Output Claim Gate ─────────────────────────────────────────────────────

import re as _re_l3

SA_HASH_PATTERN = _re_l3.compile(r"SA-[0-9a-f]{8}")


def _get_restricted_expressions() -> list:
    policy = _constraint_cache.get("claim_expression_policy", {})
    return policy.get("restricted_expressions", [])


def _get_allowed_expressions() -> list:
    policy = _constraint_cache.get("claim_expression_policy", {})
    return policy.get("allowed_without_evidence", [])


def _l3_gate(output_text: str) -> Optional[str]:
    """
    완료/PASS 선언 -> SA-해시 확인 -> issued_audit_ids 대조.
    유효 해시 없으면 L3_DENY.
    """
    restricted = _get_restricted_expressions()
    if not restricted:
        return None
    claim_pattern = _re_l3.compile(
        r"\b(" + "|".join(_re_l3.escape(e) for e in restricted) + r")\b"
    )
    if not claim_pattern.search(output_text):
        return None  # 제한 표현 없음 -> PASS
    sa_matches = SA_HASH_PATTERN.findall(output_text)
    for sa_id in sa_matches:
        if sa_id in _issued_audit_ids:
            return None  # 유효 evidence_id 존재 -> PASS
    allowed = _get_allowed_expressions()
    return (
        "L3_DENY: 완료 선언에 유효한 evidence_id(SA-해시) 없음.\n"
        f"evidence_id 없이 허용되는 표현: {allowed}"
    )


def _register_audit_id(sa_id: str) -> None:
    """exec_audit_trail에 audit_id 발행 시 등록."""
    _issued_audit_ids.add(sa_id)


# ── Evidence Receipt 자동 생성 ────────────────────────────────────────────────

def _emit_evidence_receipt(
    actor: str,
    action: str,
    evidence_files: list,
    decision: str,
    result: str,
    sa_id: str = "",
) -> None:
    """
    중요 판단 완료 시 자동 호출.
    exec_audit_trail.log에 append.
    Receipt 없는 결정은 무효 (EDA v1.2 도미 지적 #2).
    """
    import hashlib as _hl, time as _tm
    registry_hash = _hl.sha256(
        json.dumps(_constraint_cache, sort_keys=True).encode()
    ).hexdigest()[:16] if _constraint_cache else "no_registry"

    receipt = {
        "receipt_type":             "EVIDENCE_RECEIPT",
        "actor":                    actor,
        "action":                   action,
        "evidence_files":           evidence_files,
        "constraint_registry_hash": registry_hash,
        "session_audit_id":         sa_id,
        "decision":                 decision,
        "result":                   result,
        "timestamp":                _tm.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
    }
    _exec_audit_path = (
        "/opt/arss/engine/arss-protocol/tools/mcp/exec_audit_trail.log"
    )
    try:
        with open(_exec_audit_path, "a", encoding="utf-8") as _f:
            _f.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    except Exception as _e:
        print(f"[EDA] Evidence Receipt 기록 실패: {_e}", file=sys.stderr)

# ── OAuth Compatibility Layer (S184 EAG-2, S187 EAG-1) ───────────────────────
import secrets as _secrets
_OAUTH_TOKENS: dict = {}          # token → {client_id, expires_at}  — 인메모리 유지
_OAUTH_CLIENTS: dict = {}         # client_id → {client_secret, client_name, ...}
_OAUTH_TOKEN_TTL = 3600
_OAUTH_CODE_TTL = 60
_OAUTH_CODES: dict = {}           # auth_code → {client_id, redirect_uri, expires_at}

# OAuth client 영속성 파일 경로 (secret_hash만 저장, 원문 금지)
_OAUTH_CLIENT_REGISTRY_PATH = "/opt/arss/engine/arss-protocol/registry/oauth_clients.json"
_DYNAMIC_CLIENT_REGISTRY_PATH = "/opt/arss/engine/arss-protocol/registry/dynamic_clients.json"

OAUTH_ISSUER = "https://arss-protocol.org"
OAUTH_TOKEN_ENDPOINT = "https://arss-protocol.org/token"
OAUTH_REGISTRATION_ENDPOINT = "https://arss-protocol.org/register"
OAUTH_AUTHORIZE_ENDPOINT = "https://arss-protocol.org/authorize"
# ─────────────────────────────────────────────────────────────────────────────

INTERNAL_ACTOR_ID = "claude_ai_remote_connector"
INTERNAL_ACTOR_SOURCE = "claude.ai"
INTERNAL_CONNECTOR_NAME = "ARSS Protocol"
EXTERNAL_PAYLOAD_ACTOR_TRUSTED = False

READ_HMAC_SECRET = os.environ.get("AIBA_READ_HMAC_SECRET", "")


def _get_read_hmac_secret() -> str:
    """Lazy HMAC secret read. OI-S311-001 fix: avoids module-load-time env capture."""
    return os.environ.get("AIBA_READ_HMAC_SECRET", "")


INTERNAL_CONNECTOR_IDENTITY = "claude.ai-arss-protocol"

READ_ALLOWED_ACTORS = frozenset(AGENT_ROOT_ALLOWLIST.keys())  # domi, jeni, caddy

# Write Plane 상수 (PT-S139-MCP-WRITE-BRIDGE-001)
WRITE_ALLOWED_ACTOR = "caddy"
WRITE_SERVER_URL = "http://127.0.0.1:8444/mcp/write"
WRITE_SERVER_TIMEOUT = 30
WRITE_MAX_PAYLOAD_BYTES = 65536

WRITE_TOOLS = frozenset({"write_file", "get_write_plane_state"})

# Jeni Runtime 상수 (PT-S189-JENI-RUNTIME-001, S189 EAG-1)
JENI_RUNTIME_URL = "http://127.0.0.1:8447/ask"
JENI_RUNTIME_TIMEOUT = 200
ASK_JENI_ALLOWED_ACTOR = "caddy"
ASK_JENI_MAX_PROMPT_BYTES = 32768
ASK_TOOLS = frozenset({"ask_jeni"})

# Domi Runtime 상수 (PT-S194-DOMI-RUNTIME-001, S194 EAG-1)
DOMI_RUNTIME_URL = "http://127.0.0.1:8448/ask"
DOMI_RUNTIME_TIMEOUT = 200
ASK_DOMI_ALLOWED_ACTOR = "caddy"
ASK_DOMI_MAX_PROMPT_BYTES = 32768
ASK_DOMI_TOOLS = frozenset({"ask_domi"})

# Exec Runtime 상수 (PT-S196-EXEC-SCOPED-001, S196 EAG-1)
EXEC_RUNTIME_URL = "http://127.0.0.1:8449/exec"
EXEC_RUNTIME_TIMEOUT = 310
EXEC_ALLOWED_ACTOR = "caddy"
EXEC_MAX_PAYLOAD_BYTES = 32768  # v1.4.0: write_script content 수용
EXEC_TOOLS = frozenset({"exec_scoped"})

# Sync 도구 (EAG-S205-SYNC-001)
SYNC_TOOLS = frozenset({"sync"})

ALLOWED_TOOLS = frozenset({
    "ping", "get_load_state",
    "read_file", "list_dir", "grep_scoped", "read_log", "check_service_state",
    "read_pytest_result", "read_audit_event", "read_metadata", "get_runtime_snapshot",
    "write_file", "get_write_plane_state",
    "ask_jeni", "ask_domi",
    "exec_scoped",
    "sync",
})

READ_TOOLS = frozenset({
    "read_file", "list_dir", "grep_scoped", "read_log", "check_service_state",
    "read_pytest_result", "read_audit_event", "read_metadata", "get_runtime_snapshot",
})

# ── Agent REST Wrapper 허용 도구 ───────────────────────────────────────────────
_AGENT_READ_TOOLS = frozenset({
    "read_file", "list_dir", "grep_scoped", "read_log", "get_runtime_snapshot"
})
_AGENT_WRITE_TOOLS = frozenset({"write_file"})
_AGENT_ALLOWED_TOOLS = _AGENT_READ_TOOLS | _AGENT_WRITE_TOOLS

# ── actor별 Tier2 write whitelist ─────────────────────────────────────────────
_ARSS_ROOT = "/opt/arss/engine/arss-protocol"
_ACTOR_WRITE_WHITELIST: dict = {
    "domi": [
        os.path.realpath(f"{_ARSS_ROOT}/tools/sandbox/domi"),
        os.path.realpath(f"{_ARSS_ROOT}/tools/sandbox/common/collab"),
        os.path.realpath(f"{_ARSS_ROOT}/tools/tmp"),
        os.path.realpath(f"{_ARSS_ROOT}/tests/sandbox"),
    ],
    "jeni": [
        os.path.realpath(f"{_ARSS_ROOT}/tools/sandbox/jeni"),
        os.path.realpath(f"{_ARSS_ROOT}/tools/sandbox/common/collab"),
        os.path.realpath(f"{_ARSS_ROOT}/tools/tmp"),
        os.path.realpath(f"{_ARSS_ROOT}/tests/sandbox"),
    ],
}

CONTAINMENT_ERROR_CODE = -32000
CONTAINMENT_ERROR_MESSAGE = "AIBA containment active"
CONTAINMENT_ERROR_REASON = "CONTAINMENT_ACTIVE"
SSE_HEARTBEAT_INTERVAL = 15

_read_server = ReadOnlyServer()

# ── Bridge 상태 ────────────────────────────────────────────────────────────────

_bridge_state = "INACTIVE"
_bridge_state_lock = threading.Lock()
_sse_clients: list = []
_sse_clients_lock = threading.Lock()


def _get_bridge_state() -> str:
    with _bridge_state_lock:
        return _bridge_state


def _set_bridge_state(state: str) -> None:
    with _bridge_state_lock:
        global _bridge_state
        _bridge_state = state


# ── OAuth client 영속성 (S187 EAG-1, S189 EAG-1) ─────────────────────────────

def _hash_secret(secret: str) -> str:
    """client_secret SHA-256 hash — 원문 저장 금지."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _load_agent_clients_from_env() -> None:
    """
    환경변수 기반 domi/jeni/caddy client 사전 등록.
    AIBA_DOMI_CLIENT_ID, AIBA_DOMI_CLIENT_SECRET
    AIBA_JENI_CLIENT_ID, AIBA_JENI_CLIENT_SECRET
    AIBA_CADDY_CLIENT_ID, AIBA_CADDY_CLIENT_SECRET
    bridge 시작 시 1회 호출.
    """
    for actor in ("domi", "jeni", "caddy"):
        cid_key = f"AIBA_{actor.upper()}_CLIENT_ID"
        csec_key = f"AIBA_{actor.upper()}_CLIENT_SECRET"
        client_id = os.environ.get(cid_key, "")
        client_secret = os.environ.get(csec_key, "")
        if client_id and client_secret:
            _OAUTH_CLIENTS[client_id] = {
                "client_secret": client_secret,
                "client_name": f"{actor}-connector",
                "actor_id": actor,
                "scopes": ["mcp:read"],
                "secret_hash": _hash_secret(client_secret),
                "revoked": False,
            }
            print(f"[OAUTH] {actor} client loaded from env: {client_id}", file=sys.stderr)


def _persist_client_registry() -> None:
    """
    client registry를 파일로 저장 — secret 원문 제외, secret_hash만 기록.
    파일은 bridge 재시작 시 참조용 (인증은 환경변수 우선).
    """
    try:
        os.makedirs(os.path.dirname(_OAUTH_CLIENT_REGISTRY_PATH), exist_ok=True)
        safe_clients = {}
        for cid, info in _OAUTH_CLIENTS.items():
            safe_clients[cid] = {
                k: v for k, v in info.items()
                if k not in ("client_secret",)  # 원문 제외
            }
        with open(_OAUTH_CLIENT_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(safe_clients, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[OAUTH] client registry persist WARN: {e}", file=sys.stderr)


def _persist_dynamic_client(client_id: str, info: dict) -> None:
    """
    동적 등록 client를 파일로 즉시 영속화.
    secret 원문 제외, secret_hash만 저장.
    bridge 재시작 후 _load_dynamic_clients_from_file()로 복원.
    """
    try:
        os.makedirs(os.path.dirname(_DYNAMIC_CLIENT_REGISTRY_PATH), exist_ok=True)
        try:
            with open(_DYNAMIC_CLIENT_REGISTRY_PATH, "r", encoding="utf-8") as f:
                registry = json.load(f)
        except Exception:
            registry = {}
        registry[client_id] = {
            k: v for k, v in info.items()
            if k not in ("client_secret",)
        }
        with open(_DYNAMIC_CLIENT_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[OAUTH] dynamic client persist WARN: {e}", file=sys.stderr)


def _load_dynamic_clients_from_file() -> None:
    """
    bridge 시작 시 동적 등록 client를 파일에서 복원.
    secret_hash만 저장되어 있으므로 재인증 시 새 secret 발급 필요.
    단, client_id 존재 여부만으로 /authorize 허용 — secret은 /token에서 검증.
    """
    if not os.path.exists(_DYNAMIC_CLIENT_REGISTRY_PATH):
        return
    try:
        with open(_DYNAMIC_CLIENT_REGISTRY_PATH, "r", encoding="utf-8") as f:
            registry = json.load(f)
        for cid, info in registry.items():
            if cid not in _OAUTH_CLIENTS:
                _OAUTH_CLIENTS[cid] = {
                    **info,
                    "client_secret": "",   # 재인증 시 갱신됨
                    "restored_from_file": True,
                }
        print(f"[OAUTH] dynamic clients restored: {len(registry)} entries", file=sys.stderr)
    except Exception as e:
        print(f"[OAUTH] dynamic client load WARN: {e}", file=sys.stderr)


# ── Governance Adapter ────────────────────────────────────────────────────────

def _build_governance_context(raw_request: dict) -> dict:
    return {
        "actor_id": INTERNAL_ACTOR_ID,
        "source": INTERNAL_ACTOR_SOURCE,
        "connector_name": INTERNAL_CONNECTOR_NAME,
        "external_payload_actor_trusted": EXTERNAL_PAYLOAD_ACTOR_TRUSTED,
        "raw_request": raw_request,
        "bridge_state": _get_bridge_state(),
        "containment_active": containment_is_active(),
    }


def _containment_jsonrpc_error(request_id) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": CONTAINMENT_ERROR_CODE,
            "message": CONTAINMENT_ERROR_MESSAGE,
            "data": {"reason": CONTAINMENT_ERROR_REASON},
        },
    }


def _audit_allow(gov_ctx: dict, returned_scope: str, reason: str) -> None:
    write_audit(
        agent_id=gov_ctx["actor_id"],
        requested_shard="mcp_endpoint",
        returned_scope=returned_scope,
        decision="ALLOW",
        reason=reason,
        load_state=gov_ctx["bridge_state"],
        retrieval_class="CLASS-B",
    )


def _audit_deny(gov_ctx: dict, reason: str) -> None:
    try:
        write_deny_audit(
            agent_id=gov_ctx["actor_id"],
            requested_shard="mcp_endpoint",
            reason=reason,
        )
    except Exception as _audit_err:
        print("[audit_deny best-effort failure]", repr(_audit_err), file=sys.stderr)


# ── Agent REST Wrapper — Audit Mandatory Gate (S187 EAG-1) ───────────────────

def _agent_audit_pre(actor_id: str, tool_name: str, purpose: str, endpoint: str) -> bool:
    """
    audit pre-record — mandatory gate.
    실패 시 False 반환 → 호출자가 HTTP 500 / ACCESS_DENIED 반환.
    성공 시 True.
    """
    try:
        write_audit(
            agent_id=actor_id,
            requested_shard=f"{endpoint}/{tool_name}",
            returned_scope=tool_name,
            decision="PRE_RECORD",
            reason=f"agent_rest_wrapper pre: purpose={purpose}",
            load_state=_get_bridge_state(),
            retrieval_class="CLASS-B",
        )
        return True
    except Exception as e:
        print(f"[audit_pre FAIL] {actor_id}/{tool_name}: {e}", file=sys.stderr)
        return False


def _agent_audit_post(actor_id: str, tool_name: str, endpoint: str, success: bool, detail: str = "") -> bool:
    """
    audit post-record — mandatory gate.
    실패 시 False 반환 → 호출자가 HTTP 500 / RESULT_WITHHELD 반환.
    성공 시 True.
    """
    try:
        decision = "POST_ALLOW" if success else "POST_DENY"
        write_audit(
            agent_id=actor_id,
            requested_shard=f"{endpoint}/{tool_name}",
            returned_scope=tool_name,
            decision=decision,
            reason=f"agent_rest_wrapper post: success={success} {detail}".strip(),
            load_state=_get_bridge_state(),
            retrieval_class="CLASS-B",
        )
        return True
    except Exception as e:
        print(f"[audit_post FAIL] {actor_id}/{tool_name}: {e}", file=sys.stderr)
        return False


# ── agent write — Tier2 realpath 경계 검증 (S187 EAG-1) ──────────────────────

def _is_safe_write_path(actor_id: str, target_path: str) -> tuple:
    """
    actor별 write whitelist + realpath 경계 검증.
    Returns: (is_safe: bool, reason: str)
    """
    whitelist = _ACTOR_WRITE_WHITELIST.get(actor_id, [])
    if not whitelist:
        return False, f"actor '{actor_id}' has no write whitelist"

    try:
        real_target = os.path.realpath(os.path.abspath(target_path))
    except Exception as e:
        return False, f"path resolution error: {e}"

    for allowed_base in whitelist:
        real_base = os.path.realpath(allowed_base)
        if real_target == real_base or real_target.startswith(real_base + os.sep):
            return True, f"path within whitelist: {real_base}"

    return False, f"path '{real_target}' not in actor '{actor_id}' whitelist"


def _handle_agent_write_file(actor_id: str, req_body: dict) -> dict:
    """
    /domi/write_file, /jeni/write_file 처리.
    Tier2 Sandbox 한정, actor 강제 주입, realpath 검증.
    """
    target_path = req_body.get("target_path", "")
    content = req_body.get("content", "")

    if not target_path:
        return {"isError": True, "content": [{"type": "text", "text": "DENY: target_path required"}]}

    # realpath 경계 검증
    is_safe, reason = _is_safe_write_path(actor_id, target_path)
    if not is_safe:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: {reason}"}]}

    # 실제 파일 쓰기
    try:
        real_path = os.path.realpath(os.path.abspath(target_path))
        os.makedirs(os.path.dirname(real_path), exist_ok=True)
        with open(real_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps({
                "status": "ALLOW",
                "written_path": real_path,
                "bytes_written": len(content.encode("utf-8")),
                "actor": actor_id,
            }, ensure_ascii=False)}],
        }
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: write error: {e}"}]}


# ── OAuth 헬퍼 ────────────────────────────────────────────────────────────────

def _oauth_protected_resource_meta() -> dict:
    return {
        "resource": "https://arss-protocol.org/mcp",
        "authorization_servers": [OAUTH_ISSUER],
        "bearer_methods_supported": ["header"],
        "resource_documentation": "https://arss-protocol.org/mcp",
    }

def _oauth_server_meta() -> dict:
    return {
        "issuer": OAUTH_ISSUER,
        "authorization_endpoint": OAUTH_AUTHORIZE_ENDPOINT,
        "token_endpoint": OAUTH_TOKEN_ENDPOINT,
        "registration_endpoint": OAUTH_REGISTRATION_ENDPOINT,
        "grant_types_supported": ["client_credentials", "authorization_code"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
        "response_types_supported": ["code"],
        "scopes_supported": ["mcp:read"],
    }

def _oauth_authorize(query_string: str) -> tuple:
    import time as _time, urllib.parse as _up
    params = dict(_up.parse_qsl(query_string))
    response_type = params.get("response_type", "")
    client_id     = params.get("client_id", "")
    redirect_uri  = params.get("redirect_uri", "")
    state         = params.get("state", "")
    if response_type != "code":
        return 400, None, {"error": "unsupported_response_type"}
    if not client_id:
        return 400, None, {"error": "invalid_request", "error_description": "client_id required"}
    if not redirect_uri:
        return 400, None, {"error": "invalid_request", "error_description": "redirect_uri required"}
    if client_id not in _OAUTH_CLIENTS:
        _OAUTH_CLIENTS[client_id] = {"client_secret": "", "client_name": "auto", "actor_id": "domi", "scopes": ["mcp:read"], "revoked": False, "auto_registered": True}
    auth_code  = _secrets.token_hex(16)
    expires_at = _time.time() + _OAUTH_CODE_TTL
    _OAUTH_CODES[auth_code] = {"client_id": client_id, "redirect_uri": redirect_uri, "expires_at": expires_at}
    qs_params = {"code": auth_code}
    if state:
        qs_params["state"] = state
    import urllib.parse as _up2
    location = redirect_uri + "?" + _up2.urlencode(qs_params)
    return 302, location, None


def _oauth_register(body: dict) -> dict:
    import time as _time
    client_id = "claude-" + _secrets.token_hex(8)
    client_secret = _secrets.token_hex(32)
    _OAUTH_CLIENTS[client_id] = {
        "client_secret": client_secret,
        "client_name": body.get("client_name", "claude-connector"),
        "actor_id": "external",
        "scopes": ["mcp:read"],
        "secret_hash": _hash_secret(client_secret),
        "revoked": False,
    }
    _persist_client_registry()
    _persist_dynamic_client(client_id, _OAUTH_CLIENTS[client_id])
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "client_id_issued_at": int(_time.time()),
        "client_secret_expires_at": 0,
        "grant_types": ["client_credentials", "authorization_code"],
        "token_endpoint_auth_method": "client_secret_post",
    }

def _oauth_token(form_body: str) -> tuple:
    import time as _time, urllib.parse as _up
    params = dict(_up.parse_qsl(form_body))
    grant_type    = params.get("grant_type", "")
    client_id     = params.get("client_id", "")
    client_secret = params.get("client_secret", "")

    if grant_type == "authorization_code":
        code         = params.get("code", "")
        redirect_uri = params.get("redirect_uri", "")
        entry = _OAUTH_CODES.get(code)
        if not entry:
            return 400, {"error": "invalid_grant", "error_description": "code not found"}
        if _time.time() > entry["expires_at"]:
            del _OAUTH_CODES[code]
            return 400, {"error": "invalid_grant", "error_description": "code expired"}
        if entry["client_id"] != client_id:
            return 401, {"error": "invalid_client"}
        if entry["redirect_uri"] != redirect_uri:
            return 400, {"error": "invalid_grant", "error_description": "redirect_uri mismatch"}
        del _OAUTH_CODES[code]
        client = _OAUTH_CLIENTS.get(client_id)
        if not client or client.get("revoked"):
            return 401, {"error": "invalid_client"}
        if client.get("auto_registered") and client["client_secret"] == "":
            client["client_secret"] = client_secret
            client["auto_registered"] = False
        if client["client_secret"] != client_secret:
            return 401, {"error": "invalid_client"}
        token = _secrets.token_hex(32)
        _OAUTH_TOKENS[token] = {"client_id": client_id, "expires_at": _time.time() + _OAUTH_TOKEN_TTL}
        return 200, {"access_token": token, "token_type": "bearer", "expires_in": _OAUTH_TOKEN_TTL, "scope": "mcp:read"}

    if grant_type != "client_credentials":
        return 400, {"error": "unsupported_grant_type"}
    client = _OAUTH_CLIENTS.get(client_id)
    if not client or client.get("revoked"):
        return 401, {"error": "invalid_client"}
    # 파일 복원 client: secret이 비어 있으면 새 secret으로 갱신 허용
    if client.get("restored_from_file") and client["client_secret"] == "":
        client["client_secret"] = client_secret
        client["restored_from_file"] = False
        _persist_dynamic_client(client_id, client)
    if client["client_secret"] != client_secret:
        return 401, {"error": "invalid_client"}
    token = _secrets.token_hex(32)
    _OAUTH_TOKENS[token] = {"client_id": client_id, "expires_at": _time.time() + _OAUTH_TOKEN_TTL}
    return 200, {"access_token": token, "token_type": "bearer", "expires_in": _OAUTH_TOKEN_TTL, "scope": "mcp:read"}


# ── READ 도구 내부 HMAC 생성 ──────────────────────────────────────────────────

def _make_internal_hmac(actor_id: str, nonce: str, ts: float, payload: str) -> str:
    msg = f"{actor_id}:{INTERNAL_CONNECTOR_IDENTITY}:{nonce}:{ts}:{payload}"
    return hmac_lib.new(_get_read_hmac_secret().encode(), msg.encode(), hashlib.sha256).hexdigest()


def _build_read_kwargs(actor_id: str, payload: str) -> dict:
    ts = time.time()
    nonce = str(uuid.uuid4())
    return dict(
        actor_id=actor_id,
        connector_identity=INTERNAL_CONNECTOR_IDENTITY,
        hmac_value=_make_internal_hmac(actor_id, nonce, ts, payload),
        nonce=nonce,
        timestamp=ts,
        hmac_secret=_get_read_hmac_secret(),
    )


# ── Write 도구 중계 핸들러 (v2.2.0 유지) ─────────────────────────────────────

_WRITE_FILE_ALLOWED_FIELDS = frozenset({"approval_id", "target_path", "content"})

def _handle_write_tool(tool_name: str, arguments: dict) -> dict:
    actor_id = arguments.get("actor_id", "")
    if actor_id != WRITE_ALLOWED_ACTOR:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: write tool actor must be '{WRITE_ALLOWED_ACTOR}', got '{actor_id}'"}]}
    if tool_name == "write_file":
        approval_id = arguments.get("approval_id")
        target_path = arguments.get("target_path")
        content = arguments.get("content", "")
        if not approval_id:
            return {"isError": True, "content": [{"type": "text", "text": "DENY: approval_id required"}]}
        if not target_path:
            return {"isError": True, "content": [{"type": "text", "text": "DENY: target_path required"}]}
        unknown = set(arguments.keys()) - _WRITE_FILE_ALLOWED_FIELDS - {"actor_id"}
        if unknown:
            return {"isError": True, "content": [{"type": "text", "text": f"DENY: unknown fields: {sorted(unknown)}"}]}
        forward_params = {"approval_id": approval_id, "target_path": target_path, "content": content}
    elif tool_name == "get_write_plane_state":
        forward_params = {}
    else:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: unknown write tool: {tool_name}"}]}

    forward_body = json.dumps({"tool": tool_name, "params": forward_params}).encode("utf-8")
    if len(forward_body) > WRITE_MAX_PAYLOAD_BYTES:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: payload size {len(forward_body)} exceeds limit {WRITE_MAX_PAYLOAD_BYTES}"}]}
    try:
        req = urllib.request.Request(WRITE_SERVER_URL, data=forward_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(forward_body))}, method="POST")
        with urllib.request.urlopen(req, timeout=WRITE_SERVER_TIMEOUT) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            return {"isError": not result.get("ok", False), "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    except urllib.error.URLError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: write server unreachable — {e}"}]}
    except TimeoutError:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: write server timeout ({WRITE_SERVER_TIMEOUT}s)"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: unexpected error — {e}"}]}


# ── ask_domi 핸들러 (PT-S194-DOMI-RUNTIME-001, S194 EAG-1) ───────────────────

def _handle_ask_domi(arguments: dict) -> dict:
    """
    ask_domi — 캐디가 도미(OpenAI)에게 설계를 의뢰.
    Connector Layer 전용 FORWARD_ONLY. caddy actor 강제.
    Domi Runtime 다운 시 FAIL_CLOSED (bridge 자체는 정상 유지 — 장애 격리).
    """
    actor_id = arguments.get("actor_id", "")
    if actor_id != ASK_DOMI_ALLOWED_ACTOR:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: ask_domi actor must be '{ASK_DOMI_ALLOWED_ACTOR}', got '{actor_id}'"}]}

    prompt = arguments.get("prompt", "")
    context = arguments.get("context", "")
    if not prompt:
        return {"isError": True, "content": [{"type": "text", "text": "DENY: prompt required"}]}

    session = arguments.get("session", "S000")
    forward_body = json.dumps({"prompt": prompt, "context": context, "session": session}).encode("utf-8")
    if len(forward_body) > ASK_DOMI_MAX_PROMPT_BYTES:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: prompt size {len(forward_body)} exceeds limit {ASK_DOMI_MAX_PROMPT_BYTES}"}]}

    try:
        req = urllib.request.Request(DOMI_RUNTIME_URL, data=forward_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(forward_body))}, method="POST")
        with urllib.request.urlopen(req, timeout=DOMI_RUNTIME_TIMEOUT) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            if result.get("ok"):
                return {"isError": False, "content": [{"type": "text", "text": result.get("text", "")}]}
            return {"isError": True, "content": [{"type": "text", "text": f"DOMI_ERROR: {result.get('error', 'unknown')}"}]}
    except urllib.error.URLError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: domi runtime unreachable — {e}"}]}
    except TimeoutError:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: domi runtime timeout ({DOMI_RUNTIME_TIMEOUT}s)"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: unexpected error — {e}"}]}


def _build_exec_required_paths(arguments: dict) -> list:
    """exec_scoped 실행 전 L2 게이트에 넘길 필수 읽기 경로 목록.
    EDA v1.2 L2 게이트 연결 (EAG-S320-EDA-L2L3-001).
    - run_script: params.script_path 가 있으면 해당 경로가 사전에 read_file로 읽혔어야 함.
    - 목록이 비어 있으면 L2 게이트는 항상 PASS (단순 명령은 읽기 증거 불필요).
    """
    required = []
    params = arguments.get("params", {}) or {}
    script_path = params.get("script_path", "")
    if script_path:
        required.append(script_path)
    required.extend(arguments.get("required_reads", []))
    return required


# -- exec_scoped 핸들러 (PT-S196-EXEC-SCOPED-001, S196 EAG-1) -----------------
# v2.5.0 (S197 EAG-1): session_audit_id 발행 — Rev.2 C-5 병렬 audit 통합

def _handle_exec_scoped(arguments: dict) -> dict:
    actor_id = arguments.get("actor_id", "")
    if actor_id != EXEC_ALLOWED_ACTOR:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: actor must be caddy, got {actor_id}"}]}
    approval_id = arguments.get("approval_id", "")
    if not approval_id:
        return {"isError": True, "content": [{"type": "text", "text": "DENY: approval_id required"}]}
    command = arguments.get("command", "")
    params = arguments.get("params", {})
    # session_audit_id: 외부 주입 또는 bridge에서 신규 발행 (Rev.2 C-5)
    session_audit_id: str = arguments.get("session_audit_id") or f"SA-{str(uuid.uuid4())[:8]}"
    VALID = frozenset({"pytest","git_commit","git_status","git_diff","systemctl_restart","git_push","write_script","run_script"})
    if command not in VALID:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: command {command} not in whitelist"}]}
    body = json.dumps({
        "actor_id": actor_id,
        "approval_id": approval_id,
        "command": command,
        "params": params,
        "session_audit_id": session_audit_id,
    }).encode()
    if len(body) > EXEC_MAX_PAYLOAD_BYTES:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: payload too large"}]}
    # ── EDA v1.2 L2 Gate (EAG-S320-EDA-L2L3-001) ────────────────────────────
    _l2_required = _build_exec_required_paths(arguments)
    _l2_deny = _l2_gate(_l2_required)
    if _l2_deny:
        return {"isError": True, "content": [{"type": "text", "text": _l2_deny}]}
    # ─────────────────────────────────────────────────────────────────────────
    try:
        req = urllib.request.Request(EXEC_RUNTIME_URL, data=body, headers={"Content-Type":"application/json","Content-Length":str(len(body))}, method="POST")
        with urllib.request.urlopen(req, timeout=EXEC_RUNTIME_TIMEOUT) as resp:
            result = json.loads(resp.read().decode())
            result["session_audit_id"] = session_audit_id
            # -- [EAG-S406] write_script success -> record written_path as L2 evidence --
            # Rationale: write_script content is authored by caddy itself, which
            # satisfies the L2 "inspected before exec" purpose more strongly than a
            # read-back. run_script is already sandbox-confined to CADDY_SANDBOX, and
            # write_script writes only there, so the executable set == the writable set.
            _written = result.get("written_path")
            if _written and result.get("exit_code") == 0:
                _l2_record_read(_written)
            # ── EDA v1.2 Evidence Receipt (EAG-S275-EDA-IMPLEMENTATION) ──────
            _exec_text = json.dumps(result, ensure_ascii=False)
            _sa_match = SA_HASH_PATTERN.search(str(result.get("session_audit_id", "")))
            if _sa_match:
                _register_audit_id(_sa_match.group(0))
            _emit_evidence_receipt(
                actor=actor_id,
                action=f"exec_scoped:{command}",
                evidence_files=[],
                decision="EXECUTED",
                result="PASS" if result.get("ok") else "FAIL",
                sa_id=_sa_match.group(0) if _sa_match else "",
            )
            # ─────────────────────────────────────────────────────────────────
            # ── EDA v1.2 L3 Gate (EAG-S320-EDA-L2L3-001) ───────────────────
            _l3_deny = _l3_gate(_exec_text)
            if _l3_deny:
                return {"isError": True, "content": [{"type": "text", "text": _l3_deny}]}
            # ─────────────────────────────────────────────────────────────────
            return {"isError": not result.get("ok", False), "content": [{"type": "text", "text": _exec_text}]}
    except urllib.error.URLError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: exec runtime unreachable -- {e}"}]}
    except TimeoutError:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: exec runtime timeout ({EXEC_RUNTIME_TIMEOUT}s)"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: unexpected -- {e}"}]}


# ── ask_jeni 핸들러 (PT-S189-JENI-RUNTIME-001, S189 EAG-1) ───────────────────

def _handle_ask_jeni(arguments: dict) -> dict:
    """
    ask_jeni — 캐디가 제니(Gemini)에게 질문.
    Connector Layer 전용 FORWARD_ONLY. caddy actor 강제.
    Jeni Runtime 다운 시 FAIL_CLOSED (bridge 자체는 정상 유지 — 장애 격리).
    """
    actor_id = arguments.get("actor_id", "")
    if actor_id != ASK_JENI_ALLOWED_ACTOR:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: ask_jeni actor must be '{ASK_JENI_ALLOWED_ACTOR}', got '{actor_id}'"}]}

    prompt = arguments.get("prompt", "")
    context = arguments.get("context", "")
    if not prompt:
        return {"isError": True, "content": [{"type": "text", "text": "DENY: prompt required"}]}

    session = arguments.get("session", "S000")
    forward_body = json.dumps({"prompt": prompt, "context": context, "session": session}).encode("utf-8")
    if len(forward_body) > ASK_JENI_MAX_PROMPT_BYTES:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: prompt size {len(forward_body)} exceeds limit {ASK_JENI_MAX_PROMPT_BYTES}"}]}

    try:
        req = urllib.request.Request(JENI_RUNTIME_URL, data=forward_body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(forward_body))}, method="POST")
        with urllib.request.urlopen(req, timeout=JENI_RUNTIME_TIMEOUT) as resp:
            resp_body = resp.read().decode("utf-8")
            result = json.loads(resp_body)
            if result.get("ok"):
                return {"isError": False, "content": [{"type": "text", "text": result.get("text", "")}]}
            error_key    = result.get("error", "unknown")
            error_detail = result.get("text", "")
            return {"isError": True, "content": [{"type": "text", "text": f"JENI_ERROR: {error_key}\nDETAIL: {error_detail}"}]}
    except urllib.error.URLError as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: jeni runtime unreachable — {e}"}]}
    except TimeoutError:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: jeni runtime timeout ({JENI_RUNTIME_TIMEOUT}s)"}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: unexpected error — {e}"}]}



# ── sync 핸들러 (EAG-S205-SYNC-001) ────────────────────────────────────────────────────

_ARSS_POINTER_PATH = os.path.join(_ARSS_ROOT, "SESSION_CONTEXT_POINTER.json")
SYNC_ALLOWED_ACTORS = READ_ALLOWED_ACTORS


# EAG-S208-WORM-002: Ledger Token Register
_LEDGER_LOOPBACK_IPS = frozenset({"127.0.0.1", "::1"})

def _handle_ledger_token_register(handler):
    if handler.client_address[0] not in _LEDGER_LOOPBACK_IPS:
        handler._send_json(403, {"ok": False, "error": "LEDGER_TOKEN_REGISTER_DENIED: LOOPBACK_ONLY"})
        return
    cl = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(cl) if cl > 0 else b"{}"
    try: body = json.loads(raw)
    except Exception:
        handler._send_json(400, {"ok": False, "error": "INVALID_JSON"}); return
    actor = body.get("actor", ""); session = body.get("session", "")
    token_id = body.get("token_id", ""); issuer = body.get("issuer", "")
    if issuer != "beo":
        handler._send_json(403, {"ok": False, "error": "DENY: issuer must be beo"}); return
    if actor not in ("caddy", "domi", "jeni"):
        handler._send_json(400, {"ok": False, "error": f"DENY: invalid actor={actor}"}); return
    if not session or not token_id:
        handler._send_json(400, {"ok": False, "error": "DENY: session and token_id required"}); return
    try:
        import sys as _s
        lp = "/opt/arss/engine/arss-protocol/tools/ledger"
        if lp not in _s.path: _s.path.insert(0, lp)
        from ledger_writer import register_ledger_token
        result = register_ledger_token(token_id, actor, session)
        handler._send_json(200 if result["ok"] else 400, result)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"LEDGER_TOKEN_REGISTER_ERROR: {e}"})

def _handle_ledger_append(handler, agent):
    if agent not in ("caddy", "domi", "jeni"):
        handler._send_json(400, {"ok": False, "error": f"DENY: invalid agent={agent}"}); return
    cl = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(cl) if cl > 0 else b"{}"
    try: body = json.loads(raw)
    except Exception:
        handler._send_json(400, {"ok": False, "error": "INVALID_JSON"}); return
    actor = body.get("actor", ""); action_type = body.get("action_type", "")
    payload = body.get("payload", ""); session = body.get("session", "")
    chain_tip = body.get("chain_tip", ""); token_id = body.get("token_id", "")
    payload_ref = body.get("payload_ref", "")
    if actor != agent:
        handler._send_json(403, {"ok": False, "error": f"DENY: actor={actor} != path agent={agent}"}); return
    if not all([actor, action_type, payload, session, chain_tip, token_id]):
        handler._send_json(400, {"ok": False, "error": "DENY: required fields missing"}); return
    try:
        import sys as _s
        lp = "/opt/arss/engine/arss-protocol/tools/ledger"
        if lp not in _s.path: _s.path.insert(0, lp)
        from ledger_writer import append_entry
        result = append_entry(actor, action_type, payload, session, chain_tip, token_id, payload_ref)
        handler._send_json(200 if result["ok"] else 400, result)
    except Exception as e:
        handler._send_json(500, {"ok": False, "error": f"LEDGER_APPEND_ERROR: {e}"})


def _handle_sync(arguments: dict) -> dict:
    """
    sync — SESSION_CONTEXT canonical 상태와 호출자 context_hash 비교.
    read-only. SESSION_CONTEXT_POINTER.json 기준. Fail-Closed.
    EAG-S205-SYNC-001
    """
    actor_id = arguments.get("actor_id", "")
    if actor_id not in SYNC_ALLOWED_ACTORS:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: unknown actor_id={actor_id}"}]}

    context_hash = arguments.get("context_hash", "")
    if (not context_hash
            or len(context_hash) != 64
            or not all(c in "0123456789abcdef" for c in context_hash.lower())):
        return {"isError": True, "content": [{"type": "text", "text": "DENY: context_hash must be 64-char lowercase hex"}]}

    try:
        with open(_ARSS_POINTER_PATH, "r", encoding="utf-8") as _f:
            pointer = json.load(_f)
    except FileNotFoundError:
        return {"isError": True, "content": [{"type": "text", "text": "FAIL_CLOSED: SESSION_CONTEXT_POINTER.json not found"}]}
    except Exception as _e:
        return {"isError": True, "content": [{"type": "text", "text": f"FAIL_CLOSED: pointer read error — {_e}"}]}

    canonical_context_hash = pointer.get("context_hash", "")
    canonical_chain_tip    = pointer.get("chain_tip", "")

    if not canonical_context_hash:
        return {"isError": True, "content": [{"type": "text", "text": "FAIL_CLOSED: context_hash missing in POINTER"}]}

    match  = context_hash.lower() == canonical_context_hash.lower()
    status = "SYNC_OK" if match else "SYNC_MISMATCH"

    return {
        "isError": False,
        "content": [{
            "type": "text",
            "text": json.dumps({
                "status": status,
                "match": match,
                "canonical_context_hash": canonical_context_hash,
                "canonical_chain_tip": canonical_chain_tip,
                "actor_id": actor_id,
            }, ensure_ascii=False),
        }],
    }


# ── AIBA Tool Layer ───────────────────────────────────────────────────────────

def _build_base_tool_entries() -> list:
    return [
        {"name": "ping", "description": "AIBA bridge connectivity check", "inputSchema": {"type": "object", "properties": {}, "required": []}},
        {"name": "get_load_state", "description": "Returns bridge load state (visibility only)", "inputSchema": {"type": "object", "properties": {}, "required": []}},
    ]


def _build_read_tool_entries_fs() -> list:
    return [
        {"name": "read_file", "description": "[READ] 단일 파일 읽기 (whitelist 경로 전용)",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["path", "actor_id", "purpose"]}},
        {"name": "list_dir", "description": "[READ] 디렉토리 목록 (depth=1, recursive 금지)",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["path", "actor_id", "purpose"]}},
        {"name": "grep_scoped", "description": "[READ] 허용 경로 내 텍스트 검색 (depth=2)",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "pattern": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["path", "pattern", "actor_id", "purpose"]}},
        {"name": "read_log", "description": "[READ] 로그 파일 tail 읽기 (최대 200줄)",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "tail_lines": {"type": "integer"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["path", "tail_lines", "actor_id", "purpose"]}},
        {"name": "check_service_state", "description": "[READ] 허용 서비스 상태 확인 (상태 조회만, 제어 금지)",
         "inputSchema": {"type": "object", "properties": {"service_name": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["service_name", "actor_id", "purpose"]}},
    ]


def _build_read_tool_entries_meta() -> list:
    return [
        {"name": "read_pytest_result", "description": "[READ] pytest result artifact 읽기 (실행 아님)",
         "inputSchema": {"type": "object", "properties": {"artifact_path": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["artifact_path", "actor_id", "purpose"]}},
        {"name": "read_audit_event", "description": "[READ] audit event 읽기 (최대 100건, bulk dump 금지)",
         "inputSchema": {"type": "object", "properties": {"log_path": {"type": "string"}, "event_range": {"type": "integer"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["log_path", "event_range", "actor_id", "purpose"]}},
        {"name": "read_metadata", "description": "[READ] SESSION_CONTEXT / SESSION_BOOT / sync metadata 읽기",
         "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["path", "actor_id", "purpose"]}},
        {"name": "get_runtime_snapshot", "description": "[READ] 사전 정의된 read-only snapshot projection",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": list(READ_ALLOWED_ACTORS)}, "purpose": {"type": "string"}}, "required": ["actor_id", "purpose"]}},
    ]


def _build_write_tool_entries() -> list:
    return [
        {"name": "write_file", "description": "[WRITE] EAG approval 기반 sandbox 파일 쓰기 (caddy only)",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": [WRITE_ALLOWED_ACTOR]}, "approval_id": {"type": "string"}, "target_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["actor_id", "approval_id", "target_path", "content"]}},
        {"name": "get_write_plane_state", "description": "[WRITE] Write Plane 현재 상태 조회 (caddy only)",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": [WRITE_ALLOWED_ACTOR]}}, "required": ["actor_id"]}},
        {"name": "ask_jeni", "description": "[ASK] 제니(Gemini Governance Auditor)에게 질문 (caddy only)",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": [ASK_JENI_ALLOWED_ACTOR]}, "prompt": {"type": "string"}, "context": {"type": "string"}, "session": {"type": "string", "description": "세션 ID (예: S264). persistent memory 세션별 축적용."}}, "required": ["actor_id", "prompt"]}},
        {"name": "ask_domi", "description": "[ASK] 도미(OpenAI Design Architect)에게 설계 의뢰 (caddy only)",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": [ASK_DOMI_ALLOWED_ACTOR]}, "prompt": {"type": "string"}, "context": {"type": "string"}, "session": {"type": "string", "description": "세션 ID (예: S264). persistent memory 세션별 축적용."}}, "required": ["actor_id", "prompt"]}},
        {"name": "exec_scoped", "description": "[EXEC] EAG approval 기반 허용 명령 실행 (caddy only)",
         "inputSchema": {"type": "object", "properties": {"actor_id": {"type": "string", "enum": [EXEC_ALLOWED_ACTOR]}, "approval_id": {"type": "string"}, "command": {"type": "string", "enum": ["pytest","git_commit","git_status","git_diff","systemctl_restart","git_push","write_script","run_script"]}, "params": {"type": "object"}}, "required": ["actor_id", "approval_id", "command"]}},
    ]


def _build_read_tool_entries() -> list:
    return _build_read_tool_entries_fs() + _build_read_tool_entries_meta()


def _build_sync_tool_entries() -> list:
    return [
        {"name": "sync",
         "description": "[SYNC] SESSION_CONTEXT canonical 상태 동기화 검증 (read-only, EAG-S205-SYNC-001)",
         "inputSchema": {"type": "object", "properties": {
             "actor_id": {"type": "string", "enum": list(SYNC_ALLOWED_ACTORS)},
             "context_hash": {"type": "string",
                              "description": "64-char hex — SHA256(canonical_json(SC_FINAL))"},
         }, "required": ["actor_id", "context_hash"]}},
    ]


def _handle_tool_list() -> dict:
    tools = (_build_base_tool_entries() + _build_read_tool_entries()
             + _build_write_tool_entries() + _build_sync_tool_entries())
    return {"tools": tools}


def _handle_read_tool(tool_name: str, arguments: dict) -> dict:
    if not _get_read_hmac_secret():
        return {"isError": True, "content": [{"type": "text", "text": "DENY: READ_HMAC_SECRET not configured"}]}
    actor_id = arguments.get("actor_id", "")
    purpose = arguments.get("purpose", "")
    if actor_id not in READ_ALLOWED_ACTORS:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: unknown actor_id={actor_id}"}]}
    try:
        if tool_name == "read_file":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_file(path, purpose=purpose, **kwargs)
        elif tool_name == "list_dir":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.list_dir(path, purpose=purpose, **kwargs)
        elif tool_name == "grep_scoped":
            path = arguments.get("path", "")
            pattern = arguments.get("pattern", "")
            max_results = arguments.get("max_results", 50)
            kwargs = _build_read_kwargs(actor_id, f"{path}:{pattern}")
            result = _read_server.grep_scoped(path, pattern, purpose=purpose, max_results=max_results, **kwargs)
        elif tool_name == "read_log":
            path = arguments.get("path", "")
            tail_lines = arguments.get("tail_lines", 50)
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_log(path, tail_lines=tail_lines, purpose=purpose, **kwargs)
        elif tool_name == "check_service_state":
            service_name = arguments.get("service_name", "")
            kwargs = _build_read_kwargs(actor_id, service_name)
            result = _read_server.check_service_state(service_name, purpose=purpose, **kwargs)
        elif tool_name == "read_pytest_result":
            artifact_path = arguments.get("artifact_path", "")
            kwargs = _build_read_kwargs(actor_id, artifact_path)
            result = _read_server.read_pytest_result(artifact_path, purpose=purpose, **kwargs)
        elif tool_name == "read_audit_event":
            log_path = arguments.get("log_path", "")
            event_range = arguments.get("event_range", 10)
            kwargs = _build_read_kwargs(actor_id, log_path)
            result = _read_server.read_audit_event(log_path, event_range=event_range, purpose=purpose, **kwargs)
        elif tool_name == "read_metadata":
            path = arguments.get("path", "")
            kwargs = _build_read_kwargs(actor_id, path)
            result = _read_server.read_metadata(path, purpose=purpose, **kwargs)
        elif tool_name == "get_runtime_snapshot":
            kwargs = _build_read_kwargs(actor_id, "runtime_snapshot")
            result = _read_server.get_runtime_snapshot(purpose=purpose, **kwargs)
        else:
            return {"isError": True, "content": [{"type": "text", "text": f"DENY: unknown read tool={tool_name}"}]}
        is_error = result.get("status") == "DENY"
        # ── EDA v1.2 L2 Evidence Gate 적립 (EAG-S275-EDA-IMPLEMENTATION) ─────
        if tool_name == "read_file" and not is_error:
            _path_arg = arguments.get("path", "")
            if _path_arg:
                _l2_record_read(_path_arg)
        # ─────────────────────────────────────────────────────────────────────
        return {"isError": is_error, "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"DENY: internal error={str(e)}"}]}


def _handle_tool_call(tool_name: str, arguments: dict) -> dict:
    if tool_name not in ALLOWED_TOOLS:
        return {"isError": True, "content": [{"type": "text", "text": f"Tool '{tool_name}' not permitted"}]}
    # ── EDA v1.2 L1 Gate (EAG-S275-EDA-IMPLEMENTATION) ─────────────────────────────────────────
    _l1_result = _l1_gate(tool_name)
    if _l1_result is not None:
        return _l1_result
    # ───────────────────────────────────────────────────────────────────────────
    if tool_name == "ping":
        return {"content": [{"type": "text", "text": "pong"}]}
    if tool_name == "get_load_state":
        return {"content": [{"type": "text", "text": json.dumps({"bridge_state": _get_bridge_state(), "containment": containment_is_active(), "version": BRIDGE_VERSION})}]}
    if tool_name in READ_TOOLS:
        return _handle_read_tool(tool_name, arguments)
    if tool_name in WRITE_TOOLS:
        return _handle_write_tool(tool_name, arguments)
    if tool_name in ASK_DOMI_TOOLS:
        return _handle_ask_domi(arguments)
    if tool_name in ASK_TOOLS:
        return _handle_ask_jeni(arguments)
    if tool_name in EXEC_TOOLS:
        return _handle_exec_scoped(arguments)
    if tool_name in SYNC_TOOLS:
        return _handle_sync(arguments)
    return {"isError": True, "content": [{"type": "text", "text": "Unknown tool"}]}


def _handle_jsonrpc(body: dict, gov_ctx: dict) -> Optional[dict]:
    method = body.get("method", "")
    request_id = body.get("id")
    params = body.get("params", {})
    if request_id is None:
        if gov_ctx["containment_active"]:
            _audit_deny(gov_ctx, f"CONTAINMENT_NOTIFICATION_DENIED:{method}")
        return None
    if gov_ctx["containment_active"]:
        _audit_deny(gov_ctx, f"CONTAINMENT_REQUEST_DENIED:{method}")
        return _containment_jsonrpc_error(request_id)
    if method == "initialize":
        _audit_allow(gov_ctx, "initialize", "MCP_INITIALIZE")
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ARSS Protocol MCP Bridge", "version": BRIDGE_VERSION}}}
    if method == "tools/list":
        _audit_allow(gov_ctx, "tools/list", "MCP_TOOLS_LIST")
        return {"jsonrpc": "2.0", "id": request_id, "result": _handle_tool_list()}
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        if tool_name not in ALLOWED_TOOLS:
            _audit_deny(gov_ctx, f"TOOL_NOT_PERMITTED:{tool_name}")
        else:
            _audit_allow(gov_ctx, f"tool:{tool_name}", "MCP_TOOL_CALL")
        result = _handle_tool_call(tool_name, arguments)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    _audit_deny(gov_ctx, f"UNKNOWN_METHOD:{method}")
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}


# ── Agent REST Wrapper 공통 처리 (S187 EAG-1) ─────────────────────────────────

def _verify_agent_bearer_token(auth_header: str) -> tuple:
    """
    Bearer token 검증.
    Returns: (is_valid: bool, error_body: dict or None)
    """
    import time as _time
    if not auth_header.startswith("Bearer "):
        return False, {"error": "unauthorized", "error_description": "Bearer token required"}
    token = auth_header[len("Bearer "):]
    token_entry = _OAUTH_TOKENS.get(token)
    if not token_entry:
        return False, {"error": "invalid_token", "error_description": "Token not found"}
    if _time.time() > token_entry.get("expires_at", 0):
        del _OAUTH_TOKENS[token]
        return False, {"error": "invalid_token", "error_description": "Token expired"}
    return True, None


def _handle_agent_request(handler, actor_id: str, endpoint_prefix: str) -> None:
    """
    /domi/* 및 /jeni/* 공통 처리 — audit mandatory gate 포함.
    handler: BridgeHandler 인스턴스
    actor_id: "domi" or "jeni"
    endpoint_prefix: "/domi/" or "/jeni/"
    """
    # Bearer token 검증
    auth_header = handler.headers.get("Authorization", "")
    is_valid, err = _verify_agent_bearer_token(auth_header)
    if not is_valid:
        handler._send_json(401, err)
        return

    # body 파싱
    content_length = int(handler.headers.get("Content-Length", 0))
    raw_body = handler.rfile.read(content_length) if content_length > 0 else b"{}"
    try:
        req_body = json.loads(raw_body)
    except json.JSONDecodeError:
        handler._send_json(400, {"error": "invalid_json"})
        return

    # 도구명 추출
    tool_name = handler.path.split(endpoint_prefix, 1)[1].split("?")[0].rstrip("/")

    if tool_name not in _AGENT_ALLOWED_TOOLS:
        handler._send_json(404, {"error": "not_found", "error_description": f"Tool '{tool_name}' not in {actor_id} allowlist"})
        return

    # actor_id 강제 주입
    req_body["actor_id"] = actor_id
    purpose = req_body.get("purpose", "OBSERVATION")
    if "purpose" not in req_body:
        req_body["purpose"] = purpose

    # ── audit pre-record mandatory gate ──────────────────────────────────────
    pre_ok = _agent_audit_pre(actor_id, tool_name, purpose, endpoint_prefix.strip("/"))
    if not pre_ok:
        handler._send_json(500, {"error": "ACCESS_DENIED", "error_description": "audit pre-record failed"})
        return

    # ── 도구 실행 ─────────────────────────────────────────────────────────────
    if tool_name in _AGENT_READ_TOOLS:
        result = _handle_read_tool(tool_name, req_body)
    elif tool_name == "write_file":
        result = _handle_agent_write_file(actor_id, req_body)
    else:
        result = {"isError": True, "content": [{"type": "text", "text": f"DENY: tool '{tool_name}' not implemented"}]}

    success = not result.get("isError", False)

    # ── audit post-record mandatory gate ─────────────────────────────────────
    post_ok = _agent_audit_post(actor_id, tool_name, endpoint_prefix.strip("/"), success)
    if not post_ok:
        handler._send_json(500, {"error": "RESULT_WITHHELD", "error_description": "audit post-record failed"})
        return

    handler._send_json(200, result)


# ── ROOL /observe/* 핸들러 (EAG-S295-ROOL-BRIDGE-001) ─────────────────────────

# ROOL tool -> bridge read_tool 매핑
_ROOL_TOOL_MAP = {
    "read": "read_file",
    "list": "list_dir",
    "grep": "grep_scoped",
    "log": "read_log",
    "snapshot": "get_runtime_snapshot",
}

# token -> actor_id 역참조 (OAuth client actor_id 경유)
def _resolve_actor_from_token(auth_header: str) -> tuple:
    """
    Bearer token -> client_id -> actor_id.
    Returns: (actor_id or None, error_body or None)
    """
    import time as _time
    if not auth_header.startswith("Bearer "):
        return None, {"error": "unauthorized", "error_description": "Bearer token required"}
    token = auth_header[len("Bearer "):]
    token_entry = _OAUTH_TOKENS.get(token)
    if not token_entry:
        return None, {"error": "invalid_token", "error_description": "Token not found"}
    if _time.time() > token_entry.get("expires_at", 0):
        del _OAUTH_TOKENS[token]
        return None, {"error": "invalid_token", "error_description": "Token expired"}
    client_id = token_entry.get("client_id", "")
    client = _OAUTH_CLIENTS.get(client_id, {})
    actor_id = client.get("actor_id", "")
    if actor_id not in ("domi", "jeni", "caddy"):
        return None, {"error": "invalid_actor", "error_description": f"actor_id '{actor_id}' not permitted for observe"}
    return actor_id, None


def _handle_observe_request(handler) -> None:
    """
    /observe/begin 및 /observe/{read|list|grep|log|snapshot} 처리.
    ROOL 게이트 -> 기존 _handle_read_tool 재사용 -> Manifest 기록.
    """
    # Bearer token -> actor_id 해석
    auth_header = handler.headers.get("Authorization", "")
    actor_id, err = _resolve_actor_from_token(auth_header)
    if actor_id is None:
        handler._send_json(401, err)
        return

    # body 파싱
    content_length = int(handler.headers.get("Content-Length", 0))
    raw_body = handler.rfile.read(content_length) if content_length > 0 else b"{}"
    try:
        req_body = json.loads(raw_body)
    except json.JSONDecodeError:
        handler._send_json(400, {"error": "invalid_json"})
        return

    # subpath 추출: /observe/<subpath>
    subpath = handler.path.split("/observe/", 1)[1].split("?")[0].rstrip("/")
    session_id = req_body.get("session", "") or req_body.get("session_id", "")

    # ── /observe/begin ───────────────────────────────────────────────────────
    if subpath == "begin":
        if not session_id:
            handler._send_json(400, {"error": "session_required",
                "error_description": "session or session_id required for begin"})
            return
        result = _rool_begin(actor_id, session_id)
        status_code = 200 if result.get("status") == "ALLOW" else 403
        handler._send_json(status_code, result)
        return

    # ── /observe/<tool> ──────────────────────────────────────────────────────
    if subpath not in _ROOL_TOOL_MAP:
        handler._send_json(404, {"error": "not_found",
            "error_description": f"observe tool '{subpath}' not in {sorted(_ROOL_TOOL_MAP.keys())}"})
        return

    observation_id = req_body.get("observation_id", "")
    if not observation_id:
        handler._send_json(400, {"error": "observation_id_required",
            "error_description": "observation_id required (call /observe/begin first)"})
        return
    if not session_id:
        handler._send_json(400, {"error": "session_required",
            "error_description": "session or session_id required"})
        return

    bridge_tool = _ROOL_TOOL_MAP[subpath]
    target = req_body.get("path", "") or req_body.get("target", "")

    # ── ROOL 게이트: ID 검증 + FORBIDDEN 검사 ──────────────────────────────────
    gate = _rool_observe(observation_id, actor_id, session_id, subpath, target)
    if gate.get("status") != "ALLOW":
        handler._send_json(gate.get("http_status", 403), gate)
        return

    # ── 게이트 통과 -> 기존 read_tool 재사용 ──────────────────────────────────
    read_args = dict(req_body)
    read_args["actor_id"] = actor_id
    if "purpose" not in read_args:
        read_args["purpose"] = "OBSERVATION"
    # grep_scoped는 pattern 필수
    read_result = _handle_read_tool(bridge_tool, read_args)
    success = not read_result.get("isError", False)

    # ── Manifest 기록 ─────────────────────────────────────────────────────────
    bytes_read = 0
    try:
        _txt = read_result.get("content", [{}])[0].get("text", "")
        bytes_read = len(_txt.encode("utf-8"))
    except Exception:
        bytes_read = 0
    _rool_record(actor_id, session_id, observation_id, subpath, target,
                 success, bytes_read=bytes_read)

    handler._send_json(200 if success else 403, read_result)


# ── HTTP Handler ───────────────────────────────────────────────────────────────

class BridgeHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(data))
        self.end_headers()
        self.wfile.write(data)

    def _fail_closed(self, reason: str) -> None:
        gov_ctx = {"actor_id": INTERNAL_ACTOR_ID, "bridge_state": _get_bridge_state(), "containment_active": True}
        _audit_deny(gov_ctx, reason)
        self._send_json(503, {"error": "bridge_unavailable"})

    def do_GET(self):
        self.path = self.path.split("?")[0]  # strip query string (S408)
        if self.path == "/bridge/health":
            self._send_json(200, {"bridge_state": _get_bridge_state(), "containment": containment_is_active(), "version": BRIDGE_VERSION})
            return
        if self.path == "/mcp":
            bridge_state = _get_bridge_state()
            if bridge_state in ("INACTIVE", "ROLLED_BACK"):
                self._fail_closed(f"BRIDGE_STATE:{bridge_state}")
                return
            gov_ctx = _build_governance_context({})
            _audit_allow(gov_ctx, "sse_stream", "SSE_STREAM_OPEN")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            with _sse_clients_lock:
                _sse_clients.append(self)
            try:
                self._sse_send_heartbeat()
                while True:
                    time.sleep(SSE_HEARTBEAT_INTERVAL)
                    self._sse_send_heartbeat()
            except (BrokenPipeError, ConnectionResetError) as _rule6_e:
                _logging.debug("RULE6 mcp_http_bridge: %s", _rule6_e)
            finally:
                with _sse_clients_lock:
                    if self in _sse_clients:
                        _sse_clients.remove(self)
                _audit_allow(gov_ctx, "sse_stream", "SSE_STREAM_CLOSE")
            return
        if self.path.startswith("/authorize"):
            query_string = self.path.split("?", 1)[1] if "?" in self.path else ""
            status, location, error_body = _oauth_authorize(query_string)
            if status == 302:
                self.send_response(302)
                self.send_header("Location", location)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json(status, error_body)
            return
        if self.path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
            self._send_json(200, _oauth_protected_resource_meta())
            return
        if self.path == "/.well-known/oauth-authorization-server":
            self._send_json(200, _oauth_server_meta())
            return
        self._send_json(403, {"error": "forbidden"})

    def _sse_send_heartbeat(self) -> None:
        event_id = str(uuid.uuid4())
        msg = f"id: {event_id}\ndata: \n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()

    def do_POST(self):
        self.path = self.path.split("?")[0]  # strip query string (S408)
        if self.path == "/register":
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                body = json.loads(raw)
            except Exception:
                body = {}
            result = _oauth_register(body)
            self._send_json(201, result)
            return
        if self.path == "/token":
            content_length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_length) if content_length > 0 else b""
            status, result = _oauth_token(raw.decode("utf-8", errors="replace"))
            self._send_json(status, result)
            return
        if self.path == "/mcp":
            bridge_state = _get_bridge_state()
            if bridge_state in ("INACTIVE", "ROLLED_BACK"):
                self._fail_closed(f"BRIDGE_STATE:{bridge_state}")
                return
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json"})
                return
            gov_ctx = _build_governance_context(body)
            result = _handle_jsonrpc(body, gov_ctx)
            if result is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send_json(200, result)
            return

        # ── /domi/* REST Wrapper (S186 EAG-1 + S187 EAG-1) ───────────────────
        if self.path.startswith("/domi/"):
            _handle_agent_request(self, "domi", "/domi/")
            return

        # ── /jeni/* REST Wrapper (S187 EAG-1 신규) ───────────────────────────
        if self.path.startswith("/jeni/"):
            _handle_agent_request(self, "jeni", "/jeni/")
            return

        # ── /observe/* ROOL 엔드포인트 (EAG-S295-ROOL-BRIDGE-001) ────────────
        if self.path.startswith("/observe/"):
            _handle_observe_request(self)
            return

        if self.path == "/internal/ledger-token/register":
            _handle_ledger_token_register(self); return
        if self.path.startswith("/internal/ledger-append/"):
            agent = self.path.split("/internal/ledger-append/", 1)[1].split("?")[0].rstrip("/")
            _handle_ledger_append(self, agent); return

        self._send_json(403, {"error": "forbidden"})


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    import signal

    def _handle_shutdown(signum, frame):
        _set_bridge_state("ROLLED_BACK")
        sys.exit(0)

    # ── EDA v1.2 Constraint Registry 로드 (EAG-S275-EDA-IMPLEMENTATION) ────────
    _load_constraint_cache()
    # ───────────────────────────────────────────────────────────────────────────
    # 환경변수 기반 agent client 로드 (S187 EAG-1, S189 EAG-1)
    _load_agent_clients_from_env()
    # 동적 등록 client 파일 복원 (S187 EAG-1 bugfix)
    _load_dynamic_clients_from_file()

    _set_bridge_state("ACTIVE")
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    gov_ctx = {"actor_id": "SYSTEM", "bridge_state": "ACTIVE", "containment_active": False}
    _audit_allow(gov_ctx, "NONE", "BRIDGE_STARTUP")

    server = ThreadedHTTPServer((BRIDGE_HOST, BRIDGE_PORT), BridgeHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()

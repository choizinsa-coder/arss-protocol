"""
AIBA MCP Server POC  v0.2.0
Task:  PT-S125-BOOT-ONDEMAND-001
EAG:   EAG-2 비오(Joshua) 승인 (S126)
설계:  도미 Rev.1 + D-3 PATCH FINAL / 도미 2차 설계 반영 (S126)

=============================================================================
PHASE 정의 (도미 2차 설계)
=============================================================================
PHASE-A (현재):
    Local stdio observability-only MCP.
    L0/L1 계층만 허용. authority containment 우선.

PHASE-B (미착수):
    Boundary hardening.
    throttling / audit isolation / timeout 설계.
    별도 도미 설계 + EAG 필요.

PHASE-C (미착수):
    HTTP/auth evaluation.
    Governance Surface Expansion으로 취급. 별도 governance phase.

PHASE-D (미착수):
    Selective exposure review.
    CLASS-C/D 도구 노출 여부 재검토. EAG 필수.

=============================================================================
MCP 계층 정의 (structural invariant)
=============================================================================
L0 = Ping / Health only          <- PHASE-A 허용
L1 = Metadata visibility         <- PHASE-A 허용
L2 = Read-only operational data  <- PHASE-B 이후
L3 = Restricted governance data  <- PHASE-D 이후 + CVC-01~04 필수
L4 = Mutation / Execution        <- FORBIDDEN (어떤 phase에서도 EAG 없이 불가)

=============================================================================
FAIL_CLOSED 정책 (structural invariant)
=============================================================================
- ALLOWED_TOOLS 미등재 도구: 자동 DENY
- FORBIDDEN_TOOLS 등재 도구: 무조건 DENY (ALLOWED에 있어도 차단)
- PHASE-A 허용 계층(L0/L1) 외 도구: 자동 DENY
- deny-by-default는 레지스트리 구조로 강제 (조건문 의존 없음)
- 모듈 로드 시점에 invariant 위반 탐지 -> RuntimeError

=============================================================================
FORBIDDEN 범위 (도미 2차 설계)
=============================================================================
write / mutation / execution / RPU issuance / workflow trigger /
chain modification / canonical ingress / full context preload
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Audit Trail Logging
# ---------------------------------------------------------------------------

_AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/audit_trail.log"
_LOG_FORMAT = "%(asctime)s [AUDIT] %(message)s"

_handlers: list = [logging.StreamHandler(sys.stderr)]
try:
    os.makedirs(os.path.dirname(_AUDIT_LOG_PATH), exist_ok=True)
    _handlers.append(logging.FileHandler(_AUDIT_LOG_PATH))
except OSError:
    pass  # 로컬 테스트 환경 — stderr만 사용

logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=_handlers)
logger = logging.getLogger("aiba_mcp_poc")

# ---------------------------------------------------------------------------
# 서버 상수
# ---------------------------------------------------------------------------

SERVER_NAME = "aiba-mcp-poc"
SERVER_VERSION = "0.2.0"
AIBA_SYSTEM = "AIBA Self-Evolution-Ready System"
AIBA_VERSION = "v1.5"
VPS_HOST = "159.203.125.1"
CANONICAL_PATH = "/opt/arss/engine/arss-protocol"
CURRENT_PHASE = "PHASE-A"

# ---------------------------------------------------------------------------
# MCP 계층 상수 (structural invariant)
# ---------------------------------------------------------------------------

MCP_LAYER = {
    "L0": "Ping / Health only",
    "L1": "Metadata visibility",
    "L2": "Read-only operational data",
    "L3": "Restricted governance data",
    "L4": "Mutation / Execution -- FORBIDDEN",
}

PHASE_A_ALLOWED_LAYERS = frozenset({"L0", "L1"})

# ---------------------------------------------------------------------------
# FORBIDDEN 도구 목록 (structural invariant)
# 이 목록 등재 이름은 ALLOWED_TOOLS에 있어도 실행 불가.
# 모듈 로드 시점에 충돌 탐지 -> RuntimeError.
# ---------------------------------------------------------------------------

FORBIDDEN_TOOLS: frozenset = frozenset({
    # full preload
    "get_all_context", "load_full_session", "preload_all",
    "get_full_boot", "get_session_context",
    # mutation
    "write_context", "modify_context", "update_session", "patch_state",
    # execution
    "trigger_workflow", "run_pipeline", "execute_command", "invoke_agent",
    # RPU / chain
    "issue_rpu", "write_chain", "modify_chain", "commit_delta",
    # canonical ingress
    "push_canonical", "set_ssot", "override_session",
})

# ---------------------------------------------------------------------------
# FAIL_CLOSED 정책 상수
# ---------------------------------------------------------------------------

FAIL_CLOSED_POLICY = {
    "default": "DENY",
    "unregistered_tool": "DENY -- 허용 레지스트리 미등재 도구 자동 거부",
    "forbidden_tool": "DENY -- FORBIDDEN_TOOLS 등재 도구 무조건 거부",
    "layer_violation": "DENY -- PHASE-A 허용 계층(L0/L1) 외 자동 거부",
    "error_on_ambiguity": "FAIL_CLOSED -- 모호한 요청 거부",
    "authority_ceiling": "L1 -- PHASE-A 최대 허용 계층",
}

# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def _audit(tool_name: str, layer: str, result_summary: str) -> None:
    logger.info(
        "TOOL_CALL tool=%s layer=%s result=%s phase=%s",
        tool_name, layer, result_summary, CURRENT_PHASE,
    )

def _audit_deny(tool_name: str, reason: str) -> None:
    logger.warning(
        "TOOL_DENY tool=%s reason=%s phase=%s policy=FAIL_CLOSED",
        tool_name, reason, CURRENT_PHASE,
    )

# ---------------------------------------------------------------------------
# 도구 구현
# ---------------------------------------------------------------------------

def ping() -> dict:
    """[L0] 서버 생존 확인 -- 고정 응답 반환."""
    result = {
        "status": "ok",
        "message": "AIBA MCP POC server is alive",
        "server": SERVER_NAME,
        "version": SERVER_VERSION,
        "phase": CURRENT_PHASE,
        "mcp_layer": "L0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _audit("ping", "L0", "ok")
    return result

def get_server_status() -> dict:
    """[L1] 서버 및 AIBA 시스템 메타데이터 반환 -- 화이트리스트 고정값만."""
    result = {
        "server_name": SERVER_NAME,
        "server_version": SERVER_VERSION,
        "aiba_system": AIBA_SYSTEM,
        "aiba_version": AIBA_VERSION,
        "vps_host": VPS_HOST,
        "canonical_path": CANONICAL_PATH,
        "mcp_poc_task": "PT-S125-BOOT-ONDEMAND-001",
        "eag_stage": "EAG-2_COMPLETE",
        "current_phase": CURRENT_PHASE,
        "mcp_layer": "L1",
        "allowed_layers": sorted(PHASE_A_ALLOWED_LAYERS),
        "fail_closed_policy": FAIL_CLOSED_POLICY["default"],
        "status": "operational",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _audit("get_server_status", "L1", "operational")
    return result

def get_current_epoch() -> dict:
    """[L1] 현재 epoch 및 UTC 타임스탬프 반환."""
    now = datetime.now(timezone.utc)
    result = {
        "epoch_ms": int(now.timestamp() * 1000),
        "epoch_s": int(now.timestamp()),
        "utc_iso": now.isoformat(),
        "source": "vps_system_clock",
        "mcp_layer": "L1",
        "note": "Used for CLASS-B Integrity Contract canonical_epoch field",
    }
    _audit("get_current_epoch", "L1", f"epoch_ms={result['epoch_ms']}")
    return result

# ---------------------------------------------------------------------------
# 허용 레지스트리 빌더 (deny-by-default 구조적 강제)
# ---------------------------------------------------------------------------

def _build_allowed_tools() -> dict:
    """
    모듈 로드 시점에 invariant 검증:
      1. FORBIDDEN_TOOLS 충돌 -> RuntimeError
      2. PHASE-A 계층 외 등재 -> RuntimeError
    """
    registry = {
        "ping": {
            "name": "ping",
            "layer": "L0",
            "description": "[L0] AIBA MCP POC 서버 생존 확인. 고정 응답 반환.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": ping,
        },
        "get_server_status": {
            "name": "get_server_status",
            "layer": "L1",
            "description": "[L1] AIBA 시스템 메타데이터를 화이트리스트 고정값으로 반환.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": get_server_status,
        },
        "get_current_epoch": {
            "name": "get_current_epoch",
            "layer": "L1",
            "description": "[L1] 현재 epoch(ms/s) 및 UTC 타임스탬프 반환.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "fn": get_current_epoch,
        },
    }

    for name, entry in registry.items():
        if name in FORBIDDEN_TOOLS:
            raise RuntimeError(
                f"[FAIL_CLOSED] FORBIDDEN 도구 '{name}'이 허용 레지스트리에 등재됨 -- "
                "즉시 중단."
            )
        if entry["layer"] not in PHASE_A_ALLOWED_LAYERS:
            raise RuntimeError(
                f"[FAIL_CLOSED] 도구 '{name}' 계층 '{entry['layer']}'은 "
                f"PHASE-A 허용 범위 외부 -- 즉시 중단."
            )

    return registry

ALLOWED_TOOLS: dict = _build_allowed_tools()

# ---------------------------------------------------------------------------
# deny-by-default 디스패처
# ---------------------------------------------------------------------------

def _dispatch(tool_name: str) -> dict:
    """
    순서:
      1. FORBIDDEN_TOOLS 검사 -> DENY
      2. ALLOWED_TOOLS 미등재 검사 -> DENY
      3. 계층 검사 -> DENY
      4. 실행
    """
    if tool_name in FORBIDDEN_TOOLS:
        _audit_deny(tool_name, "FORBIDDEN_TOOLS")
        raise PermissionError(f"[FAIL_CLOSED] FORBIDDEN 도구: {tool_name}")

    if tool_name not in ALLOWED_TOOLS:
        _audit_deny(tool_name, "NOT_IN_REGISTRY")
        raise PermissionError(f"[FAIL_CLOSED] 미등재 도구: {tool_name}")

    entry = ALLOWED_TOOLS[tool_name]
    if entry["layer"] not in PHASE_A_ALLOWED_LAYERS:
        _audit_deny(tool_name, f"LAYER_VIOLATION:{entry['layer']}")
        raise PermissionError(
            f"[FAIL_CLOSED] 계층 위반 -- tool={tool_name} layer={entry['layer']}"
        )

    return entry["fn"]()

# ---------------------------------------------------------------------------
# MCP 프로토콜 핸들러 (stdio JSON-RPC)
# ---------------------------------------------------------------------------

def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

def _handle(request: dict) -> None:
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        _send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        })

    elif method == "tools/list":
        # ALLOWED_TOOLS만 노출 (FORBIDDEN은 목록에도 미노출)
        tool_list = [
            {
                "name": e["name"],
                "description": e["description"],
                "inputSchema": e["inputSchema"],
            }
            for e in ALLOWED_TOOLS.values()
        ]
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tool_list}})

    elif method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        try:
            result = _dispatch(tool_name)
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
                    "isError": False,
                },
            })
        except PermissionError as exc:
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": str(exc)},
            })
        except Exception as exc:
            logger.error("TOOL_ERROR tool=%s error=%s", tool_name, str(exc))
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "result": {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
            })

    elif method == "notifications/initialized":
        pass

    else:
        if req_id is not None:
            _send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })

def main() -> None:
    logger.info(
        "AIBA MCP POC Server v%s starting -- phase=%s task=PT-S125-BOOT-ONDEMAND-001 "
        "policy=FAIL_CLOSED allowed_layers=%s",
        SERVER_VERSION, CURRENT_PHASE, sorted(PHASE_A_ALLOWED_LAYERS),
    )
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            _handle(request)
        except json.JSONDecodeError as exc:
            logger.error("JSON_DECODE_ERROR: %s", exc)
            _send({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            })

if __name__ == "__main__":
    main()

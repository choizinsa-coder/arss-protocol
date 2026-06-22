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


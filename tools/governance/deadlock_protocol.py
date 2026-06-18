"""
deadlock_protocol.py  v1.0
AIBA Governance 3-5: Deadlock Protocol
EAG: EAG-S263-3-5-001

규칙 1: TRUST_NOT_READY 에 violations 없으면 TRUST_ADVISORY 로 강등
규칙 2: 선언/구현 층위 경계 자동 판정
규칙 3: 라운드 카운터 — Warning(2) / Escalate(3+)
"""
from __future__ import annotations
from .deadlock_models import ValidationResult, DeadlockState


# ── 규칙 1 ────────────────────────────────────────────────────────────────────

def validate_not_ready_payload(result: ValidationResult) -> ValidationResult:
    """
    규칙 1 게이트.
    TRUST_NOT_READY + violations 비어 있음 → TRUST_ADVISORY 로 강등.
    violations 있으면 원본 유지 (blocking 효력 유지).
    """
    if result.status == "TRUST_NOT_READY" and not result.violations:
        return ValidationResult(
            status="TRUST_ADVISORY",
            violations=[],
            advisories=result.advisories + ["AUTO_DOWNGRADED: no guardrail violations specified"],
        )
    return result


# ── 규칙 2 ────────────────────────────────────────────────────────────────────

_DECLARATION_KEYWORDS = {
    "principle", "vision", "charter", "governance",
    "policy", "declaration", "mandate", "guideline",
    "선언", "원칙", "정책", "거버넌스",
}

_IMPLEMENTATION_KEYWORDS = {
    "file", "path", "function", "runtime", "service",
    "code", "script", "deploy", "class", "module",
    "threshold", "sla", "metric", "count", "value",
    "파일", "경로", "함수", "런타임", "배포", "임계값",
}


def classify_layer(proposal: dict) -> str:
    """
    규칙 2 분류기.
    proposal["text"] 에서 키워드를 감지하여
    DECLARATION / IMPLEMENTATION / HYBRID 중 하나를 반환.
    """
    text = str(proposal.get("text", "")).lower()
    tokens = set(text.replace(",", " ").replace(".", " ").split())

    has_decl = bool(tokens & _DECLARATION_KEYWORDS)
    has_impl = bool(tokens & _IMPLEMENTATION_KEYWORDS)

    if has_decl and has_impl:
        return "HYBRID"
    if has_impl:
        return "IMPLEMENTATION"
    return "DECLARATION"


# ── 규칙 3 ────────────────────────────────────────────────────────────────────

def evaluate_deadlock(proposal_id: str, current_round: int) -> dict:
    """
    규칙 3 라운드 카운터.

    round 0~1 : NORMAL
    round 2   : WARNING  (deadlock=False, escalate=False)
    round 3+  : DEADLOCK (deadlock=True,  escalate=True)

    도미 권고(S263): 2라운드는 Warning, 3라운드부터 Escalate.
    한 번의 수정 기회를 보장하여 과도한 상위 이관 방지.

    Returns:
        {
            "proposal_id": str,
            "round": int,
            "deadlock": bool,
            "escalate": bool,
            "status": "NORMAL" | "WARNING" | "DEADLOCK"
        }
    """
    if current_round <= 1:
        status = "NORMAL"
        deadlock, escalate = False, False
    elif current_round == 2:
        status = "WARNING"
        deadlock, escalate = False, False
    else:  # 3+
        status = "DEADLOCK"
        deadlock, escalate = True, True

    return {
        "proposal_id": proposal_id,
        "round":       current_round,
        "deadlock":    deadlock,
        "escalate":    escalate,
        "status":      status,
    }

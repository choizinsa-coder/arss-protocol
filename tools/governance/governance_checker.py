"""
governance_checker.py
governance_checker v1.0 Rev.2
S103 EAG-1 승인 — 비오(Joshua)

Read-only registry validation module.
검증 대상: Approved Dependency Registry v1.0 + Legacy Exception Registry v1.0
Receipt Scope: R1 (Verdict Receipt Required)
"""

import logging as _logging
import json
import hashlib
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional


# ── 상수 ──────────────────────────────────────────────────────────────────────

REGISTRY_DIR = Path(__file__).parent
APPROVED_DEP_REGISTRY_FILE = REGISTRY_DIR / "approved_dependency_registry_v1.0.json"
LEGACY_EXCEPTION_REGISTRY_FILE = REGISTRY_DIR / "legacy_exception_registry_v1.0.json"

ALLOWED_AGENT_IDS = {"caddy", "domi", "jeni", "beo"}

STOP_ON_UNAPPROVED_DEP = "STOP_ON_UNAPPROVED_DEP"
EXPIRED_EXCEPTION_STOP = "EXPIRED_EXCEPTION_STOP"
CROSS_REGISTRY_CONFLICT_STOP = "CROSS_REGISTRY_CONFLICT_STOP"
AWARENESS_BOUNDARY_VIOLATION_STOP = "AWARENESS_BOUNDARY_VIOLATION_STOP"
CURRENT_SESSION_MISSING = "CURRENT_SESSION_MISSING"
CURRENT_SESSION_MALFORMED = "CURRENT_SESSION_MALFORMED"


# ── 내부 유틸 ─────────────────────────────────────────────────────────────────

def _load_registry(path: Path) -> dict:
    """Registry 파일을 read-only로 로드한다."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _hash_registry(data: dict) -> str:
    """Registry 내용의 SHA256 해시를 반환한다."""
    serialized = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _parse_session_number(session_str: str) -> Optional[int]:
    """'S<number>' 형식을 파싱하여 정수 반환. 실패 시 None."""
    if not isinstance(session_str, str):
        return None
    s = session_str.strip()
    if s.startswith("S") and s[1:].isdigit():
        return int(s[1:])
    return None


def _validate_current_session(current_session) -> tuple:
    """
    current_session 유효성 검증.
    반환: (is_valid: bool, session_number: Optional[int], stop_reason: Optional[str])
    """
    if current_session is None:
        return False, None, CURRENT_SESSION_MISSING
    parsed = _parse_session_number(str(current_session))
    if parsed is None:
        return False, None, CURRENT_SESSION_MALFORMED
    return True, parsed, None


# ── expiry 판정 ───────────────────────────────────────────────────────────────

def _check_expiry(entry: dict, current_session_number: Optional[int]) -> dict:
    """
    Legacy Exception Registry 단일 항목의 만료 판정.
    반환: {"expired": bool, "verdict": str, "risk_tier": str,
           "stop_required": bool, "stop_reason": Optional[str],
           "review_reason": Optional[str]}
    """
    expiry_policy = entry.get("expiry_policy")

    # 필드 부재
    if expiry_policy is None:
        return {
            "expired": False,
            "verdict": "REVIEW",
            "risk_tier": "T1",
            "stop_required": False,
            "stop_reason": None,
            "review_reason": "EXPIRY_POLICY_MISSING",
        }

    policy_type = expiry_policy.get("type", "NONE")

    if policy_type == "NONE":
        return {
            "expired": False,
            "verdict": "PASS",
            "risk_tier": "T0",
            "stop_required": False,
            "stop_reason": None,
            "review_reason": None,
        }

    if policy_type == "DATE":
        expiry_date_str = expiry_policy.get("expiry_date")
        if expiry_date_str:
            try:
                expiry_date = date.fromisoformat(expiry_date_str)
                if date.today() > expiry_date:
                    return {
                        "expired": True,
                        "verdict": "FAIL",
                        "risk_tier": "T3",
                        "stop_required": True,
                        "stop_reason": EXPIRED_EXCEPTION_STOP,
                        "review_reason": None,
                    }
            except ValueError as _rule6_e:
                _logging.debug("RULE6 governance_checker: %s", _rule6_e)
        return {
            "expired": False,
            "verdict": "PASS",
            "risk_tier": "T0",
            "stop_required": False,
            "stop_reason": None,
            "review_reason": None,
        }

    if policy_type == "SESSION":
        expiry_session_str = expiry_policy.get("expiry_session")
        expiry_session_number = _parse_session_number(str(expiry_session_str)) if expiry_session_str else None
        if expiry_session_number is not None and current_session_number is not None:
            if current_session_number > expiry_session_number:
                return {
                    "expired": True,
                    "verdict": "FAIL",
                    "risk_tier": "T3",
                    "stop_required": True,
                    "stop_reason": EXPIRED_EXCEPTION_STOP,
                    "review_reason": None,
                }
        return {
            "expired": False,
            "verdict": "PASS",
            "risk_tier": "T0",
            "stop_required": False,
            "stop_reason": None,
            "review_reason": None,
        }

    if policy_type == "CONDITION":
        return {
            "expired": False,
            "verdict": "REVIEW",
            "risk_tier": "T1",
            "stop_required": False,
            "stop_reason": None,
            "review_reason": "CONDITION_EXPIRY_REQUIRES_HUMAN_REVIEW",
        }

    # 알 수 없는 타입
    return {
        "expired": False,
        "verdict": "REVIEW",
        "risk_tier": "T1",
        "stop_required": False,
        "stop_reason": None,
        "review_reason": "UNKNOWN_EXPIRY_POLICY_TYPE",
    }


# ── Approved Dependency Registry 검증 ────────────────────────────────────────

def _check_approved_dep_registry(registry: dict) -> list:
    """
    Approved Dependency Registry 항목별 검증.
    반환: list of finding dicts
    """
    findings = []
    entries = registry.get("entries", [])
    approved_names = set()

    for entry in entries:
        name = entry.get("package_name", "UNKNOWN")
        approved_by = entry.get("approved_by")
        security_status = entry.get("security_review_status", "PENDING")

        approved_names.add(name)

        # transitive deps도 approved 목록에 추가
        for td in entry.get("transitive_deps", []):
            approved_names.add(td)

        if approved_by is None and security_status == "PENDING":
            findings.append({
                "target": name,
                "verdict": "REVIEW",
                "risk_tier": "T1",
                "stop_required": False,
                "stop_reason": None,
                "review_reason": "SECURITY_REVIEW_PENDING",
            })

    return findings, approved_names


# ── Legacy Exception Registry 검증 ───────────────────────────────────────────

def _check_legacy_exception_registry(registry: dict, current_session_number: Optional[int]) -> list:
    """
    Legacy Exception Registry 항목별 검증 (만료 판정 포함).
    반환: list of finding dicts
    """
    findings = []
    entries = registry.get("entries", [])

    for entry in entries:
        exception_id = entry.get("exception_id", "UNKNOWN")
        expiry_result = _check_expiry(entry, current_session_number)

        findings.append({
            "target": exception_id,
            **expiry_result,
        })

    return findings


# ── Cross-Registry Conflict Check ────────────────────────────────────────────

def _check_cross_registry_conflict(approved_names: set, legacy_registry: dict) -> list:
    """
    Approved Dependency Registry와 Legacy Exception Registry 교차 검증.
    반환: list of finding dicts
    """
    findings = []
    entries = legacy_registry.get("entries", [])

    CONFLICT_CLASSIFICATIONS = {
        "BLOCKED", "QUARANTINED", "DEPRECATED",
        "DELETION_REVIEW", "FORBIDDEN",
    }

    for entry in entries:
        exception_id = entry.get("exception_id", "UNKNOWN")
        module_or_file = entry.get("module_or_file", "")
        classification = entry.get("classification", "")

        # approved dependency 이름이 legacy exception의 module_or_file에 포함되는지 검사
        for approved_name in approved_names:
            if approved_name.lower() in module_or_file.lower():
                if classification in CONFLICT_CLASSIFICATIONS:
                    findings.append({
                        "target": f"{exception_id} ↔ {approved_name}",
                        "verdict": "FAIL",
                        "risk_tier": "T2",
                        "stop_required": True,
                        "stop_reason": CROSS_REGISTRY_CONFLICT_STOP,
                        "review_reason": None,
                        "detail": f"Approved dep '{approved_name}' conflicts with legacy exception '{exception_id}' (classification={classification})",
                    })

    return findings


# ── Awareness Metadata 생성 ───────────────────────────────────────────────────

def _build_awareness_metadata(
    registry_version: str,
    registry_hash: str,
    verdict: str,
    risk_tier: str,
    receipt_id: str,
    requesting_agent_id: Optional[str],
) -> dict:
    """
    Awareness Metadata 생성 (허용 필드만 포함).
    Registry body 노출 금지.
    """
    metadata = {
        "registry_version": registry_version,
        "registry_hash": registry_hash,
        "validation_timestamp": datetime.utcnow().isoformat() + "Z",
        "verdict": verdict,
        "risk_tier": risk_tier,
        "receipt_id": receipt_id,
    }
    if requesting_agent_id is not None:
        metadata["requesting_agent_id"] = requesting_agent_id
    return metadata


# ── 종합 verdict 계산 ─────────────────────────────────────────────────────────

def _aggregate_verdict(findings: list) -> tuple:
    """
    findings 전체에서 최종 verdict / risk_tier / stop_required / stop_reason 산출.
    반환: (verdict, risk_tier, stop_required, stop_reason)
    """
    verdict = "PASS"
    risk_tier = "T0"
    stop_required = False
    stop_reason = None

    tier_order = {"T0": 0, "T1": 1, "T2": 2, "T3": 3}

    for f in findings:
        fv = f.get("verdict", "PASS")
        ft = f.get("risk_tier", "T0")
        fs = f.get("stop_required", False)
        fr = f.get("stop_reason")

        if fv == "FAIL":
            verdict = "FAIL"
        elif fv == "REVIEW" and verdict != "FAIL":
            verdict = "REVIEW"

        if tier_order.get(ft, 0) > tier_order.get(risk_tier, 0):
            risk_tier = ft

        if fs:
            stop_required = True
            if stop_reason is None:
                stop_reason = fr

    return verdict, risk_tier, stop_required, stop_reason


# ── R1 Receipt 생성 ───────────────────────────────────────────────────────────

def _build_r1_receipt(
    receipt_id: str,
    verdict: str,
    risk_tier: str,
    stop_required: bool,
    stop_reason: Optional[str],
    findings: list,
    awareness_metadata: dict,
) -> dict:
    """R1 Verdict Receipt 생성."""
    return {
        "receipt_id": receipt_id,
        "receipt_scope": "R1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "verdict": verdict,
        "risk_tier": risk_tier,
        "stop_required": stop_required,
        "stop_reason": stop_reason,
        "findings_count": len(findings),
        "findings": findings,
        "awareness_metadata": awareness_metadata,
    }


# ── 공개 API ──────────────────────────────────────────────────────────────────

def run_governance_check(
    current_session: str,
    requesting_agent_id: Optional[str] = None,
    approved_dep_registry_path: Optional[Path] = None,
    legacy_exception_registry_path: Optional[Path] = None,
) -> dict:
    """
    governance_checker 메인 진입점.

    Args:
        current_session: 현재 세션 번호 문자열 (예: "S103"). caller가 명시적으로 주입.
        requesting_agent_id: 요청 에이전트 ID (projection 제한용, verdict 계산 미사용).
        approved_dep_registry_path: Approved Dependency Registry 파일 경로 (기본값: 패키지 내 경로).
        legacy_exception_registry_path: Legacy Exception Registry 파일 경로 (기본값: 패키지 내 경로).

    Returns:
        R1 Receipt dict
    """
    receipt_id = str(uuid.uuid4())

    # current_session 검증
    is_valid_session, current_session_number, session_stop_reason = _validate_current_session(current_session)

    all_findings = []

    # SESSION 타입 expiry 판정에 current_session이 필요한데 missing/malformed인 경우
    # → 즉시 FAIL (T2) + STOP. 단, DATE/NONE/CONDITION 검증은 계속 진행.
    if not is_valid_session:
        all_findings.append({
            "target": "current_session",
            "verdict": "FAIL",
            "risk_tier": "T2",
            "stop_required": True,
            "stop_reason": session_stop_reason,
            "review_reason": None,
        })

    # Registry 로드
    dep_path = approved_dep_registry_path or APPROVED_DEP_REGISTRY_FILE
    lex_path = legacy_exception_registry_path or LEGACY_EXCEPTION_REGISTRY_FILE

    dep_registry = _load_registry(dep_path)
    lex_registry = _load_registry(lex_path)

    dep_hash = _hash_registry(dep_registry)
    lex_hash = _hash_registry(lex_registry)

    # Approved Dependency Registry 검증
    dep_findings, approved_names = _check_approved_dep_registry(dep_registry)
    all_findings.extend(dep_findings)

    # Legacy Exception Registry 검증 (만료 판정)
    lex_findings = _check_legacy_exception_registry(
        lex_registry,
        current_session_number if is_valid_session else None,
    )
    all_findings.extend(lex_findings)

    # Cross-Registry Conflict Check
    cross_findings = _check_cross_registry_conflict(approved_names, lex_registry)
    all_findings.extend(cross_findings)

    # 종합 verdict
    verdict, risk_tier, stop_required, stop_reason = _aggregate_verdict(all_findings)

    # Awareness Metadata (Registry body 노출 금지)
    combined_hash = hashlib.sha256(
        (dep_hash + lex_hash).encode("utf-8")
    ).hexdigest()

    registry_version = (
        f"{dep_registry.get('registry_id', 'unknown')}+"
        f"{lex_registry.get('registry_id', 'unknown')}"
    )

    # requesting_agent_id 유효성 확인 (projection 제한용)
    effective_agent_id = None
    if requesting_agent_id is not None:
        if requesting_agent_id in ALLOWED_AGENT_IDS:
            effective_agent_id = requesting_agent_id
        else:
            all_findings.append({
                "target": "requesting_agent_id",
                "verdict": "REVIEW",
                "risk_tier": "T1",
                "stop_required": False,
                "stop_reason": None,
                "review_reason": "UNKNOWN_AGENT_ID",
            })
            # verdict 재계산
            verdict, risk_tier, stop_required, stop_reason = _aggregate_verdict(all_findings)

    awareness_metadata = _build_awareness_metadata(
        registry_version=registry_version,
        registry_hash=combined_hash,
        verdict=verdict,
        risk_tier=risk_tier,
        receipt_id=receipt_id,
        requesting_agent_id=effective_agent_id,
    )

    return _build_r1_receipt(
        receipt_id=receipt_id,
        verdict=verdict,
        risk_tier=risk_tier,
        stop_required=stop_required,
        stop_reason=stop_reason,
        findings=all_findings,
        awareness_metadata=awareness_metadata,
    )

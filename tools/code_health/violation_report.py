ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
violation_report.py — Code Health Enforcement Layer v1.0
AIBA Code Health Protocol
위반 보고 구조 모듈
"""

import json
from typing import List, Dict, Any
from tools.code_health.rule_loader import SEVERITY_FAIL, SEVERITY_REVIEW, GATE_ID, LAYER_VERSION


def build_violation(
    rule_id: str,
    file: str,
    violation_type: str,
    detail: str,
    severity: str,
) -> Dict[str, Any]:
    """단일 위반 항목 구성"""
    return {
        "rule_id": rule_id,
        "file": file,
        "type": violation_type,
        "detail": detail,
        "severity": severity,
    }


def build_report(
    violations: List[Dict[str, Any]],
    total_checked: int,
) -> Dict[str, Any]:
    """
    최종 보고서 구성
    fail_count > 0 → pass = False
    """
    fail_count = sum(1 for v in violations if v["severity"] == SEVERITY_FAIL)
    review_count = sum(1 for v in violations if v["severity"] == SEVERITY_REVIEW)

    return {
        "pass": fail_count == 0,
        "gate": GATE_ID,
        "layer_version": LAYER_VERSION,
        "violations": violations,
        "summary": {
            "total_checked": total_checked,
            "total_violations": len(violations),
            "fail_count": fail_count,
            "review_required_count": review_count,
        },
    }


def build_exception_report(rule_id: str, file: str, exc: Exception) -> Dict[str, Any]:
    """
    validator 내부 exception 발생 시 자동 FAIL 보고서
    fail-closed 보장 — PASS 반환 절대 금지
    """
    violation = build_violation(
        rule_id=rule_id,
        file=file,
        violation_type="VALIDATOR_EXCEPTION",
        detail=f"Internal exception: {type(exc).__name__}: {exc}",
        severity=SEVERITY_FAIL,
    )
    return build_report(violations=[violation], total_checked=0)


def format_report(report: Dict[str, Any]) -> str:
    """보고서 JSON 직렬화"""
    return json.dumps(report, indent=2, ensure_ascii=False)


def is_blocked(report: Dict[str, Any]) -> bool:
    """FAIL 항목 존재 여부 — EAG-3 차단 판정"""
    return not report.get("pass", False)

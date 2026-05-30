"""
validation_runner.py
AIBA Sync Layer — Validation Runner (P3-T5)
SSOT: Domi Phase 3 Design (S171) / EAG-1 Approved (비오(Joshua))

역할:
  - 4개 validator 순차 실행: receipt → consistency → transport → fallback
  - validator 실패가 다른 validator를 차단하지 않음 (독립 실행)
  - 집계 우선순위: FAIL > UNKNOWN > PASS
  - ValidationReport 생성 (machine-readable, HG-2 E2E evidence 대비)

금지:
  - validator 간 직접 호출
  - 수정 / 복구 / 재배포
  - UNKNOWN → PASS 승격
"""

import logging
from datetime import datetime, timezone, timedelta

from tools.sync_layer.validator import receipt_validator
from tools.sync_layer.validator import consistency_validator
from tools.sync_layer.validator import transport_validator
from tools.sync_layer.validator import fallback_validator

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"

VALIDATOR_VERSION = "VALIDATION_LAYER_v1"


def run_all() -> dict:
    """
    전체 Validation 실행 진입점.
    receipt → consistency → transport → fallback 순차 실행.
    반환: ValidationReport (machine-readable, HG-2 evidence 대비)
    CC=3
    """
    executed_at = datetime.now(KST).isoformat()
    results = _execute_validators()
    overall = _aggregate(results)

    report = _build_report(overall, executed_at, results)
    logger.info(
        "VALIDATION_COMPLETE: overall=%s executed_at=%s validators=%d",
        overall, executed_at, len(results),
    )
    return report


def _execute_validators() -> list:
    """
    4개 validator 순차 실행.
    각 validator 예외는 UNKNOWN으로 처리 (fail-closed).
    실패해도 다음 validator 계속 실행.
    CC=4
    """
    validators = [
        ("receipt", receipt_validator.validate),
        ("consistency", consistency_validator.validate),
        ("transport", transport_validator.validate),
        ("fallback", fallback_validator.validate),
    ]
    results = []
    for name, fn in validators:
        try:
            result = fn()
        except Exception as exc:
            logger.error("VALIDATOR_EXCEPTION: %s — %s", name, exc)
            result = {
                "validator": name,
                "verdict": VERDICT_UNKNOWN,
                "error": str(exc),
            }
        results.append(result)
    return results


def _aggregate(results: list) -> str:
    """
    집계 우선순위: FAIL > UNKNOWN > PASS
    CC=3
    """
    verdicts = {r.get("verdict") for r in results}
    if VERDICT_FAIL in verdicts:
        return VERDICT_FAIL
    if VERDICT_UNKNOWN in verdicts:
        return VERDICT_UNKNOWN
    return VERDICT_PASS


def _build_report(overall: str, executed_at: str, results: list) -> dict:
    """
    ValidationReport 빌드.
    HG-2 E2E evidence 연결 가능 machine-readable 구조 (J-6 PASS 기준).
    CC=1
    """
    return {
        "report_type": "ValidationReport",
        "validator_version": VALIDATOR_VERSION,
        "overall_verdict": overall,
        "executed_at": executed_at,
        "validator_results": results,
        "evidence_refs": _collect_evidence_refs(results),
        "p3_task": "P3-T5",
        "hg2_ready": True,
    }


def _collect_evidence_refs(results: list) -> list:
    """
    각 validator 결과에서 evidence reference 수집.
    detail이 있는 validator만 포함.
    CC=2
    """
    refs = []
    for r in results:
        details = r.get("details", [])
        if details:
            refs.append({
                "validator": r.get("validator"),
                "verdict": r.get("verdict"),
                "detail_count": len(details),
            })
    return refs


def get_runner_status() -> dict:
    """Validation Runner 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "validation_runner",
        "layer": "sync_layer/validator",
        "p3_task": "P3-T5",
        "validator_version": VALIDATOR_VERSION,
        "validators": ["receipt", "consistency", "transport", "fallback"],
        "aggregation_priority": "FAIL > UNKNOWN > PASS",
        "hg2_evidence_ready": True,
    }

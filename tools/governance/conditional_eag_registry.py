#!/usr/bin/env python3
"""
conditional_eag_registry.py v1.0.0
Conditional EAG Registry -- Always-On Phase 1
EAG: EAG-S326-CEAG-001

Decision OS v1.0 Section 16.4 Conditional EAG 구현.
조건을 미리 승인하면 조건 충족 시 시스템이 자동 착수한다.
전역 회로 차단기: 24시간 내 자동 실행 총합 3건 초과 불가.

Area 5 sovereign_authority.py 패턴 준용:
  - 함수 기반 API
  - jsonl append-only
  - schema 버전 관리
  - custom exception
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S326-CEAG-001"

ROOT              = Path("/opt/arss/engine/arss-protocol")
REGISTRY_PATH     = ROOT / "runtime/governance/conditional_eag_registry.jsonl"
EXECUTIONS_PATH   = ROOT / "runtime/governance/conditional_eag_executions.jsonl"

GLOBAL_CIRCUIT_LIMIT    = 3
GLOBAL_CIRCUIT_WINDOW_H = 24


class ExecutionResult(Enum):
    ALLOW                = "ALLOW"
    DENIED               = "DENIED"
    CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"


class ConditionalEAGError(ValueError):
    """Conditional EAG Registry 유효성 검증 실패 시 발생."""
    pass


@dataclass
class ConditionalEAGEntry:
    """Conditional EAG 항목 -- Decision OS v1.0 Section 16.4."""
    id:                    str
    condition_description: str
    action_description:    str
    limit_per_days:        int
    expires_at:            str
    eag_approval_id:       str

    def validate(self) -> None:
        """필수 필드 비어있지 않은지 검증."""
        for field in ("id", "condition_description", "action_description",
                      "expires_at", "eag_approval_id"):
            val = getattr(self, field)
            if not val or not str(val).strip():
                raise ConditionalEAGError(
                    "required field missing: '{}'".format(field)
                )
        if not isinstance(self.limit_per_days, int) or self.limit_per_days <= 0:
            raise ConditionalEAGError(
                "limit_per_days must be positive integer"
            )


def _load_jsonl(path: Path) -> list:
    """jsonl 파일 전체 로드 -- 파일 없으면 빈 리스트."""
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def register(entry: ConditionalEAGEntry) -> dict:
    """
    Conditional EAG 항목을 레지스트리에 등록.
    중복 id 재등록 시 ConditionalEAGError 발생.
    """
    entry.validate()
    existing = _load_jsonl(REGISTRY_PATH)
    for e in existing:
        if e.get("id") == entry.id:
            raise ConditionalEAGError(
                "duplicate entry id: '{}'".format(entry.id)
            )
    record = asdict(entry)
    record["schema"]        = "conditional_eag_entry_v1"
    record["version"]       = VERSION
    record["registered_at"] = datetime.now(timezone.utc).isoformat()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def get_entry(entry_id: str) -> Optional[dict]:
    """id로 레지스트리에서 항목 조회 (가장 최근 등록 반환)."""
    found = None
    for e in _load_jsonl(REGISTRY_PATH):
        if e.get("id") == entry_id:
            found = e
    return found


def get_all_entries() -> list:
    """레지스트리 전체 항목 반환."""
    return _load_jsonl(REGISTRY_PATH)


def _evaluate_ceag001(current_metrics: dict) -> bool:
    """CEAG-001 조건 평가: GHS.Calibration_Error_Rate > 0.20"""
    rate = float(current_metrics.get("calibration_error_rate", 0.0))
    return rate > 0.20


_CONDITION_EVALUATORS = {
    "GHS.Calibration_Error_Rate > 0.20": _evaluate_ceag001,
}


def evaluate_condition(entry_id: str, current_metrics: dict) -> tuple:
    """
    Conditional EAG 조건 평가.
    Returns: (bool, reason_string)
      True  -> 조건 충족
      False -> 이유 문자열 포함
    """
    entry = get_entry(entry_id)
    if entry is None:
        return (False, "ENTRY_NOT_FOUND")
    now = datetime.now(timezone.utc)
    try:
        expires = datetime.fromisoformat(entry["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            return (False, "EXPIRED")
    except (ValueError, KeyError):
        return (False, "INVALID_EXPIRES_AT")
    condition = entry.get("condition_description", "")
    evaluator = _CONDITION_EVALUATORS.get(condition)
    if evaluator is None:
        return (False, "UNKNOWN_CONDITION")
    result = evaluator(current_metrics)
    return (result, "CONDITION_MET" if result else "CONDITION_NOT_MET")


def record_execution(entry_id: str, trigger_reason: str) -> str:
    """
    조건 충족 시 실행 기록 저장.
    전역 회로 차단기 + 개별 한도 + 만료 검사 후 ALLOW/DENIED/CIRCUIT_BREAKER_OPEN 반환.
    """
    now = datetime.now(timezone.utc)
    executions = _load_jsonl(EXECUTIONS_PATH)
    window_start = now - timedelta(hours=GLOBAL_CIRCUIT_WINDOW_H)
    recent_global = [
        e for e in executions
        if e.get("result") == ExecutionResult.ALLOW.value
        and _parse_iso(e.get("executed_at", "")) >= window_start
    ]
    if len(recent_global) >= GLOBAL_CIRCUIT_LIMIT:
        return ExecutionResult.CIRCUIT_BREAKER_OPEN.value
    entry = get_entry(entry_id)
    if entry is None:
        return ExecutionResult.DENIED.value
    try:
        expires = datetime.fromisoformat(entry["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now > expires:
            return ExecutionResult.DENIED.value
    except (ValueError, KeyError):
        return ExecutionResult.DENIED.value
    limit_days = int(entry.get("limit_per_days", 30))
    limit_start = now - timedelta(days=limit_days)
    recent_this = [
        e for e in executions
        if e.get("entry_id") == entry_id
        and e.get("result") == ExecutionResult.ALLOW.value
        and _parse_iso(e.get("executed_at", "")) >= limit_start
    ]
    if len(recent_this) >= 1:
        return ExecutionResult.DENIED.value
    execution = {
        "schema":         "conditional_eag_execution_v1",
        "version":        VERSION,
        "entry_id":       entry_id,
        "trigger_reason": trigger_reason,
        "executed_at":    now.isoformat(),
        "result":         ExecutionResult.ALLOW.value,
    }
    EXECUTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EXECUTIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(execution, ensure_ascii=False) + "\n")
    return ExecutionResult.ALLOW.value


def _parse_iso(s: str) -> datetime:
    """ISO 8601 문자열을 timezone-aware datetime으로 파싱. 실패 시 epoch 반환."""
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return datetime.fromtimestamp(0, tz=timezone.utc)


CEAG_001 = ConditionalEAGEntry(
    id="CEAG-001",
    condition_description="GHS.Calibration_Error_Rate > 0.20",
    action_description="Emergency Calibration Review 착수 알림 생성",
    limit_per_days=30,
    expires_at="2027-06-30T00:00:00+00:00",
    eag_approval_id="EAG-S326-CEAG-001",
)


if __name__ == "__main__":
    import sys
    try:
        result = register(CEAG_001)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ConditionalEAGError as e:
        print("SKIP (already registered):", e)
    sys.exit(0)

#!/usr/bin/env python3
"""
area_15_failure_memory.py v1.0.0
AIF Area 15: Failure Memory System (FailureCategory RC1-RC4)
EAG: EAG-S322-AIF-AREA15-001

준용: area_11_decision_ledger.py 패턴
  - LOG_PATH append-only jsonl
  - record_failure() 필드 검증 -> entry dict -> jsonl append
  - get_*() 구조 일치
  - schema, recorded_at, actor 필드
"""
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S322-AIF-AREA15-001"

ROOT     = Path("/opt/arss/engine/arss-protocol")
LOG_PATH = ROOT / "tools/governance/failure_memory.jsonl"

VALID_COMPONENTS = frozenset({"domi", "jeni", "caddy", "beo", "system", "unknown"})


class FailureCategory(Enum):
    """Failure Category RC1-RC4 -- AIF v1.4 Area 15"""
    RC1 = "RC-1"  # Recoverable
    RC2 = "RC-2"  # Significant
    RC3 = "RC-3"  # Critical
    RC4 = "RC-4"  # Catastrophic

    @property
    def requires_escalation(self) -> bool:
        """RC-3/RC-4: context(에스컬레이션 근거) 필수"""
        return self in (FailureCategory.RC3, FailureCategory.RC4)


class FailureMemoryError(ValueError):
    """Failure Memory 유효성 검증 실패 시 발생."""
    pass


def record_failure(
    category: "FailureCategory",
    component: str,
    error_code: str,
    description: str,
    context: Optional[dict] = None,
    actor: str = "system",
) -> dict:
    """
    실패를 failure_memory.jsonl에 append 기록합니다.

    Args:
        category:    FailureCategory enum (RC1~RC4)
        component:   실패 발생 컴포넌트 (domi/jeni/caddy/beo/system/unknown)
        error_code:  오류 코드 문자열
        description: 실패 상세 설명
        context:     추가 맥락 (RC-3/RC-4 아수)
        actor:       기록 주체

    Returns:
        기록된 entry dict

    Raises:
        FailureMemoryError: 필수 필드 누락 / RC-3/RC-4 context 미제공 / 유효하지 않은 component
    """
    if not description or not str(description).strip():
        raise FailureMemoryError("required field missing: 'description'")
    if not error_code or not str(error_code).strip():
        raise FailureMemoryError("required field missing: 'error_code'")
    comp = str(component).strip().lower()
    if comp not in VALID_COMPONENTS:
        raise FailureMemoryError(
            "Invalid component: '{}'. Must be one of {}".format(
                component, sorted(VALID_COMPONENTS)
            )
        )
    if category.requires_escalation:
        if not context:
            raise FailureMemoryError(
                "context is required for {} (Critical/Catastrophic). "
                "Provide escalation rationale in context dict.".format(category.value)
            )
    entry = {
        "schema":      "failure_memory_v1",
        "version":     VERSION,
        "rc":          category.value,
        "component":   comp,
        "error_code":  error_code.strip(),
        "description": description.strip(),
        "context":     context or {},
        "actor":       actor.strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _load_all_entries() -> list:
    """failure_memory.jsonl 전체 로드."""
    if not LOG_PATH.exists():
        return []
    entries = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def get_failures_by_rc(rc: "FailureCategory") -> list:
    """RC 분류별 실패 목록 반환."""
    rc_value = rc.value
    return [e for e in _load_all_entries() if e.get("rc") == rc_value]


def get_recent_failures(n: int = 10) -> list:
    """최신순 n건 반환."""
    all_entries = _load_all_entries()
    return list(reversed(all_entries[-n:])) if all_entries else []


def get_failure_patterns(window_minutes: int = 60, threshold: int = 3) -> dict:
    """
    패턴 감지:
      consecutive_repeat: 동일 (component, error_code) 연속 threshold회 이상
      frequency_burst: 동일 (component, rc) window_minutes 이내 5회 이상
      cross_component: 3개 이상 component 동시 RC-3 감지 (window 이내)
    """
    from collections import defaultdict
    from datetime import timedelta

    all_entries = _load_all_entries()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)

    consecutive_repeats = []
    if len(all_entries) >= threshold:
        i = 0
        while i < len(all_entries):
            j = i
            key = (all_entries[i].get("component"), all_entries[i].get("error_code"))
            while j < len(all_entries) and (
                all_entries[j].get("component"),
                all_entries[j].get("error_code"),
            ) == key:
                j += 1
            if j - i >= threshold:
                consecutive_repeats.append({
                    "component": key[0],
                    "error_code": key[1],
                    "count": j - i,
                })
            i = j

    freq_counter: dict = defaultdict(int)
    for e in all_entries:
        try:
            rec_at = datetime.fromisoformat(e["recorded_at"])
            if rec_at >= window_start:
                burst_key = (e.get("component"), e.get("rc"))
                freq_counter[burst_key] += 1
        except (KeyError, ValueError):
            pass
    frequency_bursts = [
        {"component": k[0], "rc": k[1], "count": v}
        for k, v in freq_counter.items()
        if v >= 5
    ]

    rc3_components: set = set()
    for e in all_entries:
        if e.get("rc") == "RC-3":
            try:
                rec_at = datetime.fromisoformat(e["recorded_at"])
                if rec_at >= window_start:
                    rc3_components.add(e.get("component"))
            except (KeyError, ValueError):
                pass

    return {
        "window_minutes":     window_minutes,
        "threshold":          threshold,
        "consecutive_repeat": consecutive_repeats,
        "frequency_burst":    frequency_bursts,
        "cross_component":    sorted(rc3_components) if len(rc3_components) >= 3 else [],
        "has_alert":          bool(
            consecutive_repeats or frequency_bursts or len(rc3_components) >= 3
        ),
    }


def get_m04_contribution(window_minutes: int = 1440) -> dict:
    """
    Area 13 M04 연계: agent_cb_zpb_count
    window_minutes 이내 RC-1/RC-2 failure 건수 반환.
    """
    from datetime import timedelta

    all_entries = _load_all_entries()
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)
    cb_zpb_rcs = {"RC-1", "RC-2"}
    count = 0
    for e in all_entries:
        if e.get("rc") in cb_zpb_rcs:
            try:
                rec_at = datetime.fromisoformat(e["recorded_at"])
                if rec_at >= window_start:
                    count += 1
            except (KeyError, ValueError):
                pass
    return {
        "metric":         "M04",
        "metric_name":    "agent_cb_zpb_count",
        "window_minutes": window_minutes,
        "count":          count,
    }


def get_m05_contribution(session: str) -> dict:
    """
    Area 13 M05 연계: session_inc_count
    해당 session에서 RC-2 이상 실패 건수 반환.
    """
    session_str = str(session).strip()
    all_entries = _load_all_entries()
    inc_rcs = {"RC-2", "RC-3", "RC-4"}
    count = 0
    for e in all_entries:
        if e.get("rc") in inc_rcs:
            ctx = e.get("context", {})
            if ctx.get("session") == session_str:
                count += 1
    return {
        "metric":      "M05",
        "metric_name": "session_inc_count",
        "session":     session_str,
        "count":       count,
    }


def get_failure_summary() -> dict:
    """Failure Memory 전체 요약 dict 반환."""
    all_entries = _load_all_entries()
    rc_counts: dict = {}
    component_counts: dict = {}
    for e in all_entries:
        rc = e.get("rc", "UNKNOWN")
        rc_counts[rc] = rc_counts.get(rc, 0) + 1
        comp = e.get("component", "UNKNOWN")
        component_counts[comp] = component_counts.get(comp, 0) + 1
    return {
        "schema":           "failure_memory_summary_v1",
        "version":          VERSION,
        "eag":              EAG_ID,
        "total_count":      len(all_entries),
        "rc_counts":        rc_counts,
        "component_counts": component_counts,
        "recent_5":         list(reversed(all_entries[-5:])) if all_entries else [],
        "log_path":         str(LOG_PATH),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(get_failure_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

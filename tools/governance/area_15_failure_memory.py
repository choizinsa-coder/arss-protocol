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

S450 확장 (EAG-S450-FAILURE-MEMORY-RESOLVED-001, add-only):
  - resolved_entries.jsonl 부속 장부 신설. failure_memory.jsonl은 무수정이다.
  - resolved_entries.jsonl 부재 / 빈 파일은 정상 상태이며 no-op이다.
    본 기능은 배포 시점의 동작이 배포 전과 완전히 동일하므로,
    E-3(배포-시딩 원자성)이 전제하는 "소비될 백로그"가 존재하지 않는다.
    시딩은 배포와 독립된 후속 데이터 작업이다(제니 V5-1).
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
RESOLVED_PATH = ROOT / "tools/governance/resolved_entries.jsonl"  # S450

VALID_COMPONENTS = frozenset({"domi", "jeni", "caddy", "beo", "system", "unknown"})

CONSECUTIVE_REPEAT_WINDOW_MIN = 60  # S371: consecutive_repeat window (independent of frequency_burst window_minutes)

CROSS_SESSION_THRESHOLD_DEFAULT = 3   # S432 channel5: distinct-session repeat threshold
BRIDGE_SOURCE = "promise_failure_bridge"  # S432: M05 guard target


def _entry_session(entry: dict):
    """S432: context.session 우선, 없으면 context.session_ref.
    'S431' / '431' / 431 을 모두 '431'로 정규화한다. 없으면 None."""
    ctx = entry.get("context") or {}
    raw = ctx.get("session")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = ctx.get("session_ref")
    if raw is None:
        return None
    s = str(raw).strip()
    if s and s[0] in ("S", "s"):
        s = s[1:]
    return s or None


RESOLUTION_SCHEMA = "failure_resolution_v1"
RESOLUTION_REQUIRED_FIELDS = (
    "session", "component", "error_code",
    "resolved_at", "resolved_by", "resolution_note",
)


def _normalize_session(raw):
    """S450: 'S449' / '449' / 449 -> '449'. 빈값은 None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s and s[0] in ("S", "s"):
        s = s[1:]
    return s or None


def _resolution_key(entry: dict):
    """S450: failure entry -> resolved 대조 키 (session, component, error_code).

    rc를 키에 넣지 않는다. 실측상 205건 중 175건이 RC-2로 편중되어
    식별력이 없고, 1건 resolve가 무관 항목을 일괄 제외하는 과잉 필터가 된다.
    error_code를 포함해야 cross_session_repeat 그룹핑 축과 일치한다.
    """
    return (
        _entry_session(entry),
        entry.get("component"),
        entry.get("error_code"),
    )


def _load_resolved_keys() -> set:
    """S450: resolved_entries.jsonl -> {(session, component, error_code)} set.

    캐시를 두지 않는다. 파일 규모가 failure_memory와 동급이고,
    aiba_monitor는 5분 주기로 새로 기동되는 별개 프로세스라
    프로세스 내 캐시 재사용 기회가 없다. mtime 캐시는 초 단위
    해상도로 stale 창을 만들 뿐 이득이 없다(제니 V4-2).

    파일 부재 / 빈 파일은 정상 상태이며 빈 set을 반환한다(no-op).
    중복 줄은 set이므로 자동 합치기된다(제니 V4-1).
    """
    keys = set()
    if not RESOLVED_PATH.exists():
        return keys
    with open(RESOLVED_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            k = (
                _normalize_session(rec.get("session")),
                rec.get("component"),
                rec.get("error_code"),
            )
            if all(k):
                keys.add(k)
    return keys


def record_resolution(session, component, error_code,
                      resolved_by, resolution_note) -> dict:
    """S450: 실패 항목의 해결을 resolved_entries.jsonl에 append 기록한다.

    failure_memory.jsonl은 수정하지 않는다(append-only 불변).
    필수 필드가 하나라도 비면 FailureMemoryError.
    """
    sess = _normalize_session(session)
    comp = str(component).strip().lower() if component else ""
    ecode = str(error_code).strip() if error_code else ""
    rby = str(resolved_by).strip() if resolved_by else ""
    note = str(resolution_note).strip() if resolution_note else ""
    if not sess:
        raise FailureMemoryError("required field missing: 'session'")
    if not comp:
        raise FailureMemoryError("required field missing: 'component'")
    if comp not in VALID_COMPONENTS:
        raise FailureMemoryError(
            "Invalid component: '{}'. Must be one of {}".format(
                component, sorted(VALID_COMPONENTS)))
    if not ecode:
        raise FailureMemoryError("required field missing: 'error_code'")
    if not rby:
        raise FailureMemoryError("required field missing: 'resolved_by'")
    if not note:
        raise FailureMemoryError("required field missing: 'resolution_note'")
    rec = {
        "schema":          RESOLUTION_SCHEMA,
        "version":         VERSION,
        "session":         sess,
        "component":       comp,
        "error_code":      ecode,
        "resolved_at":     datetime.now(timezone.utc).isoformat(),
        "resolved_by":     rby,
        "resolution_note": note,
    }
    RESOLVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOLVED_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


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


def get_failure_patterns(window_minutes: int = 60, threshold: int = 3,
                         cross_session_threshold: int = CROSS_SESSION_THRESHOLD_DEFAULT,
                         filter_resolved: bool = False) -> dict:
    """
    패턴 감지:
      consecutive_repeat: 동일 (component, error_code) 연속 threshold회 이상
      frequency_burst: 동일 (component, rc) window_minutes 이내 5회 이상
      cross_component: 3개 이상 component 동시 RC-3 감지 (window 이내)
    """
    from collections import defaultdict
    from datetime import timedelta

    all_entries = _load_all_entries()
    if filter_resolved:
        _resolved = _load_resolved_keys()
        if _resolved:
            all_entries = [e for e in all_entries
                           if _resolution_key(e) not in _resolved]
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=window_minutes)

    consecutive_window_start = now - timedelta(minutes=CONSECUTIVE_REPEAT_WINDOW_MIN)
    cr_entries = []
    for _e in all_entries:
        try:
            _rec_at = datetime.fromisoformat(_e["recorded_at"])
            if _rec_at >= consecutive_window_start:
                cr_entries.append(_e)
        except (KeyError, ValueError):
            pass

    consecutive_repeats = []
    if len(cr_entries) >= threshold:
        i = 0
        while i < len(cr_entries):
            j = i
            key = (cr_entries[i].get("component"), cr_entries[i].get("error_code"))
            while j < len(cr_entries) and (
                cr_entries[j].get("component"),
                cr_entries[j].get("error_code"),
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

    # --- S432 channel5: cross_session_repeat (시간창 무관, 세션 경계 기준) ---
    session_keys: dict = defaultdict(set)
    for e in all_entries:
        comp_v = e.get("component")
        ec_v = e.get("error_code")
        sess_v = _entry_session(e)
        if comp_v and ec_v and sess_v:
            session_keys[(comp_v, ec_v)].add(sess_v)
    cross_session_repeats = []
    for (comp_v, ec_v), sessions_set in session_keys.items():
        if len(sessions_set) >= cross_session_threshold:
            cross_session_repeats.append({
                "component":         comp_v,
                "error_code":        ec_v,
                "distinct_sessions": len(sessions_set),
                "sessions":          sorted(sessions_set),
            })
    cross_session_repeats.sort(key=lambda d: (-d["distinct_sessions"], d["component"], d["error_code"]))

    return {
        "window_minutes":          window_minutes,
        "threshold":               threshold,
        "cross_session_threshold": cross_session_threshold,
        "consecutive_repeat":      consecutive_repeats,
        "frequency_burst":         frequency_bursts,
        "cross_component":         sorted(rc3_components) if len(rc3_components) >= 3 else [],
        "cross_session_repeat":    cross_session_repeats,
        "has_alert":               bool(
            consecutive_repeats or frequency_bursts or len(rc3_components) >= 3
            or cross_session_repeats
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


def get_m05_contribution(session: str,
                         exclude_sources: frozenset = frozenset({BRIDGE_SOURCE})) -> dict:
    """
    Area 13 M05 연계: session_inc_count
    해당 session에서 RC-2 이상 실패 건수 반환.
    """
    session_str = str(session).strip()
    all_entries = _load_all_entries()
    inc_rcs = {"RC-2", "RC-3", "RC-4"}
    count = 0
    want = session_str[1:] if session_str[:1] in ("S", "s") else session_str
    for e in all_entries:
        if e.get("rc") in inc_rcs:
            ctx = e.get("context") or {}
            if exclude_sources and ctx.get("source") in exclude_sources:
                continue
            if _entry_session(e) == want:
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

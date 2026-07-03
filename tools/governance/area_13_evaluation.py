#!/usr/bin/env python3
"""
area_13_evaluation.py v1.0.0
AIF Area 13: Evaluation & Benchmark (지푗10종 SSOT)
EAG: EAG-S321-AIF-AREA11-13-001

지푗10종 (M01~M07):
  M01 -- pytest_passed          (SC_FINAL 자동)
  M02 -- pytest_failed          (SC_FINAL 자동)
  M03 -- wf05_orchestration_rate (수동)
  M04 -- agent_cb_zpb_count     (수동)
  M05 -- session_inc_count      (수동)
  M06 -- dep_completion_rate    (수동)
  M07 -- daily_api_cost         (DOMI_DAILY_COST_STATE.json 자동)

준용: sovereign_authority.py (Area 5) 패턴
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S321-AIF-AREA11-13-001"

ROOT     = Path("/opt/arss/engine/arss-protocol")
LOG_PATH = ROOT / "tools/governance/evaluation_log.jsonl"

# 지푗10종 정의 (M01~M07)
METRICS_7: dict = {
    "M01": {"id": "M01", "name": "pytest_passed",           "unit": "count",   "source": "SC_FINAL.pytest_status"},
    "M02": {"id": "M02", "name": "pytest_failed",           "unit": "count",   "source": "SC_FINAL.pytest_status"},
    "M03": {"id": "M03", "name": "wf05_orchestration_rate", "unit": "percent", "source": "manual"},
    "M04": {"id": "M04", "name": "agent_cb_zpb_count",      "unit": "count",   "source": "manual"},
    "M05": {"id": "M05", "name": "session_inc_count",       "unit": "count",   "source": "manual"},
    "M06": {"id": "M06", "name": "dep_completion_rate",     "unit": "percent", "source": "manual"},
    "M07": {"id": "M07", "name": "daily_api_cost",          "unit": "usd",     "source": "DOMI_DAILY_COST_STATE.json"},
}

_VALID_METRIC_IDS = frozenset(METRICS_7.keys())


class MetricValidationError(ValueError):
    """MetricValidationError -- 유효하지 않은 metric_id 또는 값 형식."""
    pass


def validate_metric_id(metric_id: str) -> bool:
    """
    metric_id가 M01~M07 범위인지 검증합니다.

    Raises:
        MetricValidationError: 유효하지 않은 metric_id
    """
    if not metric_id or not metric_id.strip():
        raise MetricValidationError("metric_id cannot be empty")
    mid = metric_id.strip().upper()
    if mid not in _VALID_METRIC_IDS:
        raise MetricValidationError(
            f"Invalid metric_id: '{metric_id}'. "
            f"Must be one of {sorted(_VALID_METRIC_IDS)}"
        )
    return True


def record_metric(
    metric_id: str,
    value: float,
    context: Optional[dict] = None,
    actor: str = "system",
) -> dict:
    """
    지푗10를 evaluation_log.jsonl에 append 기록합니다.

    Args:
        metric_id: M01~M07
        value:     측정값 (숫자)
        context:   추가 맥락 ({\'session\': \'S321\', \'note\': ...})
        actor:     기록 주체

    Returns:
        기록된 entry dict

    Raises:
        MetricValidationError: 유효하지 않은 metric_id 또는 비숫자 value
    """
    if context is None:
        context = {}
    validate_metric_id(metric_id)
    try:
        float_val = float(value)
    except (TypeError, ValueError):
        raise MetricValidationError(
            f"value must be numeric, got: {type(value).__name__}"
        )
    mid = metric_id.strip().upper()
    entry = {
        "schema":      "evaluation_metric_v1",
        "version":     VERSION,
        "metric_id":   mid,
        "metric_name": METRICS_7[mid]["name"],
        "value":       float_val,
        "unit":        METRICS_7[mid]["unit"],
        "context":     context,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "actor":       actor.strip(),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _load_all_metric_entries() -> list:
    """evaluation_log.jsonl 전체 로드."""
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


def get_metric_history(metric_id: str, n: int = 10) -> list:
    """metric_id 최신 n건 반환 (최신순)."""
    validate_metric_id(metric_id)
    mid = metric_id.strip().upper()
    matched = [e for e in _load_all_metric_entries() if e.get("metric_id") == mid]
    matched.reverse()
    return matched[:n]


def get_all_metrics_latest() -> dict:
    """M01~M07 각 metric_id별 최신 entry 반환."""
    latest: dict = {}
    for e in _load_all_metric_entries():
        mid = e.get("metric_id")
        if mid in _VALID_METRIC_IDS:
            latest[mid] = e
    return {mid: latest.get(mid) for mid in sorted(_VALID_METRIC_IDS)}


def get_current_snapshot() -> dict:
    """
    자동 수집 가능 지푗10 실측:
      M01/M02: SESSION_CONTEXT POINTER -> SC_FINAL -> pytest_status
               FIX: POINTER key = 'current_session' (실측 확인)
      M07: runtime/governance/budget/DOMI_DAILY_COST_STATE.json -> total_usd
           FIX: 실제 키 = 'total_usd' ('daily_cost' 아님)
      M03~M06: 수동 기록 필요 -> None
    """
    result: dict = {
        "M01": None, "M02": None, "M03": None, "M04": None,
        "M05": None, "M06": None, "M07": None,
        "pytest_skipped": None,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
    }

    # M01/M02: POINTER -> SC_FINAL
    pointer_path = ROOT / "SESSION_CONTEXT_POINTER.json"
    try:
        with open(pointer_path, encoding="utf-8") as f:
            pointer = json.load(f)
        # FIX: 실제 POINTER.json 키 = 'current_session' (session_count 아님)
        current_session = pointer.get("current_session") or pointer.get("last_session")
        if current_session is not None:
            sc_path = ROOT / f"SESSION_CONTEXT_S{current_session}_FINAL.json"
            if sc_path.exists():
                with open(sc_path, encoding="utf-8") as f:
                    sc_data = json.load(f)
                pts = sc_data.get("pytest_status", {})
                result["M01"] = pts.get("total_passed")
                result["M02"] = pts.get("total_failed")
                result["pytest_skipped"] = pts.get("total_skipped")
    except (json.JSONDecodeError, IOError, OSError):
        pass

    # M07: DOMI_DAILY_COST_STATE.json
    cost_path = ROOT / "runtime/governance/budget/DOMI_DAILY_COST_STATE.json"
    try:
        if cost_path.exists():
            with open(cost_path, encoding="utf-8") as f:
                cost_data = json.load(f)
            # FIX: 실제 키 = 'total_usd' ('daily_cost'/'total_cost' 아님)
            result["M07"] = cost_data.get("total_usd")
    except (json.JSONDecodeError, IOError, OSError):
        pass

    return result


def get_evaluation_summary() -> dict:
    """Evaluation & Benchmark 전체 요약 반환."""
    all_entries = _load_all_metric_entries()
    latest = get_all_metrics_latest()
    snapshot = get_current_snapshot()
    return {
        "schema":           "evaluation_summary_v1",
        "version":          VERSION,
        "eag":              EAG_ID,
        "total_records":    len(all_entries),
        "log_path":         str(LOG_PATH),
        "metrics_defined":  {mid: METRICS_7[mid]["name"] for mid in sorted(_VALID_METRIC_IDS)},
        "metrics_latest":   latest,
        "current_snapshot": snapshot,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(get_evaluation_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

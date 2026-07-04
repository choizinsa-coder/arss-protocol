#!/usr/bin/env python3
"""calibration.py v1.0.0 -- KG Phase 2 Confidence Calibration (EAG-S333-KG-PHASE2-001)

Section 5.4: Calibration_Error = |Predicted_Confidence - Actual_Success_Rate|
Aggregate over recorded outcomes. Graceful fallback: samples < min_samples -> None.
Goodhart defense (Non-Goals #7): no synthetic score when data insufficient.
"""
from pathlib import Path

VERSION = "1.0.0"
EAG_ID  = "EAG-S333-KG-PHASE2-001"

ROOT = Path("/opt/arss/engine/arss-protocol")
DEFAULT_MIN_SAMPLES = 3


def _load_outcomes_with_confidence() -> list:
    """Filter outcomes where predicted_confidence is present (not None)."""
    try:
        from tools.knowledge_graph import outcome_log
        outcomes = outcome_log.load_all_outcomes()
    except Exception:
        return []
    filtered = []
    for o in outcomes:
        pc = o.get("predicted_confidence")
        if pc is not None:
            try:
                pcf = float(pc)
                if 0.0 <= pcf <= 1.0:
                    filtered.append({"pc": pcf, "outcome": o.get("outcome"), "dc": o.get("dc")})
            except (TypeError, ValueError):
                pass
    return filtered


def compute_calibration_error(min_samples: int = DEFAULT_MIN_SAMPLES):
    """
    Calibration_Error = |avg_predicted - actual_success_rate|.
    samples < min_samples -> None (graceful fallback, Goodhart defense).
    """
    samples = _load_outcomes_with_confidence()
    if len(samples) < min_samples:
        return None
    avg_predicted = sum(s["pc"] for s in samples) / len(samples)
    success = sum(1 for s in samples if s["outcome"] == "success")
    actual_rate = success / len(samples)
    return round(abs(avg_predicted - actual_rate), 4)


def get_calibration_snapshot(min_samples: int = DEFAULT_MIN_SAMPLES) -> dict:
    """Calibration status snapshot."""
    samples = _load_outcomes_with_confidence()
    total = len(samples)
    if total == 0:
        return {
            "calibration_error": None,
            "total_samples":     0,
            "avg_predicted":     None,
            "actual_success_rate": None,
            "sufficient":        False,
        }
    avg_predicted = round(sum(s["pc"] for s in samples) / total, 4)
    success = sum(1 for s in samples if s["outcome"] == "success")
    actual_rate = round(success / total, 4)
    err = round(abs(avg_predicted - actual_rate), 4) if total >= min_samples else None
    return {
        "calibration_error":   err,
        "total_samples":       total,
        "avg_predicted":       avg_predicted,
        "actual_success_rate": actual_rate,
        "sufficient":          total >= min_samples,
    }

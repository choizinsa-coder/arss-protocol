#!/usr/bin/env python3
"""
trs_v2_1.py — Trust Score Calculator (계산 전용, ledger 쓰기 금지)
Evolution Score v2.1
"""

from datetime import datetime, timezone, timedelta

# ── 고정 테이블 (임의 변경 금지) ──────────────────────────────────────
DIFFICULTY_TABLE = [
    (0.0,  20.0, 1.00),
    (20.0, 40.0, 0.70),
    (40.0, 60.0, 0.50),
    (60.0, 80.0, 0.30),
    (80.0, 90.0, 0.15),
    (90.0, 100.0, 0.05),
]

V_MULTIPLIER = {"V1": 1.0, "V2": 1.5, "V3": 2.0}

BASE_DELTA_TABLE = {
    "governance_directive": 0.5,
    "lesson_added":         0.3,
    "task_completed":       0.2,
    "document_approved":    0.15,
    "rpu_issued":           0.1,
}

BASE_DELTA_MAX   = 0.5
V1_SESSION_CAP   = 0.5
SCORE_MAX        = 100.0
REBASE_START     = 10.0
REBASED_FROM     = 329

TRUST_TIERS = [
    (0,  20,  "T0", "Bootstrapped"),
    (20, 40,  "T1", "Structured"),
    (40, 60,  "T2", "Reliable"),
    (60, 80,  "T3", "Verified"),
    (80, 90,  "T4", "Highly Verified"),
    (90, 100, "T5", "Institutional Grade"),
]


# ── 보조 함수 ─────────────────────────────────────────────────────────
def get_difficulty(score: float) -> float:
    for lo, hi, factor in DIFFICULTY_TABLE:
        if lo <= score < hi:
            return factor
    return 0.05  # 100.0 edge


def get_tier(score: float) -> dict:
    for lo, hi, tier, label in TRUST_TIERS:
        if lo <= score < hi:
            return {"tier": tier, "label": label}
    return {"tier": "T5", "label": "Institutional Grade"}


# ── 검증 ─────────────────────────────────────────────────────────────
def validate_verification(level: str, package) -> None:
    if level not in V_MULTIPLIER:
        raise ValueError(f"Unknown verification_level: {level}")
    if level in ("V2", "V3") and package is None:
        raise ValueError("verification_package required for V2/V3")
    if level == "V3":
        if not isinstance(package, dict):
            raise ValueError("V3 requires verification_package dict")
        if package.get("verifier_status") != "PASS":
            raise ValueError("V3 requires verifier_status: PASS")


def rebase_guard(current_score: float, active_sum: float) -> None:
    """Archive contamination 탐지 — 329가 active 계산에 섞이면 차단."""
    if current_score > SCORE_MAX:
        raise ValueError(f"Score cap exceeded: {current_score}")
    # active score = REBASE_START + sum(active records delta)
    expected = round(REBASE_START + active_sum, 6)
    if abs(current_score - expected) > 0.001:
        raise ValueError(
            f"Archive contamination detected: "
            f"current={current_score}, expected={expected}"
        )


# ── 핵심 계산 (쓰기 없음) ────────────────────────────────────────────
def calculate(
    event_type: str,
    verification_level: str,
    package,
    current_score: float,
    session_v1_used: float = 0.0,
) -> dict:
    if event_type not in BASE_DELTA_TABLE:
        raise ValueError(f"Unknown event_type: {event_type}")

    base_delta = BASE_DELTA_TABLE[event_type]
    assert base_delta <= BASE_DELTA_MAX, "base_delta_max 위반"

    validate_verification(verification_level, package)

    difficulty = get_difficulty(current_score)
    multiplier = V_MULTIPLIER[verification_level]

    if verification_level == "V1":
        if session_v1_used + base_delta > V1_SESSION_CAP:
            raise ValueError(
                f"V1 session cap exceeded: used={session_v1_used}, "
                f"delta={base_delta}, cap={V1_SESSION_CAP}"
            )

    delta = round(base_delta * multiplier * difficulty, 6)
    new_score = round(min(SCORE_MAX, current_score + delta), 6)
    tier_info = get_tier(new_score)

    return {
        "base_delta": base_delta,
        "difficulty_factor": difficulty,
        "verification_multiplier": multiplier,
        "delta_score": delta,
        "score_before": current_score,
        "score_after": new_score,
        "trust_tier_after": tier_info["tier"],
        "trust_tier_label": tier_info["label"],
    }


# ── score_velocity 계산 (기록용) ─────────────────────────────────────
def compute_velocity(records: list, days: int = 7) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    recent = [
        r["delta_score"]
        for r in records
        if datetime.fromisoformat(r["timestamp"]) >= cutoff
    ]
    total = round(sum(recent), 6)
    if total > 1.0:
        trend = "RISING"
    elif total > 0:
        trend = "STABLE"
    else:
        trend = "FLAT"
    return {"last_7d_delta": total, "trend": trend}


# ── 단위 테스트 ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== trs_v2_1.py Unit Test ===")

    # Case 1: score=10.0, V1, governance_directive
    r = calculate("governance_directive", "V1", None, 10.0, 0.0)
    assert r["delta_score"] == 0.5, f"Case1 fail: {r}"
    assert r["score_after"] == 10.5
    print(f"[PASS] Case1: {r['score_before']} -> {r['score_after']}")

    # Case 2: score=82.0, V2, task_completed
    pkg = {"verifier_status": "PASS", "reproducibility": "public"}
    r = calculate("task_completed", "V2", pkg, 82.0)
    assert r["delta_score"] == round(0.2 * 1.5 * 0.15, 6)
    print(f"[PASS] Case2: {r['score_before']} -> {r['score_after']}")

    # Case 3: hard cap
    r = calculate("governance_directive", "V3", {"verifier_status": "PASS"}, 99.96)
    assert r["score_after"] == 100.0, f"Case3 fail: {r}"
    print(f"[PASS] Case3: cap enforced -> {r['score_after']}")

    # Case 4: V2 without package
    try:
        calculate("task_completed", "V2", None, 10.0)
        assert False, "Should raise"
    except ValueError as e:
        print(f"[PASS] Case4: {e}")

    # Case 5: V1 session cap
    try:
        calculate("governance_directive", "V1", None, 10.0, session_v1_used=0.4)
        assert False, "Should raise"
    except ValueError as e:
        print(f"[PASS] Case5: {e}")

    # Case 6: rebase_guard
    try:
        rebase_guard(105.0, 0.0)
        assert False
    except ValueError as e:
        print(f"[PASS] Case6: {e}")

    print("=== All tests PASS ===")

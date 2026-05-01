# tools/delta_context/phase2_validator.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# PT-S66-001: Shadow Mode Phase 2 — Trigger Precondition + Comparison Contract

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))

COMPARISON_CONTRACT_PASS = "PASS"
COMPARISON_CONTRACT_FAIL = "FAIL"
COMPARISON_CONTRACT_BLOCKED = "BLOCKED_VALIDATION"

TIMESTAMP_WINDOW_SECONDS = 300  # 5분


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), indent=None, allow_nan=False,
    )


def compute_normalized_payload_hash(payload: dict) -> str:
    raw = _canonical_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


# ── Trigger Precondition 7가지 ────────────────────────────────────────────────

def check_preconditions(ctx: dict) -> dict:
    """
    Phase 2 진입 전 trigger precondition 7가지 점검.

    ctx 필수 키:
        shadow_mode: bool
        index_loaded: bool
        delta_count: int
        session_number: int
        candidate_payload: dict
        ssot_payload: dict
        phase1_complete: bool

    Returns:
        {"passed": True, "failed_conditions": []}
        {"passed": False, "failed_conditions": [str, ...]}
    """
    failed = []

    # PC-1: shadow_mode 활성
    if not ctx.get("shadow_mode", False):
        failed.append("PC-1: shadow_mode is not active")

    # PC-2: index 로드 완료
    if not ctx.get("index_loaded", False):
        failed.append("PC-2: index not loaded")

    # PC-3: delta_count >= 1
    if ctx.get("delta_count", 0) < 1:
        failed.append("PC-3: delta_count < 1")

    # PC-4: session_number 양수
    if not isinstance(ctx.get("session_number"), int) or ctx.get("session_number", 0) <= 0:
        failed.append("PC-4: session_number invalid")

    # PC-5: candidate_payload 존재
    if not ctx.get("candidate_payload"):
        failed.append("PC-5: candidate_payload missing")

    # PC-6: ssot_payload 존재
    if not ctx.get("ssot_payload"):
        failed.append("PC-6: ssot_payload missing")

    # PC-7: Phase 1 완료
    if not ctx.get("phase1_complete", False):
        failed.append("PC-7: phase1 not complete")

    return {"passed": len(failed) == 0, "failed_conditions": failed}


# ── Timestamp Window 검증 ─────────────────────────────────────────────────────

def check_timestamp_window(candidate_ts: str, ssot_ts: str) -> dict:
    """
    두 타임스탬프 차이가 TIMESTAMP_WINDOW_SECONDS 이내인지 확인.
    """
    try:
        t_candidate = datetime.fromisoformat(candidate_ts)
        t_ssot = datetime.fromisoformat(ssot_ts)
        diff = abs((t_candidate - t_ssot).total_seconds())
        within = diff <= TIMESTAMP_WINDOW_SECONDS
        return {"within_window": within, "diff_seconds": diff, "window": TIMESTAMP_WINDOW_SECONDS}
    except Exception as e:
        return {"within_window": False, "diff_seconds": None, "error": str(e)}


# ── Mutation Prohibition 확인 ─────────────────────────────────────────────────

PROHIBITED_KEYS = {"chain", "schema_version", "generated_at"}


def check_mutation_prohibition(candidate_payload: dict, ssot_payload: dict) -> dict:
    """
    prohibited keys가 candidate에서 변경되지 않았는지 확인.
    """
    violations = []
    for key in PROHIBITED_KEYS:
        c_val = candidate_payload.get(key)
        s_val = ssot_payload.get(key)
        if _canonical_dumps(c_val) != _canonical_dumps(s_val):
            violations.append(key)
    return {"clean": len(violations) == 0, "violations": violations}


# ── Comparison Contract ────────────────────────────────────────────────────────

def run_comparison_contract(
    candidate_payload: dict,
    ssot_payload: dict,
    candidate_ts: str,
    ssot_ts: str,
) -> dict:
    """
    Phase 2 핵심: normalized_payload_hash 비교 + timestamp_window + mutation prohibition.

    Returns:
        {
            "contract": "PASS" | "FAIL" | "BLOCKED_VALIDATION",
            "normalized_payload_hash_match": bool,
            "candidate_hash": str,
            "ssot_hash": str,
            "timestamp_window": dict,
            "mutation_prohibition": dict,
            "reasons": [str, ...]
        }
    """
    reasons = []

    # hash 비교
    candidate_hash = compute_normalized_payload_hash(candidate_payload)
    ssot_hash = compute_normalized_payload_hash(ssot_payload)
    hash_match = candidate_hash == ssot_hash

    # timestamp window
    ts_result = check_timestamp_window(candidate_ts, ssot_ts)
    if ts_result.get("error"):
        return {
            "contract": COMPARISON_CONTRACT_BLOCKED,
            "normalized_payload_hash_match": False,
            "candidate_hash": candidate_hash,
            "ssot_hash": ssot_hash,
            "timestamp_window": ts_result,
            "mutation_prohibition": {},
            "reasons": [f"BLOCKED: timestamp parse error — {ts_result['error']}"],
        }

    # mutation prohibition
    mutation_result = check_mutation_prohibition(candidate_payload, ssot_payload)

    if not hash_match:
        reasons.append("normalized_payload_hash mismatch")
    if not ts_result["within_window"]:
        reasons.append(f"timestamp diff {ts_result['diff_seconds']:.1f}s > window {TIMESTAMP_WINDOW_SECONDS}s")
    if not mutation_result["clean"]:
        reasons.append(f"mutation prohibition violated: {mutation_result['violations']}")

    if reasons:
        contract = COMPARISON_CONTRACT_FAIL
    else:
        contract = COMPARISON_CONTRACT_PASS

    return {
        "contract": contract,
        "normalized_payload_hash_match": hash_match,
        "candidate_hash": candidate_hash,
        "ssot_hash": ssot_hash,
        "timestamp_window": ts_result,
        "mutation_prohibition": mutation_result,
        "reasons": reasons,
    }


# ── 통합 진입점 ────────────────────────────────────────────────────────────────

def validate_phase2(ctx: dict) -> dict:
    """
    precondition → comparison_contract 순서 실행.

    Returns:
        {
            "phase2_valid": bool,
            "preconditions": dict,
            "contract": dict | None,
        }
    """
    pre = check_preconditions(ctx)
    if not pre["passed"]:
        return {
            "phase2_valid": False,
            "preconditions": pre,
            "contract": None,
        }

    candidate_payload = ctx["candidate_payload"]
    ssot_payload = ctx["ssot_payload"]
    candidate_ts = candidate_payload.get("generated_at", "")
    ssot_ts = ssot_payload.get("generated_at", "")

    contract = run_comparison_contract(candidate_payload, ssot_payload, candidate_ts, ssot_ts)

    return {
        "phase2_valid": contract["contract"] == COMPARISON_CONTRACT_PASS,
        "preconditions": pre,
        "contract": contract,
    }

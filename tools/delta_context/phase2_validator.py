ACTIVE_VERSION = "1.2.0"
VERSION_STATUS = "active"
# tools/delta_context/phase2_validator.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# PT-S66-001: Shadow Mode Phase 2 — Trigger Precondition + Comparison Contract
# PT-S73-002: Source Collapse Detection Gate (S91 STABILIZATION)

import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

KST = timezone(timedelta(hours=9))

COMPARISON_CONTRACT_PASS = "PASS"
COMPARISON_CONTRACT_FAIL = "FAIL"
COMPARISON_CONTRACT_BLOCKED = "BLOCKED_VALIDATION"

TIMESTAMP_WINDOW_SECONDS = 300  # 5분

# ── Source Collapse 판정 상수 ──────────────────────────────────────────────────

COLLAPSE_VERDICT_FAIL = "FAIL"
COLLAPSE_VERDICT_PASS = "PASS"

COLLAPSE_REASON_PATH_MATCH = "PATH_MATCH"
COLLAPSE_REASON_HASH_MATCH = "HASH_MATCH"
COLLAPSE_REASON_INODE_MATCH = "INODE_MATCH"
COLLAPSE_REASON_INVALID_HASH_FORMAT = "INVALID_HASH_FORMAT"
COLLAPSE_REASON_INVALID_HASH_INTEGRITY = "INVALID_HASH_INTEGRITY"
COLLAPSE_REASON_UNKNOWN = "UNKNOWN"
COLLAPSE_REASON_NONE = "NONE"

SHA256_HEX_LENGTH = 64


def _canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj, sort_keys=True, ensure_ascii=True,
        separators=(",", ":"), indent=None, allow_nan=False,
    )


def compute_normalized_payload_hash(payload: dict) -> str:
    raw = _canonical_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _compute_file_sha256(path: str) -> str:
    """파일 내용 기준 SHA256 full 64자리 반환. 실패 시 예외 전파."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── Source Collapse Detection Gate ────────────────────────────────────────────

def check_source_collapse(ctx: dict) -> dict:
    """
    Source collapse 사전 차단 게이트.
    validate_phase2() 진입 전에 반드시 실행해야 한다.

    판정 입력 (ctx 최상위 키):
        REQUIRED:
            candidate_source_path (str)
            ssot_source_path      (str)
            candidate_source_hash (str)  — SHA256 full 64자리
            ssot_source_hash      (str)  — SHA256 full 64자리
        OPTIONAL:
            candidate_source_inode (int)
            ssot_source_inode      (int)

    반환:
        {
            "collapse": bool,
            "reason":  "PATH_MATCH | HASH_MATCH | INODE_MATCH |
                        INVALID_HASH_FORMAT | INVALID_HASH_INTEGRITY |
                        UNKNOWN | NONE",
            "verdict": "FAIL | PASS"
        }

    PASS 조건:
        collapse == False AND reason == "NONE" AND verdict == "PASS"
    그 외 모든 조합 = FAIL.

    FAIL-CLOSED:
        내부에서 발생하는 모든 Exception은 PASS로 전환될 수 없다.
        → collapse=True, reason="UNKNOWN", verdict="FAIL"
    """
    def _fail(reason: str) -> dict:
        return {"collapse": True, "reason": reason, "verdict": COLLAPSE_VERDICT_FAIL}

    try:
        # ── 필드 존재 확인 ──────────────────────────────────────────────────
        candidate_path = ctx.get("candidate_source_path")
        ssot_path = ctx.get("ssot_source_path")
        candidate_hash_provided = ctx.get("candidate_source_hash")
        ssot_hash_provided = ctx.get("ssot_source_hash")

        if not candidate_path:
            return _fail(COLLAPSE_REASON_UNKNOWN)
        if not ssot_path:
            return _fail(COLLAPSE_REASON_UNKNOWN)
        if not candidate_hash_provided:
            return _fail(COLLAPSE_REASON_UNKNOWN)
        if not ssot_hash_provided:
            return _fail(COLLAPSE_REASON_UNKNOWN)

        # ── PATH_EXISTENCE_CHECK ────────────────────────────────────────────
        if not os.path.exists(candidate_path):
            return _fail(COLLAPSE_REASON_UNKNOWN)
        if not os.path.exists(ssot_path):
            return _fail(COLLAPSE_REASON_UNKNOWN)

        # ── HASH_FORMAT_CHECK — SHA256 full 64자리 강제 ─────────────────────
        if len(candidate_hash_provided) != SHA256_HEX_LENGTH:
            return _fail(COLLAPSE_REASON_INVALID_HASH_FORMAT)
        if len(ssot_hash_provided) != SHA256_HEX_LENGTH:
            return _fail(COLLAPSE_REASON_INVALID_HASH_FORMAT)

        # ── HASH_INTEGRITY_CHECK — 실제 파일 재계산 ─────────────────────────
        try:
            candidate_hash_actual = _compute_file_sha256(candidate_path)
        except Exception:
            return _fail(COLLAPSE_REASON_UNKNOWN)

        try:
            ssot_hash_actual = _compute_file_sha256(ssot_path)
        except Exception:
            return _fail(COLLAPSE_REASON_UNKNOWN)

        if candidate_hash_provided != candidate_hash_actual:
            return _fail(COLLAPSE_REASON_INVALID_HASH_INTEGRITY)
        if ssot_hash_provided != ssot_hash_actual:
            return _fail(COLLAPSE_REASON_INVALID_HASH_INTEGRITY)

        # ── PATH_MATCH — 정규화 경로 비교 ───────────────────────────────────
        if os.path.abspath(candidate_path) == os.path.abspath(ssot_path):
            return _fail(COLLAPSE_REASON_PATH_MATCH)

        # ── HASH_MATCH — 검증 완료된 hash 비교 ──────────────────────────────
        if candidate_hash_actual == ssot_hash_actual:
            return _fail(COLLAPSE_REASON_HASH_MATCH)

        # ── INODE_MATCH (optional) ───────────────────────────────────────────
        candidate_inode = ctx.get("candidate_source_inode")
        ssot_inode = ctx.get("ssot_source_inode")
        if candidate_inode is not None and ssot_inode is not None:
            if candidate_inode == ssot_inode:
                return _fail(COLLAPSE_REASON_INODE_MATCH)

        # ── PASS ─────────────────────────────────────────────────────────────
        return {
            "collapse": False,
            "reason": COLLAPSE_REASON_NONE,
            "verdict": COLLAPSE_VERDICT_PASS,
        }

    except Exception:
        # FAIL-CLOSED: 예외 발생 시 무조건 FAIL
        return _fail(COLLAPSE_REASON_UNKNOWN)


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


# ── 통합 게이트 진입점 ─────────────────────────────────────────────────────────

def run_with_collapse_gate(ctx: dict) -> dict:
    """
    Source collapse gate → Phase 2 validator 순서를 보장하는 통합 진입점.
    shadow_pipeline.py는 validate_phase2() 대신 이 함수를 호출해야 한다.

    실행 순서:
        1. check_source_collapse(ctx)
        2. collapse_result["verdict"] == "FAIL"  →  즉시 collapse_result 반환
                                                     (validate_phase2 호출 금지)
        3. collapse PASS  →  validate_phase2(ctx) 실행 후 결과 반환

    Returns:
        collapse FAIL 시:
            {"collapse": True, "reason": str, "verdict": "FAIL"}
        collapse PASS 시:
            validate_phase2() 반환값 그대로
            {"phase2_valid": bool, "preconditions": dict, "contract": dict|None}
    """
    collapse_result = check_source_collapse(ctx)
    if collapse_result["verdict"] == COLLAPSE_VERDICT_FAIL:
        return collapse_result
    return validate_phase2(ctx)

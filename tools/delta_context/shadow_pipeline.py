# tools/delta_context/shadow_pipeline.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Shadow sidecar 진입점 — SESSION_CONTEXT.json은 여전히 SSOT
# CORE+DELTA는 non-canonical shadow 구조

import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from delta_context.delta_writer import write_delta
from delta_context.index_updater import update_index
from delta_context.session_transaction_manager import create_transaction, mark_incomplete
from delta_context.commit_marker_manager import create_commit, verify_commit_exists
from delta_context.phase2_validator import validate_phase2
from delta_context.divergence_recorder import record_divergence, get_divergence_summary
from delta_context.readiness_tracker import record_session

KST = timezone(timedelta(hours=9))

DELTA_LOG_BASE   = "/opt/arss/engine/arss-protocol/DELTA_LOG"
TX_BASE_PATH     = "/opt/arss/engine/arss-protocol/DELTA_LOG/transactions"
COMMIT_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG/commits"

# diagnostic/log timestamp 전용 — generated_at source로 사용 금지
def _runtime_observed_at() -> str:
    now = datetime.now(KST)
    ms = now.strftime("%f")[:3]
    return now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")


def run_shadow_pipeline(
    session_number: int,
    delta_requests: list[dict],
    generated_at: str,
) -> dict:
    """
    Shadow Mode 세션 종료 파이프라인.

    delta_requests: [
        {
            "domain": str,
            "sequence_number": int,
            "event_type": str,
            "target_key": str,
            "new_value": Any,
            "cross_ref": str,
            "prev_delta_id": str,
            "prev_content_hash": str,
        },
        ...
    ]

    Returns:
        {"success": True, "commit_id": str, "delta_count": int}
        {"success": False, "hard_stop": True, "reason": str, "stage": str}
    """
    # ── PRECONDITION: generated_at 검증 ──────────────────────────────────────
    if not isinstance(generated_at, str) or not generated_at:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "generated_at 누락 또는 빈 값 — SESSION_CONTEXT.generated_at 주입 필수",
            "stage":     "PRECONDITION_GATE",
        }
    try:
        datetime.fromisoformat(generated_at)
    except ValueError:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"generated_at ISO8601 파싱 실패: {generated_at!r}",
            "stage":     "PRECONDITION_GATE",
        }

    if not delta_requests:
        return {
            "success":    False,
            "hard_stop":  True,
            "reason":     "delta_requests 비어 있음 — shadow pipeline 진입 불가",
            "stage":      "PRE_CHECK",
        }

    committed_by = "caddy"
    written_deltas = []

    # ── Stage 0: PRE_DELTA_IDEMPOTENCY_GATE ───────────────────────────────────────
    domains = list({req["domain"] for req in delta_requests})
    delta_exists = any(
        os.path.isdir(os.path.join(DELTA_LOG_BASE, domain, f"S{session_number}"))
        for domain in domains
    )
    if delta_exists:
        tx_path      = os.path.join(TX_BASE_PATH,     f"TX-S{session_number}.json")
        commit_path  = os.path.join(COMMIT_BASE_PATH, f"COMMIT-S{session_number}.json")
        tx_exists     = os.path.exists(tx_path)
        commit_exists = os.path.exists(commit_path)
        if tx_exists and commit_exists:
            return {
                "success": True,
                "reason":  "ALREADY_COMPLETED",
                "stage":   "PRE_DELTA_IDEMPOTENCY_GATE",
            }
        else:
            return {
                "success":   False,
                "hard_stop": True,
                "reason":    "PARTIAL_STATE_DETECTED",
                "stage":     "PRE_DELTA_IDEMPOTENCY_GATE",
            }

    # ── Stage 1: delta_writer (각 domain) ──────────────────────────────────────
    for req in delta_requests:
        write_result = write_delta(
            domain=req["domain"],
            session_number=session_number,
            sequence_number=req["sequence_number"],
            event_type=req["event_type"],
            target_key=req["target_key"],
            new_value=req["new_value"],
            cross_ref=req["cross_ref"],
            prev_delta_id=req["prev_delta_id"],
            prev_content_hash=req["prev_content_hash"],
        )

        if not write_result["success"]:
            return {
                "success":   False,
                "hard_stop": True,
                "reason":    f"delta_writer 실패: {write_result.get('reason')}",
                "stage":     "DELTA_WRITE",
                "failed_req": req,
            }

        delta = write_result["delta"]
        delta_path = write_result["path"]

        # ── Stage 2: index_updater (FIX-1 적용) ──────────────────────────────
        index_result = update_index(delta, delta_path)

        if not index_result["success"]:
            # FIX-1: index_updater 실패 → delta 이미 QUARANTINED
            # TX/COMMIT 생성 진입 금지
            return {
                "success":   False,
                "hard_stop": True,
                "reason":    index_result["reason"],
                "stage":     "INDEX_UPDATE",
                "quarantine": index_result.get("quarantine"),
                "message":   index_result.get("message"),
            }

        written_deltas.append(delta)

    # ── Stage 3: session_transaction_manager TX 생성 ──────────────────────────
    tx_result = create_transaction(
        session_number=session_number,
        committed_by=committed_by,
        included_deltas=written_deltas,
        generated_at=generated_at,
    )

    if not tx_result["success"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"TX 생성 실패: {tx_result.get('reason')}",
            "stage":     "TX_CREATE",
        }

    tx_id = tx_result["tx_id"]
    transaction_hash = tx_result["transaction_hash"]
    # ── Stage 4: COMMIT 생성 ──────────────────────────────────────────
    commit_result = create_commit(
        session_number=session_number,
        tx_id=tx_id,
        transaction_hash=transaction_hash,
        committed_by=committed_by,
        generated_at=generated_at,
    )

    if not commit_result["success"]:
        mark_incomplete(session_number, f"COMMIT 생성 실패: {commit_result.get('reason')}")
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    f"COMMIT 생성 실패: {commit_result.get('reason')}",
            "stage":     "COMMIT_CREATE",
        }

    # ── Stage 5: PRE_COMMIT_GATE (FIX-2 — 생성 완료 후 정합성 검증) ────────
    pre_commit_check = verify_commit_exists(session_number)
    if pre_commit_check.get("hard_stop"):
        mark_incomplete(session_number, pre_commit_check["reason"])
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    pre_commit_check["reason"],
            "stage":     "PRE_COMMIT_GATE",
        }

    # ── Stage 6: COMMIT 존재 최종 확인 (POST_COMMIT_VERIFY) ────────────────
    final_check = verify_commit_exists(session_number)
    if not final_check["exists"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    "COMMIT 생성 후 존재 확인 실패 — HARD STOP",
            "stage":     "POST_COMMIT_VERIFY",
        }

    # ── Stage 7: Phase 2 Validator ──────────────────────────────────────────────
    candidate_payload = {d["target_key"]: d["new_value"] for d in written_deltas}
    candidate_payload["generated_at"] = generated_at

    ssot_payload = {d["target_key"]: d["new_value"] for d in written_deltas}
    ssot_payload["generated_at"] = generated_at

    phase2_ctx = {
        "shadow_mode": True,
        "index_loaded": True,
        "delta_count": len(written_deltas),
        "session_number": session_number,
        "candidate_payload": candidate_payload,
        "ssot_payload": ssot_payload,
        "phase1_complete": True,
    }
    phase2_result = validate_phase2(phase2_ctx)
    contract = phase2_result.get("contract") or {}
    contract_result = contract.get("contract", "PASS")

    divergence_id = None
    phase3_blocked = False
    if contract_result != "PASS":
        div_result = record_divergence(
            session_number=session_number,
            contract=contract,
        )
        divergence_id = div_result.get("divergence_id")
        phase3_blocked = div_result.get("phase3_blocked", False)

    div_summary = get_divergence_summary(session_number)
    record_session(
        session_number=session_number,
        contract_result=contract_result,
        divergence_summary=div_summary,
    )

    return {
        "success":          True,
        "commit_id":        commit_result["commit_id"],
        "tx_id":            tx_id,
        "delta_count":      len(written_deltas),
        "generated_at":     generated_at,
        "phase2_valid":     phase2_result["phase2_valid"],
        "phase2_contract":  contract_result,
        "divergence_id":    divergence_id,
        "phase3_blocked":   phase3_blocked,
    }

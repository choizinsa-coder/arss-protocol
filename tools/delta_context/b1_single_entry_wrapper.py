# tools/delta_context/b1_single_entry_wrapper.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# 비오님 단일 진입점 — shadow pipeline 전체를 1회 호출로 실행

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from delta_context.shadow_pipeline import run_shadow_pipeline
from delta_context.atomic_sync import final_ack


def execute(session_number: int, delta_requests: list[dict], generated_at: str) -> dict:
    """
    비오님 단일 진입점.

    1. shadow_pipeline 실행 (delta write → index → TX → COMMIT)
    2. final_ack (chain + index 동시 검증)

    Returns:
        {"success": True, "commit_id": str, "delta_count": int}
        {"success": False, "hard_stop": True, "reason": str, "stage": str}
    """
    # ── Step 1: shadow pipeline ───────────────────────────────────────────────
    pipeline_result = run_shadow_pipeline(
        session_number=session_number,
        delta_requests=delta_requests,
        generated_at=generated_at,
    )

    if not pipeline_result["success"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    pipeline_result.get("reason", "shadow_pipeline 실패"),
            "stage":     pipeline_result.get("stage", "SHADOW_PIPELINE"),
        }

    written_deltas = []
    for req in delta_requests:
        # final_ack용 delta 재구성 — pipeline 내부 written_deltas 재참조 불가
        # atomic_sync는 INDEX 기반으로 검증하므로 pipeline result 활용
        pass

    # ── Step 2: final_ack ─────────────────────────────────────────────────────
    # shadow_pipeline이 성공했으면 written deltas는 INDEX에 등록된 상태
    # atomic_sync.final_ack은 INDEX 기반 검증 수행
    ack_result = final_ack(
        session_number=session_number,
        written_deltas=[],  # INDEX 기반 검증 — delta 재로드는 atomic_sync 내부 처리
    )

    if not ack_result["success"]:
        return {
            "success":   False,
            "hard_stop": True,
            "reason":    ack_result.get("reason", "final_ack 실패"),
            "stage":     "FINAL_ACK",
        }

    return {
        "success":     True,
        "commit_id":   pipeline_result.get("commit_id"),
        "tx_id":       pipeline_result.get("tx_id"),
        "delta_count": pipeline_result.get("delta_count"),
        "generated_at": pipeline_result.get("generated_at"),
    }

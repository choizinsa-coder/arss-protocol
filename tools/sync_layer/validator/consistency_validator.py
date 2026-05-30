"""
consistency_validator.py
AIBA Sync Layer — 3-way Consistency Validator (P3-T5)
SSOT: Domi Phase 3 Design (S171) / EAG-1 Approved (비오(Joshua))

역할:
  - SESSION_CONTEXT_POINTER / STALE_MANIFEST / FINAL 3-way 일치 검증
  - C1: session_count 일치 (POINTER == MANIFEST == FINAL)
  - C2: context_hash 일치 (POINTER == FINAL)
  - C3: updated_at 일치 (POINTER == MANIFEST)
판정: PASS / FAIL / UNKNOWN (fail-closed)

금지:
  - 수정 / 복구 / 재배포
  - UNKNOWN → PASS 승격
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
POINTER_PATH = VPS_ROOT / "SESSION_CONTEXT_POINTER.json"
MANIFEST_PATH = VPS_ROOT / "SESSION_CONTEXT_STALE_MANIFEST.json"

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"


def validate() -> dict:
    """
    3-way consistency 검증 진입점.
    POINTER → canonical_file 기준으로 FINAL 파일 결정.
    반환: {validator, verdict, mismatches[]}
    CC=5
    """
    pointer = _load_json(POINTER_PATH)
    manifest = _load_json(MANIFEST_PATH)

    if pointer is None:
        return _result(VERDICT_UNKNOWN, [{"error": "POINTER_LOAD_FAILED"}])
    if manifest is None:
        return _result(VERDICT_UNKNOWN, [{"error": "MANIFEST_LOAD_FAILED"}])

    canonical_file = pointer.get("canonical_file", "")
    if not canonical_file:
        return _result(VERDICT_UNKNOWN, [{"error": "POINTER_CANONICAL_FILE_MISSING"}])

    final_path = VPS_ROOT / canonical_file
    final = _load_json(final_path)
    if final is None:
        return _result(VERDICT_UNKNOWN, [{"error": f"FINAL_LOAD_FAILED: {canonical_file}"}])

    mismatches = _check_consistency(pointer, manifest, final)
    verdict = VERDICT_PASS if not mismatches else VERDICT_FAIL
    return _result(verdict, mismatches)


def _check_consistency(pointer: dict, manifest: dict, final: dict) -> list:
    """
    C1/C2/C3 일치 항목 확인. 불일치 목록 반환.
    CC=4
    """
    mismatches = []

    # C1: session_count — POINTER == MANIFEST == FINAL
    p_sc = pointer.get("session_count")
    m_sc = manifest.get("session_count")
    f_sc = final.get("session_count")
    if not (p_sc == m_sc == f_sc):
        mismatches.append({
            "check": "C1",
            "field": "session_count",
            "pointer": p_sc,
            "manifest": m_sc,
            "final": f_sc,
        })

    # C2: context_hash — POINTER == FINAL
    p_ch = pointer.get("context_hash")
    f_ch = final.get("context_hash")
    if p_ch != f_ch:
        mismatches.append({
            "check": "C2",
            "field": "context_hash",
            "pointer": p_ch,
            "final": f_ch,
        })

    # C3: updated_at — POINTER == MANIFEST
    p_ua = pointer.get("updated_at")
    m_ua = manifest.get("updated_at")
    if p_ua != m_ua:
        mismatches.append({
            "check": "C3",
            "field": "updated_at",
            "pointer": p_ua,
            "manifest": m_ua,
        })

    return mismatches


def _load_json(path: Path):
    """JSON 파일 로드. 실패 시 None 반환. CC=2"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("LOAD_FAILED: %s — %s", path.name, exc)
        return None


def _result(verdict: str, mismatches: list) -> dict:
    """결과 딕셔너리 빌드. CC=1"""
    return {
        "validator": "consistency",
        "verdict": verdict,
        "mismatches": mismatches,
    }


def get_validator_status() -> dict:
    """Consistency Validator 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "consistency_validator",
        "layer": "sync_layer/validator",
        "p3_task": "P3-T5",
        "pointer_path": str(POINTER_PATH),
        "manifest_path": str(MANIFEST_PATH),
        "check_items": ["C1:session_count", "C2:context_hash", "C3:updated_at"],
    }

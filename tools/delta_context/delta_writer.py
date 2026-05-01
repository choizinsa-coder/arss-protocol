# tools/delta_context/delta_writer.py
# AIBA DELTA-ONLY CONTEXT ARCHITECTURE v1.2
# Gate chain: G1~G8 → atomic write
# BK-1 Hash Canonicalization 적용

import json
import os
import sys
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any

# 상위 경로 추가 (auto_loader 모듈 접근)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_loader.mutation_gate import evaluate as _mg_evaluate, MutationRequest
from delta_context.event_type_target_validator import validate as dq003_validate

KST = timezone(timedelta(hours=9))
DELTA_BASE_PATH = "/opt/arss/engine/arss-protocol/DELTA_LOG"
GENESIS_MARKER = "GENESIS"


# ── BK-1 Hash 계산 ─────────────────────────────────────────────────────────────

def _canonical_dumps(obj: Any) -> str:
    """BK-1: sort_keys=True, ensure_ascii=True, separators=(',',':'), indent=None"""
    return json.dumps(
        obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        indent=None,
        allow_nan=False,
    )


def compute_content_hash(delta: dict) -> str:
    """content_hash 입력 9개 필드 (BK-1 고정 순서)"""
    payload = {
        "delta_id":        delta["delta_id"],
        "domain":          delta["domain"],
        "session_number":  delta["session_number"],
        "sequence_number": delta["sequence_number"],
        "event_type":      delta["event_type"],
        "target_key":      delta["target_key"],
        "new_value":       delta["new_value"],
        "approved_by":     delta["approved_by"],
        "cross_ref":       delta["cross_ref"],
    }
    raw = _canonical_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_parent_hash(prev_delta_id: str, prev_content_hash: str) -> str:
    """parent_hash: prev_delta_id + prev_content_hash"""
    payload = {
        "prev_content_hash": prev_content_hash,
        "prev_delta_id":     prev_delta_id,
    }
    raw = _canonical_dumps(payload).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _kst_now() -> str:
    """BK-1: ISO 8601, KST(+09:00), 밀리초 3자리 고정"""
    now = datetime.now(KST)
    ms = now.strftime("%f")[:3]
    return now.strftime(f"%Y-%m-%dT%H:%M:%S.{ms}+09:00")


# ── Gate 검증 ──────────────────────────────────────────────────────────────────

def _gate_1_mutation_gate(delta: dict) -> dict:
    """G1: mutation_gate PASS 확인"""
    try:
        req = MutationRequest(target="mutation_gate.evaluate", operation="read", payload=delta)
        result = _mg_evaluate(req)
        if not result.allowed:
            return {"pass": False, "gate": "G1", "reason": result.reason}
        return {"pass": True}
    except Exception as e:
        return {"pass": False, "gate": "G1", "reason": f"evaluate 예외: {e}"}


def _gate_2_dq003(delta: dict) -> dict:
    """G2: event_type × target_key 매핑 확인"""
    result = dq003_validate(delta["event_type"], delta["target_key"], delta["new_value"])
    if not result["valid"]:
        return {"pass": False, "gate": "G2", "reason": result["reason"]}
    return {"pass": True}


def _gate_6_approved_by(delta: dict) -> dict:
    """G6: approved_by = '비오(Joshua)' 단일값 고정"""
    if delta.get("approved_by") != "비오(Joshua)":
        return {
            "pass": False,
            "gate": "G6",
            "reason": f"approved_by must be '비오(Joshua)', got {delta.get('approved_by')!r}",
        }
    return {"pass": True}


def _gate_7_generated_by(delta: dict) -> dict:
    """G7: generated_by = 'caddy' 고정"""
    if delta.get("generated_by") != "caddy":
        return {
            "pass": False,
            "gate": "G7",
            "reason": f"generated_by must be 'caddy', got {delta.get('generated_by')!r}",
        }
    return {"pass": True}


def _gate_8_generated_at(delta: dict) -> dict:
    """G8: generated_at KST 형식 확인 (+09:00 포함)"""
    val = delta.get("generated_at", "")
    if not isinstance(val, str) or "+09:00" not in val:
        return {
            "pass": False,
            "gate": "G8",
            "reason": f"generated_at must be KST ISO 8601 (+09:00), got {val!r}",
        }
    return {"pass": True}


# ── Atomic Write ───────────────────────────────────────────────────────────────

def _atomic_write(path: str, data: dict) -> None:
    """tmp 파일 기록 후 rename — atomic write"""
    tmp_path = path + ".tmp"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(_canonical_dumps(data))
    os.replace(tmp_path, path)


# ── 메인 진입점 ────────────────────────────────────────────────────────────────

def write_delta(
    domain: str,
    session_number: int,
    sequence_number: int,
    event_type: str,
    target_key: str,
    new_value: Any,
    cross_ref: str,
    prev_delta_id: str,
    prev_content_hash: str,
    approved_by: str = "비오(Joshua)",
    generated_by: str = "caddy",
) -> dict:
    """
    G1~G8 gate 통과 후 atomic write 실행.

    Returns:
        {"success": True, "delta_id": str, "path": str}
        {"success": False, "gate": str, "reason": str}
    """
    generated_at = _kst_now()
    delta_id = f"DELTA-S{session_number}-{domain.upper()}-{sequence_number:04d}"

    delta = {
        "delta_id":        delta_id,
        "domain":          domain,
        "session_number":  session_number,
        "sequence_number": sequence_number,
        "event_type":      event_type,
        "target_key":      target_key,
        "new_value":       new_value,
        "approved_by":     approved_by,
        "cross_ref":       cross_ref,
        "generated_by":    generated_by,
        "generated_at":    generated_at,
        "status":          "PENDING",
    }

    # ── Gate Chain (순서 고정) ──
    for gate_fn in [
        _gate_1_mutation_gate,
        _gate_2_dq003,
        _gate_6_approved_by,
        _gate_7_generated_by,
        _gate_8_generated_at,
    ]:
        result = gate_fn(delta)
        if not result["pass"]:
            return {"success": False, **result}

    # G4: content_hash 계산
    delta["content_hash"] = compute_content_hash(delta)

    # G5: parent_hash 계산
    delta["parent_hash"] = compute_parent_hash(prev_delta_id, prev_content_hash)
    delta["prev_delta_id"] = prev_delta_id

    # ── Atomic Write ──
    path = os.path.join(
        DELTA_BASE_PATH,
        domain,
        f"S{session_number}",
        f"{delta_id}.json",
    )

    try:
        _atomic_write(path, delta)
    except Exception as e:
        return {
            "success": False,
            "gate": "ATOMIC_WRITE",
            "reason": f"atomic write 실패: {e}",
        }

    delta["status"] = "WRITTEN"
    return {"success": True, "delta_id": delta_id, "path": path, "delta": delta}

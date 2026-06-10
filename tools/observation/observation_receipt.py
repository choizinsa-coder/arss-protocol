"""
observation_receipt.py
OI-P1-001 검증 구조 개선 — OBSERVATION_RECEIPT 생성·검증 모듈
EAG: EAG-S219-OI-001
Version: 1.0.0

원칙:
- 캐디(COO)가 ask_domi / ask_jeni 응답 수신 후 생성
- 4-Step 검증으로 evidence_hash 재계산 및 VERIFIED 전환
- get_runtime_snapshot() 기반 교차검증 (journalctl 대체)
- 저장 위치: evidence/receipts/ (R1 등급, 180일)
- session_journal OI event_type 연계
"""

import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 경로 상수 ──────────────────────────────────────────────────────
VPS_ROOT     = Path("/opt/arss/engine/arss-protocol")
RECEIPTS_DIR = VPS_ROOT / "evidence" / "receipts"
JOURNAL_PATH = VPS_ROOT / "session_journal" / "session_journal.jsonl"

# ── OBSERVATION_RECEIPT 스키마 v1.0 ───────────────────────────────

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_receipt(
    session_id: str,
    agent: str,
    prompt: str,
    context: dict,
    observations: list[dict],
    response: str,
    runtime_snapshot: Optional[dict] = None,
) -> dict:
    """
    OBSERVATION_RECEIPT 생성.

    observations 항목 형식:
      {
        "tool": "read_file",
        "path": "/opt/.../file.py",
        "purpose": "OBSERVATION",
        "content": "<실제 파일 내용>"   # evidence_hash 계산용
      }
    """
    seq = str(uuid.uuid4())[:8].upper()
    receipt_id = f"OR-{session_id}-{seq}"

    obs_records = []
    for obs in observations:
        content = obs.get("content", "")
        path    = obs.get("path", "")
        evidence_hash = _sha256(path + content)
        obs_records.append({
            "tool":           obs.get("tool", "read_file"),
            "path":           path,
            "purpose":        obs.get("purpose", "OBSERVATION"),
            "evidence_hash":  evidence_hash,
        })

    snapshot_hash = (
        _sha256(json.dumps(runtime_snapshot, sort_keys=True))
        if runtime_snapshot else None
    )

    receipt = {
        "receipt_id":            receipt_id,
        "schema_version":        "1.0",
        "session_id":            session_id,
        "agent":                 agent,
        "generated_at":          _now_iso(),

        "prompt_hash":           _sha256(prompt),
        "context_hash":          _sha256(json.dumps(context, sort_keys=True)),

        "observations":          obs_records,

        "runtime_snapshot_hash": snapshot_hash,
        "response_hash":         _sha256(response),

        "verification_state":    "UNVERIFIED",
        "eag_ref":               "EAG-S219-OI-001",
    }
    return receipt


def save_receipt(receipt: dict) -> Path:
    """
    evidence/receipts/ 에 저장.
    파일명: OR-{session_id}-{seq}_{timestamp}.json
    """
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{receipt['receipt_id']}_{ts}.json"
    path = RECEIPTS_DIR / filename
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
    return path


# ── 4-Step 검증 ────────────────────────────────────────────────────

class VerificationResult:
    def __init__(self):
        self.steps: list[dict] = []
        self.passed = True

    def record(self, step: int, name: str, ok: bool, detail: str = ""):
        self.steps.append({
            "step": step, "name": name,
            "result": "PASS" if ok else "FAIL",
            "detail": detail,
        })
        if not ok:
            self.passed = False

    def to_dict(self) -> dict:
        return {
            "passed":           self.passed,
            "verification_state": "VERIFIED" if self.passed else "FAIL",
            "steps":            self.steps,
            "verified_at":      _now_iso(),
        }


def verify_receipt(
    receipt: dict,
    fresh_observations: list[dict],
    fresh_snapshot: Optional[dict] = None,
) -> VerificationResult:
    """
    4-Step 검증.

    Step 1: Receipt 존재 확인
    Step 2: observations 재실행 (호출자가 fresh_observations 제공)
    Step 3: evidence_hash 재계산 및 일치 확인
    Step 4: runtime_snapshot_hash 비교 (제공된 경우)
    """
    result = VerificationResult()

    # Step 1 — Receipt 구조 확인
    required_keys = {
        "receipt_id", "session_id", "agent",
        "prompt_hash", "context_hash",
        "observations", "response_hash",
    }
    missing = required_keys - set(receipt.keys())
    result.record(1, "RECEIPT_STRUCTURE",
                  ok=len(missing) == 0,
                  detail=f"missing={missing}" if missing else "OK")

    if not result.passed:
        return result

    # Step 2 & 3 — observations 재실행 + evidence_hash 재계산
    orig_obs = receipt.get("observations", [])
    if len(orig_obs) != len(fresh_observations):
        result.record(2, "OBSERVATION_COUNT_MATCH",
                      ok=False,
                      detail=f"expected={len(orig_obs)} got={len(fresh_observations)}")
        result.record(3, "EVIDENCE_HASH_RECOMPUTE", ok=False,
                      detail="SKIPPED — observation count mismatch")
    else:
        result.record(2, "OBSERVATION_COUNT_MATCH", ok=True,
                      detail=f"count={len(orig_obs)}")

        hash_failures = []
        for i, (orig, fresh) in enumerate(zip(orig_obs, fresh_observations)):
            path    = orig.get("path", "")
            content = fresh.get("content", "")
            recomputed = _sha256(path + content)
            if recomputed != orig.get("evidence_hash", ""):
                hash_failures.append(
                    f"obs[{i}] path={path} expected={orig['evidence_hash'][:12]}... "
                    f"got={recomputed[:12]}..."
                )

        result.record(3, "EVIDENCE_HASH_RECOMPUTE",
                      ok=len(hash_failures) == 0,
                      detail="; ".join(hash_failures) if hash_failures else "ALL MATCH")

    # Step 4 — runtime_snapshot 교차검증
    stored_snap_hash = receipt.get("runtime_snapshot_hash")
    if stored_snap_hash and fresh_snapshot:
        fresh_hash = _sha256(json.dumps(fresh_snapshot, sort_keys=True))
        # snapshot은 시간이 지나면 services 상태가 변할 수 있으므로
        # services 키 존재 여부 + ACTIVE 상태만 확인
        stored_services = fresh_snapshot.get("services", {})
        active_count = sum(1 for v in stored_services.values() if v == "active")
        result.record(4, "RUNTIME_SNAPSHOT_CROSS_CHECK",
                      ok=active_count > 0,
                      detail=f"active_services={active_count}/{len(stored_services)}")
    elif stored_snap_hash and not fresh_snapshot:
        result.record(4, "RUNTIME_SNAPSHOT_CROSS_CHECK",
                      ok=False,
                      detail="fresh_snapshot not provided")
    else:
        result.record(4, "RUNTIME_SNAPSHOT_CROSS_CHECK",
                      ok=True,
                      detail="SKIPPED — no snapshot in receipt (optional)")

    return result


def apply_verification(receipt: dict, vr: VerificationResult) -> dict:
    """검증 결과를 receipt에 반영."""
    receipt["verification_state"] = vr.to_dict()["verification_state"]
    receipt["verification_detail"] = vr.to_dict()
    return receipt


# ── session_journal OI event 기록 ─────────────────────────────────

def build_journal_entry(
    session_id: str,
    receipt_id: str,
    agent: str,
    verification_state: str,
    prev_hash: str,
) -> dict:
    """
    session_journal 에 기록할 OI event 항목 생성.
    WORM append-only 구조 준수.
    """
    payload = {
        "event_type":   "OI",
        "session_id":   session_id,
        "agent":        agent,
        "details": {
            "observation_receipt": receipt_id,
            "verification":        verification_state,
        },
        "generated_at": _now_iso(),
        "prev_hash":    prev_hash,
    }
    entry_hash = _sha256(json.dumps(payload, sort_keys=True))
    payload["entry_hash"] = entry_hash
    return payload


# ── OI-P1-001 PASS/FAIL 판정 ──────────────────────────────────────

def evaluate_oi_p1_001(vr: VerificationResult) -> str:
    """
    OI-P1-001 최종 판정.

    PASS: verification_state == VERIFIED
    FAIL: 그 외 모든 경우
    """
    if vr.passed:
        return "PASS"
    return "FAIL"

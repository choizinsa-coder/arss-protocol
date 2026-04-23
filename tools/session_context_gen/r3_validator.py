"""
r3_validator.py — PT-S52-001 R3 Post-Recovery Validation Gate
LOCKED SCOPE: verification-only / no evidence write / no chain mutation
EAG-2 승인 완료 (비오(Joshua))
"""

import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta

import requests

# ── 상수 ──────────────────────────────────────────────────────────────────────
TASK_ID = "PT-S52-001"
STAGE = "R3"
SESSION_CURRENT_URL = "http://159.203.125.1:8000/session/current"
SESSION_CURRENT_TOKEN = "caddy-a7f3k9m2p5x8"

KST = timezone(timedelta(hours=9))

# PEC 잠금값
PEC_HASH_ALGORITHM = "sha256"
PEC_CANONICAL_FORMAT = "json.dumps(sort_keys=True, ensure_ascii=False, separators=(',', ':'))"

REQUIRED_RECEIPT_KEYS = {"candidate_hash", "verifier_summary", "selected_last_known_good"}
REQUIRED_RECEIPT_VERIFIER_KEYS = {"final_chain_hash"}
REQUIRED_RECEIPT_LKG_KEYS = {"session_count"}


# ── 유틸 ──────────────────────────────────────────────────────────────────────
def _sha256_hex(obj: dict) -> str:
    """canonical JSON SHA256 (sort_keys, no spaces, ensure_ascii=False)"""
    serialized = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _now_kst() -> str:
    return datetime.now(KST).isoformat()


def _run_id() -> str:
    return "R3-" + datetime.now(KST).strftime("%Y%m%d-%H%M%S")


# ── § 1. load_and_validate_inputs ─────────────────────────────────────────────
def load_and_validate_inputs(candidate_path: str, receipt_path: str) -> dict:
    """
    파일 존재 확인 → JSON 파싱 → required key 확인
    반환: {"ok": True, "candidate": {...}, "receipt": {...}}
         {"ok": False, "verdict": "SYSTEM_ERROR"|"FAIL", "reason": str}
    """
    for label, path in [("candidate", candidate_path), ("receipt", receipt_path)]:
        if not os.path.exists(path):
            return {"ok": False, "verdict": "SYSTEM_ERROR",
                    "reason": f"Required file missing: {label} @ {path}"}

    try:
        with open(candidate_path, encoding="utf-8") as f:
            candidate = json.load(f)
    except Exception as e:
        return {"ok": False, "verdict": "SYSTEM_ERROR",
                "reason": f"JSON parse failure (candidate): {e}"}

    try:
        with open(receipt_path, encoding="utf-8") as f:
            receipt = json.load(f)
    except Exception as e:
        return {"ok": False, "verdict": "SYSTEM_ERROR",
                "reason": f"JSON parse failure (receipt): {e}"}

    # required key 검사
    missing = REQUIRED_RECEIPT_KEYS - set(receipt.keys())
    if missing:
        return {"ok": False, "verdict": "FAIL",
                "reason": f"Receipt missing required keys: {missing}"}

    missing_v = REQUIRED_RECEIPT_VERIFIER_KEYS - set(receipt.get("verifier_summary", {}).keys())
    if missing_v:
        return {"ok": False, "verdict": "FAIL",
                "reason": f"Receipt.verifier_summary missing keys: {missing_v}"}

    missing_lkg = REQUIRED_RECEIPT_LKG_KEYS - set(receipt.get("selected_last_known_good", {}).keys())
    if missing_lkg:
        return {"ok": False, "verdict": "FAIL",
                "reason": f"Receipt.selected_last_known_good missing keys: {missing_lkg}"}

    return {"ok": True, "candidate": candidate, "receipt": receipt}


# ── § 2. recompute_reference_state ────────────────────────────────────────────
def recompute_reference_state(base_dir: str) -> dict:
    """
    evidence/scoring_ledger.json → actual chain tip
    GET /session/current          → current_session_count
    INTERPRETATION_RULE.json      → allowed_event_types
    """
    # chain tip
    ledger_path = os.path.join(base_dir, "evidence", "scoring_ledger.json")
    try:
        with open(ledger_path, encoding="utf-8") as f:
            ledger = json.load(f)
        entries = ledger if isinstance(ledger, list) else ledger.get("entries", [])
        if not entries:
            return {"ok": False, "verdict": "SYSTEM_ERROR",
                    "reason": "scoring_ledger.json entries empty"}
        actual_chain_tip = entries[-1].get("chain_hash") or entries[-1].get("hash")
        if not actual_chain_tip:
            return {"ok": False, "verdict": "SYSTEM_ERROR",
                    "reason": "chain_hash field not found in ledger last entry"}
    except Exception as e:
        return {"ok": False, "verdict": "SYSTEM_ERROR",
                "reason": f"evidence/scoring_ledger.json read failure: {e}"}

    # session_count — /session/current 단일 고정
    try:
        resp = requests.get(
            SESSION_CURRENT_URL,
            headers={"Authorization": f"Bearer {SESSION_CURRENT_TOKEN}"},
            timeout=10,
        )
        resp.raise_for_status()
        current_session_count = resp.json()["session_count"]
    except Exception as e:
        return {"ok": False, "verdict": "SYSTEM_ERROR",
                "reason": f"/session/current fetch failure: {e}"}

    # INTERPRETATION_RULE.json
    rules_path = os.path.join(base_dir, "INTERPRETATION_RULE.json")
    try:
        with open(rules_path, encoding="utf-8") as f:
            rules = json.load(f)
        allowed_event_types = rules.get("allowed_event_types", [])
    except Exception as e:
        return {"ok": False, "verdict": "SYSTEM_ERROR",
                "reason": f"INTERPRETATION_RULE.json read failure: {e}"}

    return {
        "ok": True,
        "actual_chain_tip": actual_chain_tip,
        "current_session_count": current_session_count,
        "allowed_event_types": allowed_event_types,
    }


# ── § 3. run_r3_gates ─────────────────────────────────────────────────────────
def run_r3_gates(candidate: dict, receipt: dict, reference: dict) -> dict:
    """
    5축 검증 (A~E)
    반환: {verdict, gate_results, failure_reasons}
    """
    failure_reasons = []
    gate_results = {}

    # 축 A — chain_tip equality gate
    expected_chain_tip = receipt["verifier_summary"]["final_chain_hash"]
    actual_chain_tip = reference["actual_chain_tip"]
    if expected_chain_tip == actual_chain_tip:
        gate_results["A_chain_tip"] = "PASS"
    else:
        gate_results["A_chain_tip"] = "FAIL"
        failure_reasons.append(
            f"Chain tip mismatch: expected={expected_chain_tip} actual={actual_chain_tip}"
        )

    # 축 B — session_count validity
    lkg_count = receipt["selected_last_known_good"]["session_count"]
    current_count = reference["current_session_count"]
    if lkg_count <= current_count:
        gate_results["B_session_count"] = "PASS"
    else:
        gate_results["B_session_count"] = "FAIL"
        failure_reasons.append(
            "LKG session_count exceeds actual /session/current session_count"
        )

    # 축 C — candidate hash recompute (64-char 강제)
    candidate_hash_expected = receipt.get("candidate_hash", "")
    # 길이 검사 선행
    if len(candidate_hash_expected) != 64:
        gate_results["C_candidate_hash"] = "FAIL"
        failure_reasons.append(
            f"candidate_hash is not 64-char hex: len={len(candidate_hash_expected)}"
        )
    else:
        candidate_hash_actual = _sha256_hex(candidate)
        if candidate_hash_expected == candidate_hash_actual:
            gate_results["C_candidate_hash"] = "PASS"
        else:
            gate_results["C_candidate_hash"] = "FAIL"
            failure_reasons.append(
                f"Candidate hash mismatch"
            )

    # 축 D — event_type admissibility
    if "event_type" in candidate:
        et = candidate["event_type"]
        allowed = reference["allowed_event_types"]
        if et in allowed:
            gate_results["D_event_type"] = "PASS"
        else:
            gate_results["D_event_type"] = "FAIL"
            failure_reasons.append(
                f"event_type not allowed: '{et}' not in {allowed}"
            )
    else:
        gate_results["D_event_type"] = "SKIP"

    # 축 E — schema compliance
    required_candidate_keys = {"session_count"}
    missing_c = required_candidate_keys - set(candidate.keys())
    if missing_c:
        gate_results["E_schema"] = "FAIL"
        failure_reasons.append(f"Candidate missing required schema keys: {missing_c}")
    else:
        gate_results["E_schema"] = "PASS"

    verdict = "PASS" if not failure_reasons else "FAIL"
    return {
        "verdict": verdict,
        "gate_results": gate_results,
        "failure_reasons": failure_reasons,
    }


# ── § 4. emit_r3_audit_and_quarantine ─────────────────────────────────────────
def emit_r3_audit_and_quarantine(
    verdict: str,
    audit_data: dict,
    candidate_path: str,
    receipt_path: str,
    base_dir: str,
    run_id: str,
) -> dict:
    """
    audit log 생성 + FAIL/SYSTEM_ERROR 시 quarantine bundle 이동
    반환: {audit_log_path, quarantine_applied, quarantine_dir, final_verdict}
    """
    quarantine_applied = False
    quarantine_dir = None
    final_verdict = verdict

    if verdict in ("FAIL", "SYSTEM_ERROR"):
        q_dir = os.path.join(base_dir, "SNAPSHOT_LOG", "quarantine", run_id)
        try:
            os.makedirs(q_dir, exist_ok=True)

            # audit log를 quarantine 번들 내에 생성
            audit_log_path = os.path.join(q_dir, "r3_audit_log.json")
            audit_data["quarantine_applied"] = True
            audit_data["quarantine_dir"] = q_dir
            with open(audit_log_path, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, ensure_ascii=False, indent=2)

            # candidate / receipt 이동 (존재 시만)
            for src, dst_name in [
                (candidate_path, "candidate.json"),
                (receipt_path, "r2_receipt.json"),
            ]:
                if os.path.exists(src):
                    shutil.move(src, os.path.join(q_dir, dst_name))

            quarantine_applied = True
            quarantine_dir = q_dir

        except Exception as e:
            # quarantine move 실패 → SYSTEM_ERROR 승격
            final_verdict = "SYSTEM_ERROR"
            audit_data["quarantine_failure_reason"] = str(e)
            audit_data["quarantine_applied"] = False
            # audit log를 가능한 경로에 기록 시도
            try:
                fallback_path = os.path.join(base_dir, f"r3_audit_fallback_{run_id}.json")
                with open(fallback_path, "w", encoding="utf-8") as f:
                    json.dump(audit_data, f, ensure_ascii=False, indent=2)
                audit_log_path = fallback_path
            except Exception:
                audit_log_path = None
            return {
                "audit_log_path": audit_log_path,
                "quarantine_applied": False,
                "quarantine_dir": None,
                "final_verdict": "SYSTEM_ERROR",
            }

    else:
        # PASS — recovery/receipts/ 에 audit log 저장
        receipts_dir = os.path.join(base_dir, "recovery", "receipts")
        os.makedirs(receipts_dir, exist_ok=True)
        audit_log_path = os.path.join(receipts_dir, f"r3_audit_{run_id}.json")
        audit_data["quarantine_applied"] = False
        audit_data["quarantine_dir"] = None
        with open(audit_log_path, "w", encoding="utf-8") as f:
            json.dump(audit_data, f, ensure_ascii=False, indent=2)

    return {
        "audit_log_path": audit_log_path,
        "quarantine_applied": quarantine_applied,
        "quarantine_dir": quarantine_dir,
        "final_verdict": final_verdict,
    }


# ── 메인 오케스트레이터 ────────────────────────────────────────────────────────
def run_r3_validation(candidate_path: str, receipt_path: str, base_dir: str) -> dict:
    run_id = _run_id()
    verified_at_kst = _now_kst()

    # § 1. 입력 로드
    load_result = load_and_validate_inputs(candidate_path, receipt_path)
    if not load_result["ok"]:
        verdict = load_result["verdict"]
        reason = load_result["reason"]
        audit_data = {
            "task_id": TASK_ID, "stage": STAGE, "run_id": run_id,
            "verdict": verdict, "verified_at_kst": verified_at_kst,
            "candidate_path": candidate_path, "receipt_path": receipt_path,
            "failure_reasons": [reason],
            "pec": {
                "hash_algorithm": PEC_HASH_ALGORITHM,
                "canonical_format": PEC_CANONICAL_FORMAT,
            },
        }
        emit_result = emit_r3_audit_and_quarantine(
            verdict, audit_data, candidate_path, receipt_path, base_dir, run_id
        )
        return {
            "verdict": emit_result["final_verdict"],
            "failure_reasons": [reason],
            "quarantine_applied": emit_result["quarantine_applied"],
            "quarantine_dir": emit_result["quarantine_dir"],
            "audit_log_path": emit_result["audit_log_path"],
        }

    candidate = load_result["candidate"]
    receipt = load_result["receipt"]

    # § 2. 참조 상태 재계산
    ref_result = recompute_reference_state(base_dir)
    if not ref_result["ok"]:
        verdict = ref_result["verdict"]
        reason = ref_result["reason"]
        audit_data = {
            "task_id": TASK_ID, "stage": STAGE, "run_id": run_id,
            "verdict": verdict, "verified_at_kst": verified_at_kst,
            "candidate_path": candidate_path, "receipt_path": receipt_path,
            "failure_reasons": [reason],
            "pec": {
                "hash_algorithm": PEC_HASH_ALGORITHM,
                "canonical_format": PEC_CANONICAL_FORMAT,
            },
        }
        emit_result = emit_r3_audit_and_quarantine(
            verdict, audit_data, candidate_path, receipt_path, base_dir, run_id
        )
        return {
            "verdict": emit_result["final_verdict"],
            "failure_reasons": [reason],
            "quarantine_applied": emit_result["quarantine_applied"],
            "quarantine_dir": emit_result["quarantine_dir"],
            "audit_log_path": emit_result["audit_log_path"],
        }

    # § 3. 5축 검증
    gate_result = run_r3_gates(candidate, receipt, ref_result)
    verdict = gate_result["verdict"]

    # audit data 조립
    audit_data = {
        "task_id": TASK_ID,
        "stage": STAGE,
        "run_id": run_id,
        "verdict": verdict,
        "verified_at_kst": verified_at_kst,
        "candidate_path": candidate_path,
        "receipt_path": receipt_path,
        "actual_chain_tip": ref_result["actual_chain_tip"],
        "expected_chain_tip": receipt["verifier_summary"]["final_chain_hash"],
        "actual_session_count": ref_result["current_session_count"],
        "lkg_session_count": receipt["selected_last_known_good"]["session_count"],
        "candidate_hash_expected": receipt.get("candidate_hash", ""),
        "candidate_hash_actual": _sha256_hex(candidate),
        "event_type_check": gate_result["gate_results"].get("D_event_type", "SKIP"),
        "schema_check": gate_result["gate_results"].get("E_schema", "FAIL"),
        "gate_results": gate_result["gate_results"],
        "failure_reasons": gate_result["failure_reasons"],
        "pec": {
            "hash_algorithm": PEC_HASH_ALGORITHM,
            "canonical_format": PEC_CANONICAL_FORMAT,
        },
    }

    # § 4. audit log 생성 + quarantine
    emit_result = emit_r3_audit_and_quarantine(
        verdict, audit_data, candidate_path, receipt_path, base_dir, run_id
    )

    return {
        "verdict": emit_result["final_verdict"],
        "failure_reasons": gate_result["failure_reasons"],
        "quarantine_applied": emit_result["quarantine_applied"],
        "quarantine_dir": emit_result["quarantine_dir"],
        "audit_log_path": emit_result["audit_log_path"],
        "gate_results": gate_result["gate_results"],
    }


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="R3 Post-Recovery Validation Gate")
    parser.add_argument("--candidate", required=True, help="R2 candidate JSON path")
    parser.add_argument("--receipt", required=True, help="R2 receipt JSON path")
    parser.add_argument(
        "--base-dir",
        default="/opt/arss/engine/arss-protocol",
        help="ARSS protocol base directory",
    )
    args = parser.parse_args()

    result = run_r3_validation(
        candidate_path=args.candidate,
        receipt_path=args.receipt,
        base_dir=args.base_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["verdict"] == "PASS" else 1)

#!/usr/bin/env python3
ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
"""
boot_validator.py — BOOT 파일 무결성 검증기
검증 실패 시: STOP_SIGNAL ON, FULL fallback 강제
"""

import json
import hashlib
import sys
from pathlib import Path

# 실측 기반 ACTIVE 상태 목록
ACTIVE_TASK_STATUSES = [
    "PLANNED",
    "IN_PROGRESS",
    "PENDING",
    "DEFERRED",
    "EAG-1_COMPLETE",
    "EAG-2_PENDING",
]
ACTIVE_TASK_PREFIX = ("EAG-",)
INACTIVE_TASK_STATUSES = {"COMPLETED", "CANCELED_BY_POLICY", "CLOSED"}

GOVERNANCE_EVENT_WHITELIST = [
    "EAG_APPROVED", "EAG_REJECTED",
    "LESSON_ADDED", "LESSON_UPDATED",
    "CHAIN_CREATED", "CHAIN_VERIFIED",
    "RPU_ISSUED",
    "DIS_REGISTERED", "DIS_UPDATED",
    "HARD_STOP_TRIGGERED",
    "RECOVERY_PACKAGE_CREATED", "RECOVERY_VALIDATED",
    "EPS_RECEIPT_CREATED",
    "VERIFICATION_PASS", "VERIFICATION_FAIL",
    "SESSION_CONTEXT_GENERATED",
    "BOOT_CONTEXT_GENERATED"
]

# BOOT 파일에서 반드시 존재해야 하는 키
REQUIRED_BOOT_KEYS = [
    "boot_meta", "chain", "pending_tasks",
    "state_events", "lessons", "canonical_rules",
    "decisions", "archive_refs"
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def is_active_task(task: dict) -> bool:
    status = task.get("status", "")
    if status in ACTIVE_TASK_STATUSES:
        return True
    if any(status.startswith(p) for p in ACTIVE_TASK_PREFIX):
        if status not in INACTIVE_TASK_STATUSES:
            return True
    return False


def stable_event_id(event: dict) -> tuple:
    """안정 식별자 폴백 체인: id → ref → event → sha256(canonical JSON)"""
    if event.get("id"):
        return ("id", event["id"])
    if event.get("ref"):
        return ("ref", event["ref"])
    if event.get("event"):
        return ("event", event["event"])
    canonical = json.dumps(event, ensure_ascii=False, sort_keys=True)
    return ("sha256", hashlib.sha256(canonical.encode()).hexdigest())


def _validate_boot_input_files(full_path: str, boot_path: str):
    """full/boot 파일 존재 검증. 실패 시 fail_signal dict 반환, 통과 시 None."""
    if not Path(full_path).exists():
        return {
            "overall": "FAIL", "stop_signal": True, "fallback": "USE FULL",
            "failures": [f"FULL file not found: {full_path}"], "checks": {},
        }
    if not Path(boot_path).exists():
        return {
            "overall": "FAIL", "stop_signal": True, "fallback": "USE FULL",
            "failures": [f"BOOT file not found: {boot_path}"], "checks": {},
        }
    return None


def _load_full_and_boot_context(full_path: str, boot_path: str) -> dict:
    """full context, boot context 로드."""
    full_p = Path(full_path)
    boot_p = Path(boot_path)
    with open(full_p, encoding="utf-8") as f:
        full = json.load(f)
    with open(boot_p, encoding="utf-8") as f:
        boot = json.load(f)
    return {"full": full, "boot": boot, "full_p": full_p, "boot_p": boot_p}


def _validate_boot_required_keys(boot: dict):
    """BOOT 필수 키 검증. 실패 시 fail_signal dict 반환, 통과 시 None."""
    missing_boot_keys = [k for k in REQUIRED_BOOT_KEYS if k not in boot]
    if missing_boot_keys:
        return {
            "overall": "FAIL", "stop_signal": True, "fallback": "USE FULL",
            "failures": [f"BOOT missing required keys: {missing_boot_keys}"],
            "checks": {},
        }
    return None


def _check_active_task_count(
    full: dict, boot: dict, failures: list, results: dict
) -> None:
    """CHECK-1: ACTIVE 태스크 수 일치."""
    full_active = [t for t in full.get("pending_tasks", []) if is_active_task(t)]
    boot_active = [t for t in boot.get("pending_tasks", []) if is_active_task(t)]
    c1 = len(full_active) == len(boot_active)
    results["CHECK-1_active_tasks"] = {
        "pass": c1,
        "full_count": len(full_active),
        "boot_count": len(boot_active),
    }
    if not c1:
        full_ids = {t.get("id") for t in full_active}
        boot_ids = {t.get("id") for t in boot_active}
        missing = full_ids - boot_ids
        failures.append(
            f"CHECK-1 FAIL: ACTIVE task mismatch "
            f"(FULL={len(full_active)}, BOOT={len(boot_active)}, missing={missing})"
        )


def _check_chain_tip_match(
    full: dict, boot: dict, failures: list, results: dict
) -> None:
    """CHECK-2: chain.tip 일치."""
    full_tip = full.get("chain", {}).get("tip")
    boot_tip = boot.get("chain", {}).get("tip")
    if full_tip is None:
        failures.append("CHECK-2 FAIL: FULL chain.tip key missing — FAIL-CLOSED")
        c2 = False
    elif boot_tip is None:
        failures.append("CHECK-2 FAIL: BOOT chain.tip key missing — FAIL-CLOSED")
        c2 = False
    else:
        c2 = full_tip == boot_tip
        if not c2:
            failures.append(
                f"CHECK-2 FAIL: chain.tip mismatch "
                f"(FULL={full_tip[:16]}..., BOOT={boot_tip[:16]}...)"
            )
    results["CHECK-2_chain_tip"] = {"pass": c2, "full": full_tip, "boot": boot_tip}


def _check_unresolved_events_included(
    full: dict, boot: dict, failures: list, results: dict
) -> None:
    """CHECK-3: unresolved 거버넌스 이벤트 전량 포함."""
    full_unresolved = [
        e for e in full.get("state_events", [])
        if e.get("event_type", e.get("type", "")) in GOVERNANCE_EVENT_WHITELIST
        and e.get("status") in ("unresolved", "active", "blocking")
    ]
    boot_event_ids = {stable_event_id(e) for e in boot.get("state_events", [])}
    missing_events = [
        e for e in full_unresolved
        if stable_event_id(e) not in boot_event_ids
    ]
    c3 = len(missing_events) == 0
    results["CHECK-3_unresolved_events"] = {
        "pass": c3,
        "full_unresolved_count": len(full_unresolved),
        "missing_count": len(missing_events),
        "missing_ids": [stable_event_id(e) for e in missing_events],
    }
    if not c3:
        failures.append(
            f"CHECK-3 FAIL: {len(missing_events)} unresolved governance events missing"
        )


def _check_archive_refs_sha256(
    full_p: Path, boot: dict, failures: list, results: dict
) -> None:
    """CHECK-4: archive_refs SHA256 검증."""
    full_sha256_actual = sha256_file(full_p)
    stored_sha256 = boot.get("archive_refs", {}).get("full_context", {}).get("sha256", "")
    c4 = bool(stored_sha256) and (full_sha256_actual == stored_sha256)
    results["CHECK-4_archive_sha256"] = {
        "pass": c4,
        "actual": full_sha256_actual,
        "stored": stored_sha256,
    }
    if not c4:
        failures.append("CHECK-4 FAIL: archive_refs SHA256 mismatch or missing")


def _check_boot_is_not_ssot(
    boot: dict, failures: list, results: dict
) -> None:
    """CHECK-5: boot_is_ssot == False."""
    boot_is_ssot = boot.get("boot_meta", {}).get("boot_is_ssot", True)
    c5 = boot_is_ssot is False
    results["CHECK-5_boot_not_ssot"] = {"pass": c5, "boot_is_ssot": boot_is_ssot}
    if not c5:
        failures.append("CHECK-5 HARD STOP: boot_is_ssot is not False")


def _build_boot_validation_report(results: dict, failures: list) -> dict:
    """최종 report 조립."""
    overall_pass = len(failures) == 0
    return {
        "overall": "PASS" if overall_pass else "FAIL",
        "stop_signal": not overall_pass,
        "fallback": "USE FULL" if not overall_pass else "BOOT ACCEPTED",
        "checks": results,
        "failures": failures,
    }


def _mutate_boot_meta_on_pass(boot: dict, boot_p: Path) -> None:
    """PASS 시 boot_meta state mutation 및 저장."""
    boot["boot_meta"]["validator_result"] = "PASS"
    with open(boot_p, "w", encoding="utf-8") as f:
        json.dump(boot, f, ensure_ascii=False, indent=2)


def validate_and_mutate_state(full_path: str, boot_path: str) -> dict:
    fail_signal = _validate_boot_input_files(full_path, boot_path)
    if fail_signal is not None:
        return fail_signal

    ctx = _load_full_and_boot_context(full_path, boot_path)
    full, boot = ctx["full"], ctx["boot"]
    full_p, boot_p = ctx["full_p"], ctx["boot_p"]

    fail_signal = _validate_boot_required_keys(boot)
    if fail_signal is not None:
        return fail_signal

    failures: list = []
    results: dict = {}
    _check_active_task_count(full, boot, failures, results)
    _check_chain_tip_match(full, boot, failures, results)
    _check_unresolved_events_included(full, boot, failures, results)
    _check_archive_refs_sha256(full_p, boot, failures, results)
    _check_boot_is_not_ssot(boot, failures, results)

    report = _build_boot_validation_report(results, failures)

    if report["overall"] == "PASS":
        _mutate_boot_meta_on_pass(boot, boot_p)

    return report


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python boot_validator.py <full_path> <boot_path>")
        sys.exit(1)
    report = validate_and_mutate_state(sys.argv[1], sys.argv[2])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["stop_signal"]:
        print("\n[STOP_SIGNAL ON] BOOT 파일 거부. FULL 사용 강제. 비오님 확인 필요.")
        sys.exit(1)
    print("\n[BOOT ACCEPTED] SESSION_BOOT 파일 유효.")
    sys.exit(0)

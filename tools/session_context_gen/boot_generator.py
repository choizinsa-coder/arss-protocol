#!/usr/bin/env python3
ACTIVE_VERSION = "1.0.1"
VERSION_STATUS = "active"
"""
boot_generator.py — SESSION_BOOT_S{n}.json 생성기
BOOT는 SSOT가 아님. FULL의 검증된 파생본.
충돌 시 FULL 우선, BOOT 무효.
"""

import json
import hashlib
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
]  # 17개 고정

ACTIVE_TASK_STATUSES = [
    "PLANNED", "IN_PROGRESS", "PENDING", "DEFERRED",
    "EAG-1_COMPLETE", "EAG-2_PENDING",
]
ACTIVE_TASK_PREFIX = ("EAG-",)
INACTIVE_TASK_STATUSES = {"COMPLETED", "CANCELED_BY_POLICY", "CLOSED"}

RECENT_GOVERNANCE_SESSION_WINDOW = 10
RECENT_OPS_SESSION_WINDOW = 3
RECENT_DECISIONS_COUNT = 20
KST = timezone(timedelta(hours=9))

REQUIRED_FULL_KEYS = [
    "chain", "pending_tasks", "state_events",
    "lessons", "canonical_rules", "decisions"
]

# canonical_rules 중 BOOT에서 완전 제거 대상
CANONICAL_RULES_REMOVE_KEYS = {
    "eps_v1_3_d",       # v1.4로 대체됨
    "boot_templates",   # BOOT 파일 자체가 대체
    "scoring_ledger",   # DIS-049 비활성, evolution_score로 축약
}

# canonical_rules 항목 내 제거할 필드
CANONICAL_ITEM_REMOVE_FIELDS = {"note", "history", "changelog", "detail"}


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


def get_recent_sessions(events: list, n: int) -> set:
    sessions = sorted(
        {e.get("session") for e in events if e.get("session") is not None},
        reverse=True
    )
    return set(sessions[:n])


def filter_state_events(events: list) -> list:
    gov_sessions = get_recent_sessions(events, RECENT_GOVERNANCE_SESSION_WINDOW)
    ops_sessions = get_recent_sessions(events, RECENT_OPS_SESSION_WINDOW)
    result = []
    for e in events:
        etype = e.get("event_type", e.get("type", ""))
        session = e.get("session")
        is_gov = etype in GOVERNANCE_EVENT_WHITELIST
        is_unresolved = e.get("status") in ("unresolved", "active", "blocking")
        if is_gov and (session in gov_sessions or is_unresolved):
            result.append(e)
        elif not is_gov and session in ops_sessions:
            result.append(e)
    return result


def minify_canonical_rules(rules: dict) -> dict:
    result = {}
    for k, v in rules.items():
        if k in CANONICAL_RULES_REMOVE_KEYS:
            continue  # 완전 제거
        if isinstance(v, dict):
            result[k] = {
                ik: iv for ik, iv in v.items()
                if ik not in CANONICAL_ITEM_REMOVE_FIELDS
            }
        else:
            result[k] = v
    return result


def minify_decisions(decisions: list) -> list:
    """next_session_ref 필드 제거"""
    result = []
    for d in decisions:
        item = {k: v for k, v in d.items() if k != "next_session_ref"}
        result.append(item)
    return result


def minify_session_reentry(reentry) -> dict:
    """session_reentry: 핵심 체크리스트 항목만 유지"""
    if not isinstance(reentry, dict):
        return reentry
    KEEP_KEYS = {"checklist", "ssot_ref", "priority_order", "chain_verify"}
    return {k: v for k, v in reentry.items() if k in KEEP_KEYS}


def minify_wf_structure(wf) -> dict:
    """wf_structure_confirmed: 핵심 2필드만 유지"""
    if not isinstance(wf, dict):
        return wf
    KEEP_KEYS = {"confirmed", "commit", "status", "version"}
    return {k: v for k, v in wf.items() if k in KEEP_KEYS}


def generate(full_path: str, boot_path: str, runtime_pair_hash: str = "") -> dict:
    full_p = Path(full_path)
    boot_p = Path(boot_path)

    if not full_p.exists():
        raise FileNotFoundError(f"FULL file not found: {full_path}")

    full_sha256 = sha256_file(full_p)

    with open(full_p, encoding="utf-8") as f:
        full = json.load(f)

    # 필수 키 사전 검증 (fail-closed)
    missing_keys = [k for k in REQUIRED_FULL_KEYS if k not in full]
    if missing_keys:
        raise KeyError(f"[FAIL-CLOSED] FULL missing required keys: {missing_keys}")

    boot = {}

    # boot_meta
    boot["boot_meta"] = {
        "boot_is_ssot": False,
        "ssot_ref": full_p.name,
        "conflict_resolution": "FULL wins. BOOT invalid if conflict.",
        "generated_from_sha256": full_sha256,
        "boot_generated_at": datetime.now(KST).isoformat(),
        "validator_result": "PENDING",
        "runtime_pair_hash": runtime_pair_hash,
        "runtime_pair_rule": "BOOT_REFERENCES_RUNTIME_ONLY",
    }

    # 기본 메타
    for key in ["system_name", "system_version", "schema_version",
                "architecture", "session_count", "generated_at"]:
        if key in full:
            boot[key] = full[key]

    # chain 전량
    boot["chain"] = full["chain"]

    # canonical_rules (minified — 3개 키 제거 + 장문 필드 제거 + whitelist 추가)
    rules = minify_canonical_rules(full.get("canonical_rules", {}))
    rules["governance_event_whitelist"] = GOVERNANCE_EVENT_WHITELIST
    boot["canonical_rules"] = rules

    # lessons 전량
    boot["lessons"] = full.get("lessons", [])

    # pending_tasks: ACTIVE만 (비활성은 archive_refs로 대체)
    tasks = full.get("pending_tasks", [])
    active_tasks = [t for t in tasks if is_active_task(t)]
    inactive_count = len([t for t in tasks if not is_active_task(t)])
    boot["pending_tasks"] = active_tasks

    # state_events 필터링
    boot["state_events"] = filter_state_events(full.get("state_events", []))

    # decisions: 최근 20개 + next_session_ref 필드 제거
    decisions = full.get("decisions", [])[-RECENT_DECISIONS_COUNT:]
    boot["decisions"] = minify_decisions(decisions)

    # decision_refs 전량
    boot["decision_refs"] = full.get("decision_refs", [])

    # evolution_score 축약
    boot["evolution_score"] = {"status": "DISABLED", "ref": "DIS-049"}

    # 기타 운용 메타 (일부 압축)
    for key in ["agent_focus", "enforcement_rules", "lesson_review_policy",
                "session_delta", "sync_meta", "session_open_rules",
                "session_close_rules", "scp_standard_path",
                "automation_roadmap"]:
        if key in full:
            boot[key] = full[key]

    # session_reentry: 핵심만 유지
    if "session_reentry" in full:
        boot["session_reentry"] = minify_session_reentry(full["session_reentry"])

    # wf_structure_confirmed: 핵심 2필드만
    if "wf_structure_confirmed" in full:
        boot["wf_structure_confirmed"] = minify_wf_structure(full["wf_structure_confirmed"])

    # archive_refs (비활성 태스크 카운트 포함)
    boot["archive_refs"] = {
        "full_context": {
            "archive_file": full_p.name,
            "sha256": full_sha256,
            "record_count": {
                "state_events": len(full.get("state_events", [])),
                "pending_tasks_total": len(tasks),
                "pending_tasks_inactive": inactive_count,
                "decisions": len(full.get("decisions", []))
            },
            "last_updated_at": full.get("generated_at", "")
        }
    }

    with open(boot_p, "w", encoding="utf-8") as f:
        json.dump(boot, f, ensure_ascii=False, indent=2)

    return boot


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python boot_generator.py <full_path> <boot_path>")
        sys.exit(1)
    try:
        generate(sys.argv[1], sys.argv[2])
        print(f"[boot_generator] DONE → {sys.argv[2]}")
    except Exception as e:
        print(f"[boot_generator] FAIL: {e}")
        sys.exit(1)

"""
PT-S58-001 — task_migrator.py
TASK STRUCTURE REFACTOR v1.0
Migrates pending_tasks → 4-bucket structure.
Dry-run mode by default. Pass --apply to write.
"""

import json
import copy
import sys
from pathlib import Path

SSOT_PATH = Path(
    "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"
)

STATUS_MAP = {
    "PLANNED": "DESIGN_PENDING",
    "DEFERRED": "HOLD",
    "CLOSED": "ARCHIVED",
    "CANCELED_BY_POLICY": "CANCELED",
    "CANCELED": "CANCELED",
    "SUPERSEDED": "SUPERSEDED",
    "EAG_PENDING": "EAG_1_PENDING",
    "EAG-1_COMPLETE": "EAG_2_PENDING",
    "EAG-2_COMPLETE": "EAG_3_PENDING",
    "EAG-3_COMPLETE": "COMPLETED",
    "EAG-1_PENDING": "EAG_1_PENDING",
    "EAG-2_PENDING": "EAG_2_PENDING",
    "EAG-3_PENDING": "EAG_3_PENDING",
    "EAG_COMPLETE": "COMPLETED",
    "IN_PROGRESS": "IN_PROGRESS",
    "BLOCKED": "BLOCKED",
    "COMPLETED": "COMPLETED",
    "DESIGN_PENDING": "DESIGN_PENDING",
    "EAG_1_PENDING": "EAG_1_PENDING",
    "EAG_2_PENDING": "EAG_2_PENDING",
    "EAG_3_PENDING": "EAG_3_PENDING",
    "READY_FOR_DEPLOY": "READY_FOR_DEPLOY",
    "HOLD": "HOLD",
    "ARCHIVED": "ARCHIVED",
}

ACTIVE_STATUSES = {
    "DESIGN_PENDING", "EAG_1_PENDING", "EAG_2_PENDING",
    "EAG_3_PENDING", "READY_FOR_DEPLOY", "IN_PROGRESS"
}
BLOCKED_STATUSES = {"BLOCKED"}
HOLD_STATUSES = {"HOLD"}
ARCHIVED_STATUSES = {"COMPLETED", "CANCELED", "SUPERSEDED", "ARCHIVED"}


def normalize_status(raw: str) -> str:
    return STATUS_MAP.get(raw, raw)


def assign_id(task: dict, idx: int, used_ids: set) -> str:
    if task.get("id"):
        return task["id"]
    session = task.get("created_session")
    if session:
        candidate = f"PT-S{session}-AUTO-{idx:03d}"
    else:
        candidate = f"PT-LEGACY-AUTO-{idx:03d}"
    suffix = idx
    while candidate in used_ids:
        suffix += 1
        if session:
            candidate = f"PT-S{session}-AUTO-{suffix:03d}"
        else:
            candidate = f"PT-LEGACY-AUTO-{suffix:03d}"
    return candidate


def migrate(data: dict) -> dict:
    result = copy.deepcopy(data)
    tasks = result.get("pending_tasks", [])

    active, blocked, hold, archived = [], [], [], []
    used_ids = set()
    legacy_seq = 1

    for idx, task in enumerate(tasks, start=1):
        t = copy.deepcopy(task)

        raw_status = t.get("status", "")
        t["status"] = normalize_status(raw_status)

        if not t.get("id"):
            session = t.get("created_session")
            if session:
                candidate = f"PT-S{session}-AUTO-{idx:03d}"
            else:
                candidate = f"PT-LEGACY-AUTO-{legacy_seq:03d}"
                legacy_seq += 1
            while candidate in used_ids:
                legacy_seq += 1
                candidate = f"PT-LEGACY-AUTO-{legacy_seq:03d}"
            t["id"] = candidate
        used_ids.add(t["id"])

        status = t["status"]
        if status in BLOCKED_STATUSES:
            if "block_reason" not in t:
                t["block_reason"] = "UNKNOWN — requires manual review"
            blocked.append(t)
        elif status in HOLD_STATUSES:
            t["executable"] = False
            hold.append(t)
        elif status in ARCHIVED_STATUSES:
            archived.append(t)
        else:
            active.append(t)

    result["active_tasks"] = active
    result["blocked_tasks"] = blocked
    result["hold_tasks"] = hold
    result["archived_tasks"] = archived
    result["pending_tasks_legacy_shim"] = {
        "is_canonical": False,
        "note": "read-only projection of active+blocked+hold tasks",
        "source": ["active_tasks", "blocked_tasks", "hold_tasks"],
        "mutation_forbidden": True
    }

    return result


def print_summary(original: dict, migrated: dict):
    orig_count = len(original.get("pending_tasks", []))
    print(f"pending_tasks (original): {orig_count}")
    print(f"active_tasks:   {len(migrated['active_tasks'])}")
    print(f"blocked_tasks:  {len(migrated['blocked_tasks'])}")
    print(f"hold_tasks:     {len(migrated['hold_tasks'])}")
    print(f"archived_tasks: {len(migrated['archived_tasks'])}")
    total = (len(migrated['active_tasks']) +
             len(migrated['blocked_tasks']) +
             len(migrated['hold_tasks']) +
             len(migrated['archived_tasks']))
    print(f"total migrated: {total}")
    print(f"match: {'OK' if total == orig_count else 'MISMATCH'}")


if __name__ == "__main__":
    apply_mode = "--apply" in sys.argv

    with open(SSOT_PATH) as f:
        original = json.load(f)

    migrated = migrate(original)

    print("=== DRY-RUN SUMMARY ===" if not apply_mode
          else "=== APPLY MODE ===")
    print_summary(original, migrated)

    if apply_mode:
        with open(SSOT_PATH, "w") as f:
            json.dump(migrated, f, ensure_ascii=False,
                      indent=2, sort_keys=False)
        print("SESSION_CONTEXT.json updated.")
    else:
        print("Dry-run only. Pass --apply to write.")

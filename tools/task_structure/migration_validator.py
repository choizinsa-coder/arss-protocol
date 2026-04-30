"""
PT-S58-001 — migration_validator.py
TASK STRUCTURE REFACTOR v1.0
Fail-closed validator for 4-bucket task structure.
"""

import json

STATUS_STANDARD = {
    "DESIGN_PENDING", "EAG_1_PENDING", "EAG_2_PENDING", "EAG_3_PENDING",
    "READY_FOR_DEPLOY", "IN_PROGRESS", "BLOCKED", "HOLD",
    "COMPLETED", "CANCELED", "SUPERSEDED", "ARCHIVED"
}

ACTIVE_STATUSES = {
    "DESIGN_PENDING", "EAG_1_PENDING", "EAG_2_PENDING", "EAG_3_PENDING",
    "READY_FOR_DEPLOY", "IN_PROGRESS"
}

ARCHIVED_STATUSES = {"COMPLETED", "CANCELED", "SUPERSEDED", "ARCHIVED"}


def validate(data: dict) -> dict:
    errors = []

    active = data.get("active_tasks", [])
    blocked = data.get("blocked_tasks", [])
    hold = data.get("hold_tasks", [])
    archived = data.get("archived_tasks", [])
    pending_shim = data.get("pending_tasks_legacy_shim", None)

    all_tasks = active + blocked + hold + archived

    # Condition 1 — STATUS_STANDARD
    for t in all_tasks:
        if t.get("status") not in STATUS_STANDARD:
            errors.append(f"INVALID_STATUS: id={t.get('id')} "
                          f"status={t.get('status')}")

    # Condition 2 — id missing
    for t in all_tasks:
        if not t.get("id"):
            errors.append(f"ID_MISSING: task={t.get('task', 'UNKNOWN')[:50]}")

    # Condition 3 — id duplicate
    ids = [t.get("id") for t in all_tasks if t.get("id")]
    if len(ids) != len(set(ids)):
        dupes = [i for i in ids if ids.count(i) > 1]
        errors.append(f"ID_DUPLICATE: {list(set(dupes))}")

    # Condition 4 — active_tasks must not contain archived statuses
    for t in active:
        if t.get("status") in ARCHIVED_STATUSES:
            errors.append(f"ACTIVE_CONTAINS_ARCHIVED: id={t.get('id')} "
                          f"status={t.get('status')}")

    # Condition 5 — archived_tasks must not contain active statuses
    for t in archived:
        if t.get("status") in ACTIVE_STATUSES:
            errors.append(f"ARCHIVED_CONTAINS_ACTIVE: id={t.get('id')} "
                          f"status={t.get('status')}")

    # Condition 6 — hold_tasks.executable must be false
    for t in hold:
        if "executable" not in t:
            errors.append(f"HOLD_EXECUTABLE_MISSING: id={t.get('id')}")
        elif not isinstance(t["executable"], bool):
            errors.append(f"HOLD_EXECUTABLE_NOT_BOOL: id={t.get('id')}")
        elif t["executable"] is not False:
            errors.append(f"HOLD_EXECUTABLE_NOT_FALSE: id={t.get('id')}")

    # Condition 7 — blocked_tasks.block_reason required
    for t in blocked:
        if "block_reason" not in t:
            errors.append(f"BLOCKED_REASON_MISSING: id={t.get('id')}")
        elif not isinstance(t["block_reason"], str):
            errors.append(f"BLOCKED_REASON_NOT_STRING: id={t.get('id')}")
        elif t["block_reason"].strip() == "":
            errors.append(f"BLOCKED_REASON_EMPTY: id={t.get('id')}")

    # Condition 8 — pending_tasks_legacy_shim must not be canonical source
    if pending_shim is not None:
        if not isinstance(pending_shim, dict):
            errors.append("SHIM_INVALID_TYPE: must be dict")
        elif pending_shim.get("is_canonical", True) is not False:
            errors.append("SHIM_CANONICAL_VIOLATION: is_canonical must be false")

    verdict = "PASS" if not errors else "FAIL"
    return {"verdict": verdict, "errors": errors, "error_count": len(errors)}


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else         "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"
    with open(path) as f:
        data = json.load(f)
    result = validate(data)
    print(json.dumps(result, ensure_ascii=False, indent=2))

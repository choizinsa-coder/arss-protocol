ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
# tools/delta_context/event_type_target_validator.py
# DQ-003 event_type × target_key mapping — HARD CODED
# 매핑 변경: OS-level EAG 필요

from typing import Any

# ── DQ-003 Canonical Mapping ──────────────────────────────────────────────────
EVENT_TARGET_MAP: dict[str, dict] = {
    "task_status_update": {
        "allowed_targets": ["status", "eag_stage"],
        "value_type": {"status": "str_enum", "eag_stage": "str_enum"},
    },
    "task_created": {
        "allowed_targets": ["task_entry"],
        "value_type": {"task_entry": "dict"},
    },
    "task_completed": {
        "allowed_targets": ["status", "completed_session", "completed_date"],
        "value_type": {
            "status": "str_enum",
            "completed_session": "int",
            "completed_date": "str_iso_date",
        },
    },
    "governance_directive": {
        "allowed_targets": ["canonical_rules"],
        "value_type": {"canonical_rules": "dict"},
    },
    "lesson_added": {
        "allowed_targets": ["lesson_entry"],
        "value_type": {"lesson_entry": "dict"},
    },
    "decision_recorded": {
        "allowed_targets": ["decision_entry"],
        "value_type": {"decision_entry": "dict"},
    },
    "chain_updated": {
        "allowed_targets": ["chain_tip", "last_rpu"],
        "value_type": {"chain_tip": "str_hash", "last_rpu": "str"},
    },
    "runtime_state_changed": {
        "allowed_targets": ["system_state", "activation_allowed"],
        "value_type": {"system_state": "str_enum", "activation_allowed": "bool"},
    },
    "agent_focus_updated": {
        "allowed_targets": ["agent_focus"],
        "value_type": {"agent_focus": "dict"},
    },
    "document_approved": {
        "allowed_targets": ["document_entry"],
        "value_type": {"document_entry": "dict"},
    },
}

# ── Boolean strict rule (BK-2) ────────────────────────────────────────────────
_FORBIDDEN_BOOL_STRINGS = {"true", "false", "True", "False", "TRUE", "FALSE"}


def _validate_value_type(expected_type: str, value: Any) -> bool:
    if expected_type == "bool":
        if isinstance(value, str) and value in _FORBIDDEN_BOOL_STRINGS:
            return False  # string boolean 금지
        return isinstance(value, bool)
    if expected_type == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type in ("str_enum", "str_hash", "str", "str_iso_date"):
        return isinstance(value, str) and len(value) > 0
    if expected_type == "dict":
        return isinstance(value, dict)
    return False


def validate(event_type: str, target_key: str, new_value: Any) -> dict:
    """
    Returns:
        {"valid": True}
        {"valid": False, "reason": str}
    """
    if event_type not in EVENT_TARGET_MAP:
        return {
            "valid": False,
            "reason": f"UNKNOWN_EVENT_TYPE: {event_type!r} — HARD STOP. inferring 금지.",
        }

    mapping = EVENT_TARGET_MAP[event_type]

    if target_key not in mapping["allowed_targets"]:
        return {
            "valid": False,
            "reason": (
                f"TARGET_NOT_ALLOWED: event_type={event_type!r} "
                f"does not permit target_key={target_key!r}"
            ),
        }

    expected_type = mapping["value_type"][target_key]
    if not _validate_value_type(expected_type, new_value):
        return {
            "valid": False,
            "reason": (
                f"VALUE_TYPE_MISMATCH: target_key={target_key!r} "
                f"expects {expected_type}, got {type(new_value).__name__!r} "
                f"value={new_value!r}"
            ),
        }

    return {"valid": True}

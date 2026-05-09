ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
from dataclasses import dataclass
from .classifier import classify_statement, ClassificationResult
from .context_schema import (
    validate_sep_context, has_valid_receipt, verifier_pass,
    verifier_is_fresh, has_existing_evidence
)
from .formatter import format_exploration, format_proposed, format_assertion
from .patterns import has_next_action

@dataclass
class EnforcementResult:
    status: str
    label: str
    reason: str
    formatted_output: str | None

def enforce_statement(text: str, context: dict) -> EnforcementResult:
    cls = classify_statement(text)

    if cls.label == "E":
        return EnforcementResult("PASS", "E", cls.reason, format_exploration(text))

    if cls.label == "P":
        if not has_next_action(text):
            return EnforcementResult("BLOCKED", "P", "missing Next Action", None)
        return EnforcementResult("PASS", "P", cls.reason, format_proposed(text))

    if cls.label == "A":
        try:
            validate_sep_context(context)
        except Exception as e:
            return EnforcementResult("BLOCKED", "A", f"context validation error: {e}", None)
        if not has_valid_receipt(context):
            return EnforcementResult("BLOCKED", "A", "missing valid receipt", None)
        if not verifier_is_fresh(context):
            return EnforcementResult("BLOCKED", "A", "stale or invalid verifier result", None)
        if not has_existing_evidence(context):
            return EnforcementResult("BLOCKED", "A", "missing or nonexistent evidence", None)
        return EnforcementResult("PASS", "A", cls.reason, format_assertion(text, context))

    return EnforcementResult("BLOCKED", "?", "unknown label", None)

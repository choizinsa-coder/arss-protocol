from dataclasses import dataclass
from typing import Literal
from .patterns import (
    matches_exploration, matches_assertion_state, has_uncertainty_marker,
    matches_proposed_action, matches_auto_assertion
)

StatementLabel = Literal["E", "P", "A"]

@dataclass
class ClassificationResult:
    label: StatementLabel
    reason: str
    matched_pattern: str | None = None

def classify_statement(text: str) -> ClassificationResult:
    normalized = ' '.join(text.strip().split())

    # Priority 1: exploration
    if matches_exploration(normalized):
        # Exception: explicit assertion state without uncertainty
        if matches_assertion_state(normalized) and not has_uncertainty_marker(normalized):
            return ClassificationResult("A", "explicit finalized state despite exploration context", "assertion_pattern")
        return ClassificationResult("E", "uncertainty/exploration detected", "exploration_pattern")

    # Priority 2: proposed action
    if matches_proposed_action(normalized):
        return ClassificationResult("P", "action proposal detected", "proposed_pattern")

    # Priority 3: auto-assertion
    if matches_auto_assertion(normalized):
        return ClassificationResult("A", "ambiguous-finalizing expression with state term", "auto_assertion_pattern")

    # Priority 4: explicit assertion
    if matches_assertion_state(normalized):
        return ClassificationResult("A", "explicit state assertion detected", "assertion_pattern")

    # Fallback
    return ClassificationResult("E", "default exploration fallback", None)

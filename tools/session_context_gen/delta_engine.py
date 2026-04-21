import os
from dataclasses import dataclass, field

from .hash_utils import compute_hash


class DeltaEngineError(Exception):
    pass


@dataclass
class DeltaResult:
    status: str  # "NO_CHANGE" | "CHANGED"
    baseline_hash: str
    current_hash: str
    diagnostic: dict = field(default_factory=dict)


def compute_delta(baseline_receipt: dict, current_artifact_path: str) -> DeltaResult:
    """
    Compare artifact hashes. Judgment: hash comparison ONLY.
    line_count stored in diagnostic only — never used for judgment.
    """
    ext = baseline_receipt.get("extension", {})
    baseline_hash = ext.get("artifact_hash", "")
    if not baseline_hash:
        raise DeltaEngineError(
            "baseline_receipt missing extension.artifact_hash — cannot compute delta"
        )

    if not os.path.exists(current_artifact_path):
        raise DeltaEngineError(f"Artifact not found: {current_artifact_path}")

    with open(current_artifact_path, "r", encoding="utf-8") as f:
        content = f.read()

    current_hash = compute_hash(content)

    line_count = content.count('\n') + (1 if content and not content.endswith('\n') else 0)

    status = "NO_CHANGE" if current_hash == baseline_hash else "CHANGED"

    return DeltaResult(
        status=status,
        baseline_hash=baseline_hash,
        current_hash=current_hash,
        diagnostic={"line_count": line_count},
    )

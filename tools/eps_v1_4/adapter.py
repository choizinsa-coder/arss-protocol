ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
from datetime import datetime, timezone
from pathlib import Path
from .context_schema import CANONICAL_BASE
from .exceptions import ContextValidationError

def _normalize_evidence_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    result = []
    for p in paths:
        path = Path(p)
        if not path.is_absolute():
            path = CANONICAL_BASE / path
        result.append(str(path))
    return result

def _shape_verifier_result(vr: dict | None) -> dict:
    if not vr:
        return {"status": "UNKNOWN", "checked_at": None, "ttl_sec": 30}
    return {
        "status": vr.get("status", "UNKNOWN"),
        "checked_at": vr.get("checked_at", None),
        "ttl_sec": vr.get("ttl_sec", 30),
    }

def build_wrapper_payload(
    *,
    raw_output: str,
    receipt: dict | None,
    verifier_result: dict | None,
    evidence_paths: list[str] | None,
    source_type: str,
    timestamp: str | None = None,
) -> dict:
    if not raw_output or not isinstance(raw_output, str):
        raise ContextValidationError("raw_output is required and must be a string")
    if not source_type:
        raise ContextValidationError("source_type is required")

    ts = timestamp or datetime.now(timezone.utc).isoformat()

    return {
        "raw_output": raw_output,
        "context": {
            "receipt": receipt,
            "verifier_result": _shape_verifier_result(verifier_result),
            "evidence_paths": _normalize_evidence_paths(evidence_paths),
            "source_type": source_type,
        },
        "metadata": {
            "stage": "pre_output",
            "timestamp": ts,
        }
    }

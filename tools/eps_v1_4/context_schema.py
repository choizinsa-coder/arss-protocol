from datetime import datetime, timezone
from pathlib import Path
from .exceptions import ContextValidationError

CANONICAL_BASE = Path("/opt/arss/engine/arss-protocol/")

def normalize_evidence_path(p: str) -> Path:
    path = Path(p)
    if path.is_absolute():
        return path
    return CANONICAL_BASE / path

def validate_sep_context(context: dict) -> None:
    if not isinstance(context, dict):
        raise ContextValidationError("context must be a dict")

def has_valid_receipt(context: dict) -> bool:
    receipt = context.get("receipt")
    if not receipt:
        return False
    return isinstance(receipt, dict) and bool(receipt.get("receipt_id"))

def verifier_pass(context: dict) -> bool:
    vr = context.get("verifier_result")
    if not vr:
        return False
    return vr.get("status") == "PASS"

def verifier_is_fresh(context: dict) -> bool:
    vr = context.get("verifier_result")
    if not vr:
        return False
    if vr.get("status") != "PASS":
        return False
    checked_at_raw = vr.get("checked_at")
    ttl_sec = vr.get("ttl_sec")
    if not checked_at_raw or ttl_sec is None:
        return False
    try:
        checked_at = datetime.fromisoformat(checked_at_raw)
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - checked_at).total_seconds() <= ttl_sec
    except (ValueError, TypeError):
        return False

def has_existing_evidence(context: dict) -> bool:
    paths = context.get("evidence_paths")
    if not paths:
        return False
    try:
        return all(normalize_evidence_path(p).exists() for p in paths)
    except Exception:
        return False

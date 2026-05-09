ACTIVE_VERSION = "1.0.0"
VERSION_STATUS = "active"
from .context_schema import has_valid_receipt, normalize_evidence_path

def format_exploration(text: str) -> str:
    return f"[E] {text.strip()}"

def format_proposed(text: str) -> str:
    return f"[P] {text.strip()}"

def format_assertion(text: str, context: dict) -> str:
    receipt = context.get("receipt", {})
    receipt_id = receipt.get("receipt_id", "UNKNOWN") if receipt else "UNKNOWN"
    vr = context.get("verifier_result", {})
    verifier_status = vr.get("status", "UNKNOWN") if vr else "UNKNOWN"
    paths = context.get("evidence_paths", [])
    evidence_str = paths[0] if paths else "NONE"
    return (
        f"[A] {text.strip()}\n"
        f"Evidence: {evidence_str}\n"
        f"Verifier: {verifier_status}\n"
        f"Receipt: {receipt_id}"
    )

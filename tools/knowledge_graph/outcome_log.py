#!/usr/bin/env python3
"""outcome_log.py v1.0.0 -- KG Phase 2 Decision Outcome append-only log (EAG-S333-KG-PHASE2-001)

Decision Ledger has no outcome field; KG-level outcome log records actual
success/failure of decisions for Confidence Calibration (Section 5.4).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
EAG_ID  = "EAG-S333-KG-PHASE2-001"

ROOT = Path("/opt/arss/engine/arss-protocol")
KG_DIR = ROOT / "tools" / "knowledge_graph"
OUTCOME_LOG_PATH = KG_DIR / "decision_outcome.jsonl"

VALID_OUTCOMES = frozenset({"success", "failure"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lookup_predicted_confidence(decision_node_id: str):
    """node_index lookup predicted_confidence for decision_node_id (None if absent)."""
    try:
        from tools.knowledge_graph import storage
        nodes = storage.read_node_index_by_type("DecisionNode")
        for n in nodes:
            if n.get("node_id") == decision_node_id:
                sr = n.get("source_ref", {})
                pc = sr.get("predicted_confidence")
                if pc is None:
                    pc = n.get("predicted_confidence")
                return pc
    except Exception:
        return None
    return None


def record_outcome(
    decision_node_id: str,
    outcome: str,
    outcome_at: str = None,
    outcome_detail: str = "",
    confirmed_by: str = "",
    predicted_confidence=None,
) -> dict:
    """Record actual decision outcome to decision_outcome.jsonl (append-only)."""
    if outcome not in VALID_OUTCOMES:
        return {"recorded": False, "error": "invalid outcome: " + str(outcome)}
    if predicted_confidence is None:
        predicted_confidence = _lookup_predicted_confidence(decision_node_id)
    entry = {
        "schema":               "decision_outcome_v1",
        "decision_node_id":     decision_node_id,
        "outcome":              outcome,
        "predicted_confidence": predicted_confidence,
        "outcome_at":           outcome_at or _now_iso(),
        "confirmed_by":         confirmed_by,
        "outcome_detail":       outcome_detail,
    }
    KG_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTCOME_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
    return {"recorded": True, "entry": entry}


def load_all_outcomes() -> list:
    """Load all decision_outcome.jsonl. [] if file absent."""
    if not OUTCOME_LOG_PATH.exists():
        return []
    entries = []
    with open(OUTCOME_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries

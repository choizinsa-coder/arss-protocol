#!/usr/bin/env python3
"""merkle.py v1.0.0 -- KG Phase 2-A Merkle Graph Anchor (EAG-S333-KG-PHASE2-001)

Anchors the entire node_index.jsonl into a single Merkle Root for cumulative
integrity. Independent append-only verification chain, separate from
govdoc_freeze_gate (per-file hash). Pure hashlib. Phase 1 storage.py unmodified
(explicit call only).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from tools.knowledge_graph import storage

VERSION = "1.0.0"
EAG_ID = "EAG-S333-KG-PHASE2-001"

KG_DIR = storage.KG_DIR
NODE_INDEX_PATH = storage.NODE_INDEX_PATH
ANCHOR_PATH = KG_DIR / "merkle_anchor.json"

EMPTY_ROOT = "0" * 64
ANCHOR_HISTORY_MAX = 10

NL = chr(10)


def _leaf_hash(line: str) -> str:
    """node_index line -> SHA-256 leaf hash (trailing newline stripped)."""
    return storage.compute_hash(line.rstrip(NL))


def _merkle_root(leaf_hashes: list) -> str:
    """Standard binary Merkle Root. Odd leaf self-pairs. Empty -> sentinel."""
    if not leaf_hashes:
        return EMPTY_ROOT
    layer = list(leaf_hashes)
    while len(layer) > 1:
        next_layer = []
        for i in range(0, len(layer), 2):
            if i + 1 < len(layer):
                combined = layer[i] + layer[i + 1]
            else:
                combined = layer[i] + layer[i]
            next_layer.append(storage.compute_hash(combined))
        layer = next_layer
    return layer[0]


def get_leaf_hashes() -> list:
    """Leaf hash list for each line of node_index.jsonl."""
    if not NODE_INDEX_PATH.exists():
        return []
    leaves = []
    with open(NODE_INDEX_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                leaves.append(_leaf_hash(line))
    return leaves


def compute_current_root() -> str:
    """Current node_index.jsonl -> Merkle Root."""
    return _merkle_root(get_leaf_hashes())


def _load_anchor() -> dict:
    """Load merkle_anchor.json. Empty dict if absent."""
    if not ANCHOR_PATH.exists():
        return {}
    try:
        with open(ANCHOR_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _count_nodes() -> int:
    """node_index node count."""
    if not NODE_INDEX_PATH.exists():
        return 0
    count = 0
    with open(NODE_INDEX_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _last_node_id() -> str:
    """Last node id."""
    last = ""
    if not NODE_INDEX_PATH.exists():
        return last
    with open(NODE_INDEX_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line).get("node_id", "")
                except json.JSONDecodeError:
                    pass
    return last


def compute_and_store_anchor() -> dict:
    """Compute Merkle Root + store merkle_anchor.json (explicit call only)."""
    root = compute_current_root()
    node_count = _count_nodes()
    now = datetime.now(timezone.utc).isoformat()
    prev = _load_anchor()

    history = prev.get("anchor_history", [])
    if prev.get("merkle_root") and prev.get("merkle_root") != root:
        history.append({
            "merkle_root": prev["merkle_root"],
            "node_count": prev.get("node_count", 0),
            "updated_at": prev.get("last_updated", ""),
        })
        history = history[-ANCHOR_HISTORY_MAX:]

    anchor = {
        "schema": "merkle_anchor_v1",
        "version": VERSION,
        "eag": EAG_ID,
        "node_count": node_count,
        "merkle_root": root,
        "root_hash_of": "tools/knowledge_graph/node_index.jsonl",
        "last_updated": now,
        "last_node_id": _last_node_id(),
        "anchor_history": history,
    }
    KG_DIR.mkdir(parents=True, exist_ok=True)
    with open(ANCHOR_PATH, "w", encoding="utf-8") as f:
        json.dump(anchor, f, ensure_ascii=False, indent=2)
    return anchor


def verify_merkle_anchor() -> dict:
    """Recompute root from current node_index vs stored anchor root."""
    stored = _load_anchor()
    computed_root = compute_current_root()
    node_count = _count_nodes()
    if not stored:
        return {
            "valid": False,
            "computed_root": computed_root,
            "stored_root": None,
            "node_count": node_count,
            "error": "anchor not found",
        }
    stored_root = stored.get("merkle_root")
    valid = (computed_root == stored_root)
    return {
        "valid": valid,
        "computed_root": computed_root,
        "stored_root": stored_root,
        "node_count": node_count,
        "error": None if valid else "root mismatch",
    }


def get_anchor_snapshot() -> dict:
    """Return full merkle_anchor.json content (read-only)."""
    return _load_anchor()

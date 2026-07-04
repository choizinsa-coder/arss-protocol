#!/usr/bin/env python3
"""storage.py v1.0.0 -- KG Phase 1 node_index.jsonl CRUD (EAG-S332-MVKG-001)"""
import hashlib
import json
from pathlib import Path

VERSION = "1.0.0"
EAG_ID  = "EAG-S332-MVKG-001"
ROOT = Path("/opt/arss/engine/arss-protocol")
KG_DIR = ROOT / "tools" / "knowledge_graph"
NODE_INDEX_PATH = KG_DIR / "node_index.jsonl"


def _load_all_nodes() -> list:
    """node_index.jsonl 전체 로드. 파일 미존재 시 []"""
    if not NODE_INDEX_PATH.exists():
        return []
    entries = []
    with open(NODE_INDEX_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def write_node_index(entry: dict) -> bool:
    """node_index.jsonl에 1건 append. 중복 시 False."""
    existing = _load_all_nodes()
    existing_keys = {e.get("source_ref_key") for e in existing if e.get("source_ref_key")}
    new_key = entry.get("source_ref_key", "")
    if new_key and new_key in existing_keys:
        return False
    KG_DIR.mkdir(parents=True, exist_ok=True)
    with open(NODE_INDEX_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
    return True


def bulk_write_node_index(entries: list) -> dict:
    """복수 entry 일괄 등록. {registered, skipped} 반환"""
    existing = _load_all_nodes()
    existing_keys = {e.get("source_ref_key") for e in existing if e.get("source_ref_key")}
    to_write = []
    skipped = 0
    for entry in entries:
        key = entry.get("source_ref_key", "")
        if key and key in existing_keys:
            skipped += 1
        else:
            to_write.append(entry)
            if key:
                existing_keys.add(key)
    if to_write:
        KG_DIR.mkdir(parents=True, exist_ok=True)
        with open(NODE_INDEX_PATH, "a", encoding="utf-8") as f:
            for e in to_write:
                f.write(json.dumps(e, ensure_ascii=False) + chr(10))
    return {"registered": len(to_write), "skipped": skipped}


def read_node_index() -> list:
    """노드 인덱스 전체 로드 (최신순)."""
    return list(reversed(_load_all_nodes()))


def read_node_index_by_type(node_type: str) -> list:
    """타입별 노드 인덱스 (마지막 occurrence = 최신)."""
    seen: dict = {}
    for node in _load_all_nodes():
        if node.get("node_type") == node_type:
            nid = node.get("node_id")
            if nid:
                seen[nid] = node
    return list(seen.values())


def compute_hash(content: str) -> str:
    """SHA-256 해시 생성 (ARSS hash Phase 1)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

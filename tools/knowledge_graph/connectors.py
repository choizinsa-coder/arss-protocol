#!/usr/bin/env python3
"""connectors.py v1.0.0 -- KG Phase 1 Area11/15/5 -> node_index 어댑터 (EAG-S332-MVKG-001)"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S332-MVKG-001"
ROOT = Path("/opt/arss/engine/arss-protocol")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.governance import area_11_decision_ledger as dl
from tools.governance import area_15_failure_memory as fm
from tools.governance import sovereign_authority as sa
from tools.knowledge_graph import storage


def _compute_ref_key(source_store: str, entry: dict) -> str:
    """중복 방지용 source_ref 식별키 (SHA-256 16자)"""
    if source_store == "decision_ledger":
        raw = "|".join([
            entry.get("dc", ""),
            entry.get("subject", ""),
            entry.get("declared_at", ""),
        ])
    elif source_store == "failure_memory":
        raw = "|".join([
            entry.get("rc", ""),
            entry.get("component", ""),
            entry.get("error_code", ""),
            entry.get("recorded_at", ""),
        ])
    elif source_store == "sovereign_override":
        raw = "|".join([
            entry.get("eag", ""),
            entry.get("scope", ""),
            entry.get("override_target", ""),
            entry.get("declared_at", ""),
        ])
    else:
        raw = json.dumps(entry, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _build_node(node_type: str, source_store: str,
                source_ref: dict, ref_key: str) -> dict:
    """node_index.jsonl 항목 1건 생성"""
    prefix_map = {
        "decision_ledger": "DL",
        "failure_memory": "FM",
        "sovereign_override": "SO",
    }
    prefix = prefix_map.get(source_store, "KG")
    return {
        "schema":         "node_index_v1",
        "node_id":        prefix + "-" + ref_key[:12],
        "node_type":      node_type,
        "source_store":   source_store,
        "source_ref":     source_ref,
        "source_ref_key": ref_key,
        "status":         "active",
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }


def _load_jsonl(path: Path) -> list:
    """JSONL 파일 로드. 파일 미존재 시 []"""
    if not path.exists():
        return []
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def import_area11_to_kg(ledger_path: Optional[str] = None) -> dict:
    """decision_ledger.jsonl -> node_index.jsonl DecisionNode 일괄 등록"""
    path = Path(ledger_path) if ledger_path else dl.LOG_PATH
    if not path.exists():
        return {"registered": 0, "skipped": 0, "error": "path not found: " + str(path)}
    nodes = [
        _build_node("DecisionNode", "decision_ledger", e, _compute_ref_key("decision_ledger", e))
        for e in _load_jsonl(path)
    ]
    return storage.bulk_write_node_index(nodes)


def import_area15_to_kg(memory_path: Optional[str] = None) -> dict:
    """failure_memory.jsonl -> node_index.jsonl FailureNode 일괄 등록"""
    path = Path(memory_path) if memory_path else fm.LOG_PATH
    if not path.exists():
        return {"registered": 0, "skipped": 0, "error": "path not found: " + str(path)}
    nodes = [
        _build_node("FailureNode", "failure_memory", e, _compute_ref_key("failure_memory", e))
        for e in _load_jsonl(path)
    ]
    return storage.bulk_write_node_index(nodes)


def import_sovereign_to_kg(override_path: Optional[str] = None) -> dict:
    """sovereign_override_log.jsonl -> node_index.jsonl OverrideNode 일괄 등록"""
    path = Path(override_path) if override_path else sa.LOG_PATH
    if not path.exists():
        return {"registered": 0, "skipped": 0, "error": "path not found: " + str(path)}
    nodes = [
        _build_node("OverrideNode", "sovereign_override", e, _compute_ref_key("sovereign_override", e))
        for e in _load_jsonl(path)
    ]
    return storage.bulk_write_node_index(nodes)


def register_new_decision(
    dc: str,
    subject: str,
    rationale: str,
    eag: Optional[str] = None,
    actor: str = "unknown",
) -> dict:
    """Area 11 record_decision() + KG 인덱스 동시 등록"""
    try:
        entry = dl.record_decision(
            dc=dc, subject=subject, rationale=rationale, eag=eag, actor=actor,
        )
    except Exception as exc:
        return {"registered": 0, "skipped": 0, "error": str(exc)}
    ref_key = _compute_ref_key("decision_ledger", entry)
    node = _build_node("DecisionNode", "decision_ledger", entry, ref_key)
    return storage.bulk_write_node_index([node])

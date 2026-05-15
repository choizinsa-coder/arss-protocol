"""
AIBA MCP Audit Broker  v1.1.1
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C + Recovery Governance Layer
EAG:   EAG-2 비오(Joshua) 승인 (S128) / EAG-3 비오(Joshua) 승인 (S130)

변경 이력:
- v1.0.0 (PHASE-B, S127): AuditBroker / _AppendOnlyLedger / AuditPersistenceError
- v1.1.0 (PHASE-C, S128): write_audit / write_deny_audit / read_audit_log 추가
- v1.1.1 (S130): HC-T-05 (audit append failure) -> HARD_CONTAINMENT 진입 추가
                 주의: HC-T-05 탐지 시 containment 진입만 수행, audit 자체는 계속 시도
"""

import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

_MCP_DIR = os.path.dirname(os.path.abspath(__file__))
if _MCP_DIR not in sys.path:
    sys.path.insert(0, _MCP_DIR)

AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/audit_trail.log"
PHASE_C_AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/logs/mcp_audit/mcp_audit.log"
T3_AUDIT_PERSISTENCE_TIMEOUT_S = 1.0

_write_lock = threading.Lock()


class AuditPersistenceError(Exception):
    pass


class _AppendOnlyLedger:
    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)


class AuditBroker:
    def __init__(self, ledger=None) -> None:
        self._ledger = ledger or _AppendOnlyLedger(AUDIT_LOG_PATH)
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._worker_thread = threading.Thread(
            target=self._worker, daemon=True, name="audit-broker"
        )
        self._worker_thread.start()
        self._logger = logging.getLogger("aiba_mcp_audit_broker")

    def submit_event(self, tool_name, layer, result_summary, phase, event_type="TOOL_CALL"):
        entry = {
            "event_type": event_type,
            "tool_name": tool_name,
            "layer": layer,
            "result_summary": result_summary,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        confirmed = threading.Event()
        error_holder = []
        self._queue.put((entry, confirmed, error_holder))
        if not confirmed.wait(timeout=T3_AUDIT_PERSISTENCE_TIMEOUT_S):
            raise AuditPersistenceError(
                f"[AUDIT_PERSISTENCE_TIMEOUT] T-3 {T3_AUDIT_PERSISTENCE_TIMEOUT_S}s 초과 "
                f"— tool={tool_name} event_type={event_type}"
            )
        if error_holder:
            raise AuditPersistenceError(
                f"[AUDIT_WRITE_FAILED] tool={tool_name} error={error_holder[0]}"
            )

    def submit_deny(self, tool_name, reason, phase):
        self.submit_event(
            tool_name=tool_name,
            layer="DENY",
            result_summary=f"DENIED reason={reason}",
            phase=phase,
            event_type="TOOL_DENY",
        )

    def _worker(self):
        while True:
            try:
                entry, confirmed, error_holder = self._queue.get(timeout=5.0)
                try:
                    self._ledger.write(entry)
                except Exception as exc:
                    error_holder.append(str(exc))
                    self._logger.error("AUDIT_WRITE_ERROR: %s", exc)
                finally:
                    confirmed.set()
            except queue.Empty:
                continue
            except Exception as exc:
                self._logger.error("AUDIT_BROKER_WORKER_ERROR: %s", exc)


# ── PHASE-C 함수 ──────────────────────────────────────────────────────────────

def _hash_nonce(nonce):
    if nonce is None:
        return None
    return hashlib.sha256(nonce.encode()).hexdigest()


def _trigger_hct05() -> None:
    """HC-T-05: audit append failure -> HARD_CONTAINMENT 진입."""
    try:
        # 순환 import 방지: 런타임 import
        from mcp_containment_state import enter_containment
        enter_containment("HC-T-05")
    except Exception:
        pass


def write_audit(agent_id, requested_shard, returned_scope, decision, reason,
                source_hash=None, load_state="UNKNOWN", retrieval_class="UNKNOWN",
                nonce=None, log_path=None):
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+09:00", time.localtime()),
        "agent_id": agent_id,
        "requested_shard": requested_shard,
        "returned_scope": returned_scope,
        "decision": decision,
        "reason": reason,
        "source_hash": source_hash or "UNKNOWN",
        "load_state": load_state,
        "retrieval_class": retrieval_class,
        "nonce_hash": _hash_nonce(nonce),
    }
    target_path = log_path or PHASE_C_AUDIT_LOG_PATH
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with _write_lock:
            with open(target_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, IOError) as exc:
        # HC-T-05: audit append 실패 탐지
        _trigger_hct05()
        raise
    return record


def write_deny_audit(agent_id, requested_shard, reason, nonce=None, log_path=None):
    return write_audit(
        agent_id=agent_id,
        requested_shard=requested_shard,
        returned_scope="NONE",
        decision="DENY",
        reason=reason,
        source_hash=None,
        load_state="DENIED",
        retrieval_class="CLASS-D",
        nonce=nonce,
        log_path=log_path,
    )


def read_audit_log(log_path=None):
    target_path = log_path or PHASE_C_AUDIT_LOG_PATH
    if not os.path.exists(target_path):
        return []
    records = []
    with open(target_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return records

"""
AIBA MCP Audit Broker  v1.0.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-B
EAG:   EAG-2 비오(Joshua) 승인 (S127)
설계:  도미 PHASE-B FINAL ANCHOR + SUPPLEMENTAL ANCHOR

=============================================================================
B-2-B Authority Separation 계약
=============================================================================
- execution layer는 audit event 생성만 수행
- audit write authority는 본 broker에만 귀속
- execution authority ≠ audit authority 구조적 보장
- audit 기록 실패 = retrieval 결과 신뢰 실패 (AUDIT_UNVERIFIED_RESULT)

=============================================================================
B-3 T-3 Audit Persistence Timeout
=============================================================================
- T-3 상한: 1 second
- timeout 시 FAIL_CLOSED — AuditPersistenceError 발생
- 호출측이 AUDIT_UNVERIFIED_RESULT 처리 책임
"""

import json
import logging
import os
import queue
import threading
import time
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/audit_trail.log"
T3_AUDIT_PERSISTENCE_TIMEOUT_S = 1.0  # B-3 T-3: 1 second


# ---------------------------------------------------------------------------
# 예외
# ---------------------------------------------------------------------------

class AuditPersistenceError(Exception):
    """B-3 T-3 timeout 또는 broker 기록 실패 시 발생."""


# ---------------------------------------------------------------------------
# Append-only Audit Ledger (파일 기반)
# ---------------------------------------------------------------------------

class _AppendOnlyLedger:
    """append-only 파일 기반 audit ledger. broker 스레드에서만 접근."""

    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def write(self, entry: dict) -> None:
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line)


# ---------------------------------------------------------------------------
# Audit Broker (append broker separation)
# ---------------------------------------------------------------------------

class AuditBroker:
    """
    B-2-B: execution layer와 audit write authority를 분리하는 broker.

    - execution layer는 submit_event()로 audit event를 생성만 함
    - 실제 write는 본 broker의 전담 스레드(_worker)만 수행
    - T-3 timeout(1s) 초과 시 AuditPersistenceError 발생
    """

    def __init__(self, ledger: Optional[_AppendOnlyLedger] = None) -> None:
        self._ledger = ledger or _AppendOnlyLedger(AUDIT_LOG_PATH)
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._worker_thread = threading.Thread(
            target=self._worker, daemon=True, name="audit-broker"
        )
        self._worker_thread.start()
        self._logger = logging.getLogger("aiba_mcp_audit_broker")

    # ------------------------------------------------------------------
    # Public API (execution layer 호출 전용)
    # ------------------------------------------------------------------

    def submit_event(
        self,
        tool_name: str,
        layer: str,
        result_summary: str,
        phase: str,
        event_type: str = "TOOL_CALL",
    ) -> None:
        """
        execution layer가 audit event를 생성하여 broker에 위임.
        T-3 timeout 내 broker 기록 확정을 기다림.
        실패 시 AuditPersistenceError 발생 — 호출측은 AUDIT_UNVERIFIED_RESULT 처리.
        """
        entry = {
            "event_type": event_type,
            "tool_name": tool_name,
            "layer": layer,
            "result_summary": result_summary,
            "phase": phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        confirmed = threading.Event()
        error_holder: list = []

        self._queue.put((entry, confirmed, error_holder))

        # T-3: 1초 내 확정 대기
        if not confirmed.wait(timeout=T3_AUDIT_PERSISTENCE_TIMEOUT_S):
            raise AuditPersistenceError(
                f"[AUDIT_PERSISTENCE_TIMEOUT] T-3 {T3_AUDIT_PERSISTENCE_TIMEOUT_S}s 초과 "
                f"— tool={tool_name} event_type={event_type}"
            )
        if error_holder:
            raise AuditPersistenceError(
                f"[AUDIT_WRITE_FAILED] tool={tool_name} error={error_holder[0]}"
            )

    def submit_deny(self, tool_name: str, reason: str, phase: str) -> None:
        """DENY 이벤트 전용 submit. T-3 timeout 적용."""
        self.submit_event(
            tool_name=tool_name,
            layer="DENY",
            result_summary=f"DENIED reason={reason}",
            phase=phase,
            event_type="TOOL_DENY",
        )

    # ------------------------------------------------------------------
    # Broker 전담 write 스레드
    # ------------------------------------------------------------------

    def _worker(self) -> None:
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

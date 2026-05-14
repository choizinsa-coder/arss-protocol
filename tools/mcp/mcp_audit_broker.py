"""
AIBA MCP Audit Broker  v1.1.0
Task:  PT-S125-BOOT-ONDEMAND-001  PHASE-C
EAG:   EAG-2 비오(Joshua) 승인 (S128)
설계:  도미 PHASE-C FINAL ANCHOR (S128)

변경:
- v1.0.0 (PHASE-B): 기본 audit 필드
- v1.1.0 (PHASE-C): nonce_hash 필드 추가 (10개 필드 계약)

책임:
- append-only audit log 기록
- ALLOW / DENY 전항목 기록
- silent drop 금지
- 10개 필수 필드 보장
"""

import hashlib
import json
import os
import threading
import time
from typing import Optional

# audit log 기본 경로
DEFAULT_AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/logs/mcp_audit/mcp_audit.log"

_lock = threading.Lock()


def _hash_nonce(nonce: Optional[str]) -> Optional[str]:
    """nonce를 SHA-256으로 해시 처리 (원본 노출 방지)."""
    if nonce is None:
        return None
    return hashlib.sha256(nonce.encode()).hexdigest()


def write_audit(
    agent_id: str,
    requested_shard: str,
    returned_scope: str,
    decision: str,
    reason: str,
    source_hash: Optional[str] = None,
    load_state: str = "UNKNOWN",
    retrieval_class: str = "UNKNOWN",
    nonce: Optional[str] = None,
    log_path: Optional[str] = None,
) -> dict:
    """
    audit 레코드 생성 및 append-only 기록.

    필수 필드 10개:
    timestamp / agent_id / requested_shard / returned_scope /
    decision / reason / source_hash / load_state /
    retrieval_class / nonce_hash

    DENY 포함 모든 호출 기록. silent drop 금지.
    """
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

    target_path = log_path or DEFAULT_AUDIT_LOG_PATH

    # 디렉토리 생성 (없을 경우)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)

    # append-only 기록
    with _lock:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return record


def write_deny_audit(
    agent_id: str,
    requested_shard: str,
    reason: str,
    nonce: Optional[str] = None,
    log_path: Optional[str] = None,
) -> dict:
    """
    DENY 전용 audit 기록 헬퍼.
    모든 DENY 경로에서 반드시 호출.
    """
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


def read_audit_log(log_path: Optional[str] = None) -> list[dict]:
    """
    audit log 전체 읽기 (테스트·감사용).
    read-only — 수정 불가.
    """
    target_path = log_path or DEFAULT_AUDIT_LOG_PATH
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

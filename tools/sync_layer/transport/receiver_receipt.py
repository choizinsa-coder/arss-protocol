"""
receiver_receipt.py
AIBA Sync Layer — Transport Receiver Receipt (P4-T2)
SSOT: Domi P4-T1 Design (S172) / EAG-2 Approved (비오(Joshua))

역할:
  - TRANSPORT_RECEIVER_RECEIPT 생성 및 저장
  - n8n WF-T1/WF-T2 수신 완료 증거 영속화
  - deploy_executor Receipt와 완전 분리 (독립 타입)

Receipt 의미:
  "전송 수신과 검증 완료" (업무 처리 완료 아님)

저장 위치:
  registry/transport_receiver_receipts/

금지:
  - deploy_executor Tier 1/2 Receipt와 병합
  - 비즈니스 로직 포함
  - 자동 갱신 (모든 변경은 EAG 필요)
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
RECEIPT_DIR = VPS_ROOT / "registry" / "transport_receiver_receipts"

RECEIPT_TYPE = "TRANSPORT_RECEIVER_RECEIPT"
RECEIPT_VERSION = "TRANSPORT_RECEIVER_RECEIPT_v1"

# binding_status
BINDING_MATCH = "MATCH"
BINDING_MISMATCH = "MISMATCH"
BINDING_UNKNOWN = "UNKNOWN"

# schema_status
SCHEMA_PASS = "PASS"
SCHEMA_FAIL = "FAIL"

# result
RESULT_ACCEPTED = "ACCEPTED"
RESULT_REJECTED = "REJECTED"

VALID_RECEIVERS = frozenset({"WF-T1", "WF-T2"})
VALID_EVENT_TYPES = frozenset({"DEPLOYMENT_EVENT", "SYNC_EVENT"})
VALID_ENDPOINT_IDS = frozenset({"aiba-deployment", "aiba-sync"})


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _now_kst() -> str:
    """현재 KST ISO8601 반환. CC=1"""
    return datetime.now(KST).isoformat()


def _build_receipt_id(receiver: str, event_type: str) -> str:
    """
    receipt_id 생성.
    형식: TRCPT-{RECEIVER}-{UTC_TS}-{SHORT_HASH}
    CC=1
    """
    utc_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short = hashlib.sha256(f"{receiver}{event_type}{utc_ts}".encode()).hexdigest()[:6].upper()
    return f"TRCPT-{receiver}-{utc_ts}-{short}"


def _fsync_write(path: Path, content: str) -> bool:
    """파일 쓰기 + fsync. 실패 시 False. CC=2"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
                return True
            except OSError as exc:
                logger.warning("FSYNC_DEGRADED: %s — %s", path, exc)
                return False
    except OSError as exc:
        logger.error("FILE_WRITE_FAILED: %s — %s", path, exc)
        return False


# ── Receipt 생성 ────────────────────────────────────────────────────────────

def create_receiver_receipt(
    receiver: str,
    event_type: str,
    endpoint_id: str,
    binding_status: str,
    schema_status: str,
    result: str,
    reason: Optional[str] = None,
    payload_hash: Optional[str] = None,
    session: Optional[int] = None,
) -> dict:
    """
    TRANSPORT_RECEIVER_RECEIPT 딕셔너리 생성 (저장 없음).
    도미 P4-T1 설계 9개 필드 준수.
    CC=3
    """
    if receiver not in VALID_RECEIVERS:
        logger.warning("RECEIPT_INVALID_RECEIVER: %s", receiver)
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("RECEIPT_INVALID_EVENT_TYPE: %s", event_type)
    if endpoint_id not in VALID_ENDPOINT_IDS:
        logger.warning("RECEIPT_INVALID_ENDPOINT_ID: %s", endpoint_id)

    receipt_id = _build_receipt_id(receiver, event_type)

    receipt = {
        "receipt_id": receipt_id,
        "receipt_type": RECEIPT_TYPE,
        "receipt_version": RECEIPT_VERSION,
        "receiver": receiver,
        "event_type": event_type,
        "endpoint_id": endpoint_id,
        "binding_status": binding_status,
        "schema_status": schema_status,
        "received_at": _now_kst(),
        "result": result,
        "reason": reason,
    }

    if payload_hash is not None:
        receipt["payload_hash"] = payload_hash
    if session is not None:
        receipt["session"] = session

    return receipt


def save_receiver_receipt(receipt: dict) -> bool:
    """
    TRANSPORT_RECEIVER_RECEIPT를 registry/transport_receiver_receipts/ 에 저장.
    반환: 저장 성공 여부
    CC=2
    """
    receipt_id = receipt.get("receipt_id", "UNKNOWN")
    path = RECEIPT_DIR / f"{receipt_id}.json"
    success = _fsync_write(path, json.dumps(receipt, ensure_ascii=False, indent=2))
    if success:
        logger.info(
            "RECEIVER_RECEIPT_SAVED: receipt_id=%s result=%s",
            receipt_id, receipt.get("result"),
        )
    else:
        logger.error("RECEIVER_RECEIPT_SAVE_FAILED: receipt_id=%s", receipt_id)
    return success


def create_and_save_receipt(
    receiver: str,
    event_type: str,
    endpoint_id: str,
    binding_status: str,
    schema_status: str,
    result: str,
    reason: Optional[str] = None,
    payload_hash: Optional[str] = None,
    session: Optional[int] = None,
) -> tuple:
    """
    Receipt 생성 + 저장 원자적 실행.
    반환: (receipt dict, saved bool)
    CC=2
    """
    receipt = create_receiver_receipt(
        receiver=receiver,
        event_type=event_type,
        endpoint_id=endpoint_id,
        binding_status=binding_status,
        schema_status=schema_status,
        result=result,
        reason=reason,
        payload_hash=payload_hash,
        session=session,
    )
    saved = save_receiver_receipt(receipt)
    return receipt, saved


def get_receipt_store_status() -> dict:
    """Receipt 저장소 상태 요약 (관측/감사용). CC=2"""
    count = 0
    if RECEIPT_DIR.exists():
        count = len(list(RECEIPT_DIR.glob("*.json")))
    return {
        "component": "receiver_receipt",
        "layer": "sync_layer/transport",
        "p4_task": "P4-T2",
        "receipt_type": RECEIPT_TYPE,
        "receipt_version": RECEIPT_VERSION,
        "receipt_dir": str(RECEIPT_DIR),
        "receipt_count": count,
        "valid_receivers": sorted(VALID_RECEIVERS),
        "valid_event_types": sorted(VALID_EVENT_TYPES),
        "result_enum": [RESULT_ACCEPTED, RESULT_REJECTED],
        "deploy_executor_coupling": "NONE — 독립 타입",
    }

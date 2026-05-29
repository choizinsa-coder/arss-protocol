"""
transport_contract.py
AIBA Sync Layer — Transport Contract (Payload Validator)
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

역할:
  - DEPLOYMENT_EVENT / SYNC_EVENT payload 스키마 검증
  - payload_hash 계산
  - event_id 추출

금지:
  - HTTP 호출
  - 파일 I/O
  - 상태 변경
"""

import hashlib
import json
from typing import Tuple

from tools.sync_layer.transport.transport_types import (
    EVENT_TYPE_DEPLOYMENT,
    EVENT_TYPE_SYNC,
    VALID_EVENT_TYPES,
    DEPLOYMENT_EVENT_REQUIRED_FIELDS,
    SYNC_EVENT_REQUIRED_FIELDS,
    VALID_DEPLOY_RESULTS,
)


def validate_payload(payload: dict) -> Tuple[bool, str]:
    """
    Payload 스키마 검증.
    반환: (valid: bool, error_message: str)
    CC=3
    """
    if not payload or not isinstance(payload, dict):
        return False, "EMPTY_OR_INVALID_PAYLOAD"

    event_type = payload.get("event_type")
    if event_type not in VALID_EVENT_TYPES:
        return False, f"INVALID_EVENT_TYPE: {event_type}"

    if event_type == EVENT_TYPE_DEPLOYMENT:
        return _validate_deployment_event(payload)
    return _validate_sync_event(payload)


def _validate_deployment_event(payload: dict) -> Tuple[bool, str]:
    """DEPLOYMENT_EVENT 필수 필드 + result enum 검증. CC=3"""
    missing = DEPLOYMENT_EVENT_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        return False, f"MISSING_FIELDS: {sorted(missing)}"

    result = payload.get("result")
    if result not in VALID_DEPLOY_RESULTS:
        return False, f"INVALID_RESULT: {result}"

    return True, ""


def _validate_sync_event(payload: dict) -> Tuple[bool, str]:
    """SYNC_EVENT 필수 필드 검증. CC=2"""
    missing = SYNC_EVENT_REQUIRED_FIELDS - set(payload.keys())
    if missing:
        return False, f"MISSING_FIELDS: {sorted(missing)}"
    return True, ""


def compute_payload_hash(payload: dict) -> str:
    """Payload dict → SHA256. sort_keys=True로 결정론적 해시 보장. CC=1"""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def extract_event_id(payload: dict) -> str:
    """payload에서 event_id 추출. CC=2"""
    event_type = payload.get("event_type", "")
    if event_type == EVENT_TYPE_DEPLOYMENT:
        return payload.get("deployment_id", "UNKNOWN")
    return payload.get("event_id", "UNKNOWN")

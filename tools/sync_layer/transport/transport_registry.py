"""
transport_registry.py
AIBA Sync Layer — Transport Registry (Endpoint 조회)
SSOT: Domi Phase 3 Design v1.1 (S169) / EAG-1 Approved (비오(Joshua))

역할:
  - registry/transport_endpoints.json 로드
  - event_type 별 active endpoint URL 반환
  - Endpoint 확장 지원 (WF-05 → WF-06 / Discord / Drive / B3)

금지:
  - Endpoint 변경 / 등록
  - HTTP 호출
  - Payload 처리
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
REGISTRY_PATH = VPS_ROOT / "registry" / "transport_endpoints.json"
REGISTRY_VERSION = "TRANSPORT_REGISTRY_v1"


def load_registry() -> dict:
    """Registry 파일 로드. 파일 없거나 파싱 실패 시 빈 dict 반환. CC=3"""
    if not REGISTRY_PATH.exists():
        logger.warning("TRANSPORT_REGISTRY_NOT_FOUND: %s", REGISTRY_PATH)
        return {}
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("TRANSPORT_REGISTRY_LOAD_FAILED: %s", exc)
        return {}


def get_active_endpoint(event_type: str) -> Optional[str]:
    """
    event_type 에 대한 active endpoint URL 반환.
    비활성화 또는 URL 누락 시 None 반환 (Fail-Closed).
    CC=4
    """
    registry = load_registry()
    entry = registry.get("endpoints", {}).get(event_type, {})

    if not entry.get("active", False):
        logger.warning("ENDPOINT_INACTIVE_OR_MISSING: event_type=%s", event_type)
        return None

    url = entry.get("url")
    if not url:
        logger.warning("ENDPOINT_URL_EMPTY: event_type=%s", event_type)
        return None

    return url


def get_registry_status() -> dict:
    """Registry 상태 요약 (관측/감사용). CC=1"""
    registry = load_registry()
    endpoints = registry.get("endpoints", {})
    return {
        "component": "transport_registry",
        "layer": "sync_layer/transport",
        "p3_task": "P3-T3",
        "registry_path": str(REGISTRY_PATH),
        "registry_version": registry.get("version"),
        "endpoint_count": len(endpoints),
        "active_endpoints": [
            k for k, v in endpoints.items() if v.get("active", False)
        ],
    }

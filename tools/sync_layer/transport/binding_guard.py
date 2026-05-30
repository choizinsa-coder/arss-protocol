"""
binding_guard.py
AIBA Sync Layer — Transport Dynamic Binding Guard (P4-T2)
SSOT: Domi P4-T1 Design (S172) / EAG-2 Approved (비오(Joshua))

역할:
  - transport_endpoints.json 등록값 vs 실제 n8n webhook URL 일치 여부 검증
  - 불일치 시: endpoint active=false 처리 + 비동기 예외 신호 전파 (Jeni TA)
  - transport_client는 MISMATCH endpoint로 전송 금지

Binding 검증 방법:
  HEAD 요청 → 404 = MISMATCH / 비-404 = MATCH
  (n8n은 미등록 webhook에 대해 반드시 404 반환)

Jeni Trust Advisory (P4-T2 필수):
  차단 발생 시 비동기 예외 신호를 상위 레이어로 즉시 전파.
  누락 시 시스템 데드락 위험.

금지:
  - 바인딩 불일치 endpoint로의 전송 허용
  - transport_endpoints.json 자동 갱신 (비오 EAG 필수)
  - 비즈니스 로직 포함
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
BINDING_PROBE_TIMEOUT = 5
BINDING_STATUS_MATCH = "MATCH"
BINDING_STATUS_MISMATCH = "MISMATCH"
BINDING_STATUS_UNKNOWN = "UNKNOWN"

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
ENDPOINTS_PATH = VPS_ROOT / "registry" / "transport_endpoints.json"
BINDING_ALERT_DIR = VPS_ROOT / "registry" / "binding_alerts"


# ── 결과 타입 ───────────────────────────────────────────────────────────────

@dataclass
class EndpointBindingResult:
    """
    단일 endpoint 바인딩 검증 결과.
    CC=1
    """
    endpoint_id: str
    url: str
    active: bool
    binding_status: str        # MATCH | MISMATCH | UNKNOWN
    probe_http_status: Optional[int]
    failure_reason: Optional[str]
    checked_at: str


@dataclass
class BindingGuardResult:
    """
    전체 바인딩 가드 실행 결과.
    CC=1
    """
    all_match: bool
    results: list = field(default_factory=list)
    blocked_endpoints: list = field(default_factory=list)
    checked_at: str = ""


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _now_kst() -> str:
    """현재 KST ISO8601 반환. CC=1"""
    return datetime.now(KST).isoformat()


def _load_endpoints() -> dict:
    """
    transport_endpoints.json 로드.
    실패 시 빈 dict 반환 (fail-closed: caller가 처리).
    CC=2
    """
    try:
        with open(ENDPOINTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("ENDPOINTS_LOAD_FAILED: %s", exc)
        return {}


def _probe_endpoint(url: str) -> tuple:
    """
    HEAD 요청으로 endpoint 활성화 여부 probe.
    반환: (binding_status, http_status_or_None, failure_reason_or_None)
    n8n: 미등록 webhook → 404, 등록 webhook → 200/405
    CC=4
    """
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=BINDING_PROBE_TIMEOUT) as resp:
            return BINDING_STATUS_MATCH, resp.status, None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return BINDING_STATUS_MISMATCH, 404, "WEBHOOK_NOT_REGISTERED"
        # 404 외 HTTPError(405 등) → webhook 존재하나 HEAD 미지원 → MATCH
        return BINDING_STATUS_MATCH, exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return BINDING_STATUS_UNKNOWN, None, f"PROBE_ERROR: {type(exc).__name__}"


def _emit_binding_alert(endpoint_id: str, url: str, reason: str) -> None:
    """
    바인딩 불일치 발생 시 비동기 예외 신호 전파 (Jeni TA 필수).
    BINDING_ALERT_DIR에 알림 파일 기록 → 상위 레이어 감지용.
    CC=2
    """
    BINDING_ALERT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    alert_path = BINDING_ALERT_DIR / f"BINDING_ALERT_{endpoint_id}_{ts}.json"
    alert = {
        "alert_type": "BINDING_MISMATCH",
        "endpoint_id": endpoint_id,
        "url": url,
        "reason": reason,
        "timestamp": _now_kst(),
        "action_required": "비오(Joshua) EAG 승인 후 transport_endpoints.json 갱신",
    }
    try:
        with open(alert_path, "w", encoding="utf-8") as f:
            json.dump(alert, f, ensure_ascii=False, indent=2)
        logger.warning(
            "BINDING_ALERT_EMITTED: endpoint_id=%s url=%s reason=%s",
            endpoint_id, url, reason,
        )
    except OSError as exc:
        logger.error("BINDING_ALERT_WRITE_FAILED: %s", exc)


# ── 메인 검증 진입점 ────────────────────────────────────────────────────────

def check_single_binding(endpoint_id: str) -> EndpointBindingResult:
    """
    단일 endpoint 바인딩 검증.
    MISMATCH 시 alert 자동 전파.
    CC=4
    """
    endpoints_data = _load_endpoints()
    endpoints = endpoints_data.get("endpoints", {})
    checked_at = _now_kst()

    if endpoint_id not in endpoints:
        return EndpointBindingResult(
            endpoint_id=endpoint_id,
            url="",
            active=False,
            binding_status=BINDING_STATUS_UNKNOWN,
            probe_http_status=None,
            failure_reason="ENDPOINT_ID_NOT_FOUND",
            checked_at=checked_at,
        )

    ep = endpoints[endpoint_id]
    url = ep.get("url", "")
    active = ep.get("active", False)

    if not active:
        return EndpointBindingResult(
            endpoint_id=endpoint_id,
            url=url,
            active=False,
            binding_status=BINDING_STATUS_UNKNOWN,
            probe_http_status=None,
            failure_reason="ENDPOINT_INACTIVE",
            checked_at=checked_at,
        )

    binding_status, http_status, failure_reason = _probe_endpoint(url)

    if binding_status == BINDING_STATUS_MISMATCH:
        _emit_binding_alert(endpoint_id, url, failure_reason or "MISMATCH")

    return EndpointBindingResult(
        endpoint_id=endpoint_id,
        url=url,
        active=active,
        binding_status=binding_status,
        probe_http_status=http_status,
        failure_reason=failure_reason,
        checked_at=checked_at,
    )


def validate_all_bindings() -> BindingGuardResult:
    """
    transport_endpoints.json 전체 endpoint 바인딩 검증.
    하나라도 MISMATCH/UNKNOWN 시 all_match=False.
    CC=4
    """
    endpoints_data = _load_endpoints()
    endpoints = endpoints_data.get("endpoints", {})
    checked_at = _now_kst()

    if not endpoints:
        logger.error("BINDING_GUARD: endpoints registry empty or load failed")
        return BindingGuardResult(
            all_match=False,
            results=[],
            blocked_endpoints=[],
            checked_at=checked_at,
        )

    results = []
    blocked = []

    for ep_id in endpoints:
        result = check_single_binding(ep_id)
        results.append(result)
        if result.binding_status != BINDING_STATUS_MATCH:
            blocked.append(ep_id)
            logger.warning(
                "BINDING_BLOCKED: endpoint_id=%s status=%s reason=%s",
                ep_id, result.binding_status, result.failure_reason,
            )

    all_match = len(blocked) == 0
    if all_match:
        logger.info("BINDING_GUARD: ALL MATCH — %d endpoints verified", len(results))

    return BindingGuardResult(
        all_match=all_match,
        results=results,
        blocked_endpoints=blocked,
        checked_at=checked_at,
    )


def is_endpoint_sendable(endpoint_id: str) -> bool:
    """
    transport_client 전송 전 호출 — 전송 허용 여부 반환.
    MATCH만 True. MISMATCH/UNKNOWN → False (fail-closed).
    CC=2
    """
    result = check_single_binding(endpoint_id)
    return result.binding_status == BINDING_STATUS_MATCH


def get_binding_guard_status() -> dict:
    """바인딩 가드 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "binding_guard",
        "layer": "sync_layer/transport",
        "p4_task": "P4-T2",
        "endpoints_path": str(ENDPOINTS_PATH),
        "alert_dir": str(BINDING_ALERT_DIR),
        "probe_timeout_seconds": BINDING_PROBE_TIMEOUT,
        "binding_statuses": [
            BINDING_STATUS_MATCH,
            BINDING_STATUS_MISMATCH,
            BINDING_STATUS_UNKNOWN,
        ],
        "fail_closed": True,
        "jeni_advisory": "MISMATCH 차단 시 비동기 alert 전파 — 데드락 방지",
    }

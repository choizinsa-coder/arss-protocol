"""
transport_validator.py
AIBA Sync Layer — Transport Endpoint Reachability Validator (P3-T5)
SSOT: Domi Phase 3 Design (S171) / EAG-1 Approved (비오(Joshua))

역할:
  - registry/transport_endpoints.json 등록 active endpoint 도달성 확인
  - T1: endpoint URL 형식 유효 (host/port 파싱 가능)
  - T2: TCP connection 가능 여부 (side-effect 없음)
  - T3: timeout 내 응답 존재

판정 기준 (SC-1 해소안 — VPS 실증 기반):
  - PASS: TCP connection 성공 (400/404/405 포함 — 서버 응답 = 도달 확인)
  - FAIL: ConnectionRefusedError (endpoint 명확히 도달 불가)
  - UNKNOWN: TimeoutError / DNS error / OSError (네트워크 상태 불명)

TCP_TIMEOUT: transport_client.py HTTP_TIMEOUT_SECONDS=10 기준 통일

금지:
  - payload 전송
  - side-effect 발생
  - 실제 sync 실행
"""

import json
import logging
import socket
import urllib.parse
from pathlib import Path

logger = logging.getLogger(__name__)

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
ENDPOINTS_PATH = VPS_ROOT / "registry" / "transport_endpoints.json"
TCP_TIMEOUT_SECONDS = 10

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_UNKNOWN = "UNKNOWN"


def validate() -> dict:
    """
    Transport endpoint 도달성 검증 진입점.
    active endpoint 전수 확인.
    반환: {validator, verdict, checked, failed, details[]}
    CC=5
    """
    endpoints_data = _load_endpoints()
    if endpoints_data is None:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"error": "ENDPOINTS_FILE_LOAD_FAILED"}])

    raw_endpoints = endpoints_data.get("endpoints", {})
    if not isinstance(raw_endpoints, dict):
        return _result(VERDICT_UNKNOWN, 0, 0, [{"error": "ENDPOINTS_FORMAT_INVALID"}])

    active = {k: v for k, v in raw_endpoints.items() if v.get("active", False)}
    if not active:
        return _result(VERDICT_UNKNOWN, 0, 0, [{"note": "NO_ACTIVE_ENDPOINTS"}])

    checked = 0
    all_verdicts = []
    details = []

    for name, cfg in active.items():
        checked += 1
        verdict, detail = _check_endpoint(name, cfg.get("url", ""))
        all_verdicts.append(verdict)
        if verdict != VERDICT_PASS:
            details.append(detail)

    if VERDICT_FAIL in all_verdicts:
        overall = VERDICT_FAIL
    elif VERDICT_UNKNOWN in all_verdicts:
        overall = VERDICT_UNKNOWN
    else:
        overall = VERDICT_PASS

    failed = all_verdicts.count(VERDICT_FAIL)
    return _result(overall, checked, failed, details)


def _check_endpoint(name: str, url: str) -> tuple:
    """
    단일 endpoint TCP 도달성 확인.
    T1: URL 형식 / T2: TCP connect / T3: timeout 내 응답
    반환: (verdict, detail_dict)
    CC=5
    """
    # T1: URL 형식 유효성
    host, port = _parse_host_port(url)
    if host is None or port is None:
        return VERDICT_FAIL, {
            "name": name, "url": url, "verdict": VERDICT_FAIL,
            "reason": "T1_INVALID_URL_FORMAT",
        }

    # T2 + T3: TCP connection (side-effect 없음)
    try:
        with socket.create_connection((host, port), timeout=TCP_TIMEOUT_SECONDS):
            pass
        logger.debug("ENDPOINT_REACHABLE: %s (%s:%s)", name, host, port)
        return VERDICT_PASS, {}

    except ConnectionRefusedError:
        return VERDICT_FAIL, {
            "name": name, "url": url, "verdict": VERDICT_FAIL,
            "reason": "T2_CONNECTION_REFUSED",
        }

    except TimeoutError:
        return VERDICT_UNKNOWN, {
            "name": name, "url": url, "verdict": VERDICT_UNKNOWN,
            "reason": "T3_TIMEOUT",
        }

    except (socket.gaierror, OSError) as exc:
        return VERDICT_UNKNOWN, {
            "name": name, "url": url, "verdict": VERDICT_UNKNOWN,
            "reason": f"T2_NETWORK_ERROR: {type(exc).__name__}",
        }


def _parse_host_port(url: str) -> tuple:
    """
    URL에서 host, port 추출.
    port 없으면 scheme 기준 기본값 적용 (http=80, https=443).
    실패 시 (None, None).
    CC=3
    """
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname
        if not host:
            return None, None
        port = parsed.port
        if port is None:
            port = 443 if parsed.scheme == "https" else 80
        return host, port
    except Exception:
        return None, None


def _load_endpoints():
    """endpoints JSON 로드. 실패 시 None. CC=2"""
    try:
        return json.loads(ENDPOINTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("ENDPOINTS_LOAD_FAILED: %s", exc)
        return None


def _result(verdict: str, checked: int, failed: int, details: list) -> dict:
    """결과 딕셔너리 빌드. CC=1"""
    return {
        "validator": "transport",
        "verdict": verdict,
        "checked": checked,
        "failed": failed,
        "details": details,
    }


def get_validator_status() -> dict:
    """Transport Validator 상태 요약 (관측/감사용). CC=1"""
    return {
        "component": "transport_validator",
        "layer": "sync_layer/validator",
        "p3_task": "P3-T5",
        "endpoints_path": str(ENDPOINTS_PATH),
        "tcp_timeout_seconds": TCP_TIMEOUT_SECONDS,
        "reachable_definition": "TCP_CONNECTION_SUCCESS (side-effect-free)",
        "fail_on": "ConnectionRefusedError",
        "unknown_on": "TimeoutError / DNS error / OSError",
    }

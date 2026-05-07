# tools/delta_context/ssot_time_payload_provider.py
# PT-S71-001 — SSOT Time Payload Provider (S95)
# 설계: 도미 FINAL DESIGN / EAG-2 비오(Joshua) 승인
#
# 역할: GET /v1/system/time 호출 → session_time_lock payload 반환
# FORBIDDEN: runtime clock 직접 호출 / fallback 로직 / partial payload 허용
#
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any

PROVIDER_NAME = "ssot_time_payload_provider"
SYSTEM_TIME_URL = "http://127.0.0.1:8000/v1/system/time"
REQUIRED_SOURCE = "AIBA_STATUS_SERVER_CLOCK"
REQUIRED_TIMEZONE = "Asia/Seoul"


def _fetch_system_time() -> dict:
    """GET /v1/system/time 호출. 실패 시 예외 발생."""
    try:
        with urllib.request.urlopen(SYSTEM_TIME_URL, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.URLError as e:
        raise RuntimeError(f"SYSTEM_TIME_ENDPOINT_MISSING: {e}") from e
    except Exception as e:
        raise RuntimeError(f"SYSTEM_TIME_FETCH_ERROR: {e}") from e


def _validate_response(data: dict) -> None:
    """응답 shape 및 계약 필드 검증. 위반 시 예외 발생."""
    # ok 필드
    if not data.get("ok"):
        raise ValueError(
            f"SYSTEM_TIME_ENDPOINT_MISSING: ok=False, error={data.get('error_code', data.get('error', 'unknown'))}"
        )
    # source 검증
    source = data.get("source")
    if source != REQUIRED_SOURCE:
        raise ValueError(
            f"SYSTEM_TIME_SOURCE_MISMATCH: expected={REQUIRED_SOURCE}, got={source}"
        )
    # timezone 검증
    tz = data.get("timezone")
    if tz != REQUIRED_TIMEZONE:
        raise ValueError(
            f"SYSTEM_TIME_TIMEZONE_MISMATCH: expected={REQUIRED_TIMEZONE}, got={tz}"
        )
    # timestamp 존재 및 기본 형식 검증
    timestamp = data.get("timestamp")
    if not timestamp or not isinstance(timestamp, str):
        raise ValueError(
            f"SYSTEM_TIME_INVALID_TIMESTAMP: timestamp missing or not string"
        )
    if "+09:00" not in timestamp and "Z" not in timestamp:
        raise ValueError(
            f"SYSTEM_TIME_INVALID_TIMESTAMP: timezone marker missing in timestamp={timestamp!r}"
        )
    # epoch_ms 검증
    epoch_ms = data.get("epoch_ms")
    if not isinstance(epoch_ms, int) or epoch_ms <= 0:
        raise ValueError(
            f"SYSTEM_TIME_EPOCH_INVALID: epoch_ms={epoch_ms!r}"
        )


def provide(
    session_number: Any = None,
    written_deltas: Any = None,
    generated_at: Any = None,
) -> dict:
    """
    SSOT time payload provider.

    Returns:
        {
            "session_time_lock": {
                "source": "AIBA_STATUS_SERVER_CLOCK",
                "timezone": "Asia/Seoul",
                "generated_at": "<ISO8601 +09:00>",
                "observed_at": "<ISO8601 +09:00>",
                "epoch_ms": <int>
            }
        }

    Raises:
        RuntimeError: endpoint missing / fetch error
        ValueError:   shape mismatch / source mismatch / timezone mismatch /
                      invalid timestamp / invalid epoch_ms
    """
    data = _fetch_system_time()
    _validate_response(data)

    timestamp = data["timestamp"]
    epoch_ms = data["epoch_ms"]

    return {
        "session_time_lock": {
            "source":       REQUIRED_SOURCE,
            "timezone":     REQUIRED_TIMEZONE,
            "generated_at": timestamp,
            "observed_at":  timestamp,
            "epoch_ms":     epoch_ms,
        }
    }


# run_shadow_pipeline ssot_payload_provider 인자용 callable alias
ssot_time_payload_provider = provide

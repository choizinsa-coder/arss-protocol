#!/usr/bin/env python3
"""
model_probe.py v1.0.0
AIBA Model Deprecation Probe Engine
EAG-S363-MODEL-PROBE-IMPL-001

설계: Domi DESIGN (S363) + Caddy IMPLEMENTABLE 보정 + Jeni TRUST_READY.
목적: 제니(8447)/도미(8448) 런타임의 /probe 엔드포인트를 호출하여
      primary/escalate 모델의 실호출 가용성을 점검하고 폐기(DEPRECATED)를 분류한다.

정합 원칙(OI-S361-003): 모델 가용성은 실호출(runtime /probe)로만 확정.
Fail-Safe: 일시장애(TRANSIENT/RATE_LIMITED)·런타임 접근불가(PROBE_UNREACHABLE)는
           폐기로 오판하지 않는다. deprecations()는 status=="DEPRECATED"만 집계.

계약(런타임 /probe 응답):
  { "agent": "jeni"|"domi",
    "results": [
      { "model": "<model id>", "model_type": "primary"|"escalate",
        "http_status": <int>, "body": "<응답 본문 발췌 또는 오류 문자열>" },
      ...
    ] }
분류 로직(classify)은 본 모듈에 단일 소재 → 단위 테스트 용이(G1~G7).
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

JENI_PROBE_URL = "http://127.0.0.1:8447/probe"
DOMI_PROBE_URL = "http://127.0.0.1:8448/probe"
PROBE_HTTP_TIMEOUT = 20

# model-not-found 키워드 (Gemini + DeepSeek 양쪽 커버). 소문자 비교.
_NOT_FOUND_PATTERNS = (
    "not found",
    "not_found",
    "model_not_found",
    "model_not_exist",
    "not exist",
    "does not exist",
    "doesn't exist",
    "not supported",
    "not_supported",
    "unsupported model",
    "invalid model",
    "unknown model",
    "no such model",
    "deprecated",
)

# status 상수
STATUS_OK = "OK"
STATUS_DEPRECATED = "DEPRECATED"
STATUS_TRANSIENT = "TRANSIENT"
STATUS_AUTH_ERROR = "AUTH_ERROR"
STATUS_RATE_LIMITED = "RATE_LIMITED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_PROBE_UNREACHABLE = "PROBE_UNREACHABLE"

# 알림 대상 status (폐기 + 키 이상). RATE_LIMITED/TRANSIENT/OK/PROBE_UNREACHABLE은 미발동.
ALERTING_STATUSES = (STATUS_DEPRECATED, STATUS_AUTH_ERROR)


@dataclass
class ProbeResult:
    agent: str          # "jeni" | "domi"
    model_type: str     # "primary" | "escalate" | "escalate_preview" | "unknown"
    model_name: str
    status: str         # STATUS_* 상수 중 하나
    http_status: int
    reason: str
    probed_at: str      # ISO 8601

    def to_dict(self) -> dict:
        return asdict(self)


def classify(http_status: int, response_body: str = "") -> str:
    """raw (http_status, body) → status.
    400·404+미존재키워드=DEPRECATED / 404기타=TRANSIENT / 400기타=UNKNOWN /
    401·403=AUTH_ERROR / 429=RATE_LIMITED / 2xx=OK / 5xx·0(네트워크/timeout)=TRANSIENT.
    Gemini(404)·DeepSeek(400 'Model Not Exist') 폐기 형식 양쪽 커버."""
    body = (response_body or "").lower()
    try:
        code = int(http_status)
    except (TypeError, ValueError):
        return STATUS_UNKNOWN
    if code in (400, 404):
        if any(p in body for p in _NOT_FOUND_PATTERNS):
            return STATUS_DEPRECATED
        # 404 키워드 없음 = 라우팅 일시장애 / 400 키워드 없음 = 미상 요청오류
        return STATUS_TRANSIENT if code == 404 else STATUS_UNKNOWN
    if code in (401, 403):
        return STATUS_AUTH_ERROR
    if code == 429:
        return STATUS_RATE_LIMITED
    if 200 <= code < 300:
        return STATUS_OK
    if 500 <= code < 600:
        return STATUS_TRANSIENT
    if code == 0:
        # 네트워크 단절/timeout — 폐기로 오판 금지
        return STATUS_TRANSIENT
    return STATUS_UNKNOWN


def _is_preview(model_name: str) -> bool:
    return "preview" in (model_name or "").lower()


class ModelProbeEngine:
    """각 런타임 /probe를 호출하여 ProbeResult 리스트를 산출."""

    def __init__(self, jeni_url: str = JENI_PROBE_URL,
                 domi_url: str = DOMI_PROBE_URL,
                 timeout: int = PROBE_HTTP_TIMEOUT):
        self.jeni_url = jeni_url
        self.domi_url = domi_url
        self.timeout = timeout

    def _fetch_probe(self, url: str):
        """런타임 /probe GET → (ok, payload_dict|None, err|None).
        런타임 접근 불가/오류는 폐기가 아닌 인프라 신호로 처리."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return True, json.loads(r.read().decode("utf-8")), None
        except urllib.error.HTTPError as e:
            return False, None, f"PROBE_ENDPOINT_HTTP_{e.code}"
        except Exception as e:  # URLError/timeout/JSON 등
            return False, None, f"PROBE_UNREACHABLE: {e}"

    def _probe_agent(self, agent: str, url: str) -> list:
        probed_at = datetime.now(timezone.utc).isoformat()
        ok, data, err = self._fetch_probe(url)
        if not ok or not isinstance(data, dict):
            # 런타임 /probe 자체 접근 불가 → PROBE_UNREACHABLE (폐기 아님)
            return [ProbeResult(agent, "unknown", "", STATUS_PROBE_UNREACHABLE,
                                0, err or "no data", probed_at)]
        results = []
        for item in data.get("results", []):
            model_name = str(item.get("model", ""))
            try:
                http_status = int(item.get("http_status", 0))
            except (TypeError, ValueError):
                http_status = 0
            body = str(item.get("body", "") or item.get("error", ""))
            status = classify(http_status, body)
            mtype = str(item.get("model_type", "") or "primary")
            if mtype == "escalate" and _is_preview(model_name):
                mtype = "escalate_preview"
            reason = body[:200] if body else f"http_status={http_status}"
            results.append(ProbeResult(
                agent=agent, model_type=mtype, model_name=model_name,
                status=status, http_status=http_status,
                reason=reason, probed_at=probed_at))
        if not results:
            results.append(ProbeResult(agent, "unknown", "", STATUS_UNKNOWN,
                                       0, "empty results", probed_at))
        return results

    def probe_all(self) -> list:
        out = []
        out.extend(self._probe_agent("jeni", self.jeni_url))
        out.extend(self._probe_agent("domi", self.domi_url))
        return out

    @staticmethod
    def deprecations(results: list) -> list:
        """알림 대상만 반환 (DEPRECATED + AUTH_ERROR). 폐기 오탐 방지 핵심."""
        return [r for r in results if r.status in ALERTING_STATUSES]

    @staticmethod
    def build_alert_detail(alerting: list) -> str:
        """pending_alerts.json WorkItem.detail용 JSON 문자열(F 스키마)."""
        agents_payload = []
        for r in alerting:
            entry = {
                "agent": r.agent,
                "model_name": r.model_name,
                "model_type": r.model_type,
                "http_status": r.http_status,
                "status": r.status,
                "reason": r.reason,
            }
            entry["priority"] = "normal" if r.model_type == "escalate_preview" else "high"
            agents_payload.append(entry)
        detail = {
            "source": "Model_Deprecation",
            "probed_at": alerting[0].probed_at if alerting else
                         datetime.now(timezone.utc).isoformat(),
            "agents": agents_payload,
            "alert_summary": f"{len(alerting)}개 모델 이상 감지 "
                             f"(DEPRECATED/AUTH_ERROR)",
        }
        return json.dumps(detail, ensure_ascii=False, indent=2)

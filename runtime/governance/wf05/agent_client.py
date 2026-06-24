"""
agent_client.py v1.0.0
WF-05 Orchestrator -- Domi/Jeni Runtime Client
EAG: EAG-S285-WF05-ORCHESTRATOR-001

Domi(127.0.0.1:8448) / Jeni(127.0.0.1:8447) /ask 호출.
양 런타임 v1.5.0 / v4.10.0 실측 기반 (동일 인터페이스):
  요청: POST /ask {"prompt", "context", "session", "escalate"}
  응답: {"ok": bool, "text": "...", "rounds_used": N, "audit": {...}}
주소는 IPv6 재발 방지를 위해 127.0.0.1 고정 (S284).
"""
import json
import re
import urllib.request
import urllib.error

DOMI_BASE = "http://127.0.0.1:8448"
JENI_BASE = "http://127.0.0.1:8447"
ASK_TIMEOUT = 125  # 런타임 MAX_TOTAL_SECONDS=120 + 여유


def _ask(base, prompt, context, session, escalate=False):
    body = {"prompt": prompt, "context": context,
            "session": session, "escalate": escalate}
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        base + "/ask", data=raw,
        headers={"Content-Type": "application/json",
                 "Content-Length": str(len(raw))}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=ASK_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")[:300]
        except Exception:
            detail = "<unreadable>"
        return None, "HTTP_" + str(e.code) + ": " + detail
    except Exception as e:
        return None, "AGENT_UNREACHABLE: " + str(e)


def ask_domi(prompt, context, session, escalate=False):
    """도미 설계 요청. 성공 시 text 반환."""
    resp, err = _ask(DOMI_BASE, prompt, context, session, escalate)
    if err:
        return {"ok": False, "error": err}
    return resp


def ask_jeni(prompt, context, session, escalate=False):
    """제니 검증 요청. 성공 시 text 반환."""
    resp, err = _ask(JENI_BASE, prompt, context, session, escalate)
    if err:
        return {"ok": False, "error": err}
    return resp


def parse_jeni_verdict(text):
    """제니 응답 text에서 TRUST_READY 판정 추출.
    반환: TRUST_READY | TRUST_ADVISORY | TRUST_NOT_READY | FAIL | UNKNOWN
    """
    if not text:
        return "UNKNOWN"
    m = re.search(r"TRUST_READY\s*=\s*([A-Z_]+)", text)
    if m:
        return m.group(1)
    return "UNKNOWN"

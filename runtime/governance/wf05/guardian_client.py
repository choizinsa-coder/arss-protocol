"""
guardian_client.py v1.0.0
WF-05 Orchestrator -- Guardian Control Plane Client
EAG: EAG-S285-WF05-ORCHESTRATOR-001

Guardian(127.0.0.1:8450) /authorize /status /veto 호출.
wf05_guardian.py v1.1.0 실측 기반:
  /authorize 요청: {"command": "...", "session": "..."}
  /authorize 응답: {"ok": true, "approval_id": "...", "window_id": "...", "budget_remaining": N}
  실패 시 HTTP 403 + {"ok": false, "error": "..."}
"""
import json
import urllib.request
import urllib.error

GUARDIAN_BASE = "http://127.0.0.1:8450"
GUARDIAN_TIMEOUT = 15


def _post(path, body):
    raw = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        GUARDIAN_BASE + path, data=raw,
        headers={"Content-Type": "application/json",
                 "Content-Length": str(len(raw))}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=GUARDIAN_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        # Guardian 거부는 403 + JSON body 반환
        try:
            return json.loads(e.read().decode("utf-8")), None
        except Exception:
            return None, "GUARDIAN_HTTP_" + str(e.code)
    except Exception as e:
        return None, "GUARDIAN_UNREACHABLE: " + str(e)


def _get(path):
    req = urllib.request.Request(GUARDIAN_BASE + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=GUARDIAN_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8")), None
    except Exception as e:
        return None, "GUARDIAN_GET_FAIL: " + str(e)


def authorize(command, session):
    """Guardian 승인 요청. 성공 시 approval_id 반환."""
    resp, err = _post("/authorize", {"command": command, "session": session})
    if err:
        return {"ok": False, "error": err}
    return resp


def status():
    """Guardian 현재 상태 조회. policy_status / budget_remaining 포함."""
    resp, err = _get("/status")
    if err:
        return {"ok": False, "error": err}
    return resp


def is_paused():
    """Veto 감지: policy_status가 PAUSED면 True."""
    st = status()
    if not st.get("ok"):
        # 상태 조회 실패 시 안전측: 일시정지로 간주(FAIL_CLOSED)
        return True
    return st.get("policy_status") == "PAUSED"

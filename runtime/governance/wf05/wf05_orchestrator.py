"""
wf05_orchestrator.py v1.0.0
WF-05 Caddy-Domi-Jeni Orchestration Loop -- Python 단일 스크립트
EAG: EAG-S285-WF05-ORCHESTRATOR-001

구조: n8n Webhook -> Execute Command -> python3 wf05_orchestrator.py --payload <json>
상태머신: INPUT -> DOMI_DESIGN -> JENI_VERIFY -> (REVISE 루프) ->
            GUARDIAN_AUTHORIZE -> MCP_EXEC_SCOPED -> RESULT

거버넌스 가드레일 (제니 TRUST_READY 3조건):
  1. 승인 우회 불가: approval_id 없으면 즉시 FAIL
  2. 2-of-3 합의: Domi 설계 + Jeni TRUST_READY + Guardian 승인 모두 통과 필수
  3. Veto 즉시 반영: 루프 각 단계 진입 전 Guardian PAUSED 감지 시 즉시 중단

실행 원칙:
  - subprocess.run() 직접 실행 금지
  - 모든 실행은 MCP 8443 exec_scoped 경유
  - exec_scoped는 caddy OAuth 인증 필요 (미확인 영역 -> EXEC_MODE로 분리)
    EXEC_MODE=dry_run: Guardian 승인 + audit까지만 수행, 실제 실행은 SKIP
    EXEC_MODE=live: MCP exec_scoped 실제 호출 (caddy OAuth credentials 필요)
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_wf05 as audit
import guardian_client as guardian
import agent_client as agent

ORCH_VERSION = "1.0.0"
MAX_ROUNDS = 3
EXEC_MODE = os.environ.get("WF05_EXEC_MODE", "dry_run")  # dry_run | live

# MCP bridge (live 모드에서만 사용)
BRIDGE_BASE = "http://127.0.0.1:8443"
BRIDGE_TOKEN_ENDPOINT = BRIDGE_BASE + "/token"
BRIDGE_TIMEOUT = 30
CADDY_CLIENT_ID = os.environ.get("AIBA_CADDY_CLIENT_ID", "")
CADDY_CLIENT_SECRET = os.environ.get("AIBA_CADDY_CLIENT_SECRET", "")


def _check_veto(session):
    """Guardian PAUSED 감지. PAUSED면 즉시 중단 신호 반환."""
    if guardian.is_paused():
        audit.log_stage(session, "VETO", "PAUSED", "Guardian policy PAUSED detected")
        return True
    return False


def _mcp_exec_scoped(command, approval_id, params, session):
    """MCP 8443 exec_scoped 실제 호출 (live 모드 전용).
    caddy OAuth credentials 필요. 인증 실패 시 FAIL.
    """
    if not CADDY_CLIENT_ID or not CADDY_CLIENT_SECRET:
        return {"ok": False, "error": "CADDY_OAUTH_NOT_CONFIGURED"}
    # OAuth 토큰 발급
    import urllib.parse
    tok_body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CADDY_CLIENT_ID,
        "client_secret": CADDY_CLIENT_SECRET,
    }).encode()
    try:
        tok_req = urllib.request.Request(
            BRIDGE_TOKEN_ENDPOINT, data=tok_body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        with urllib.request.urlopen(tok_req, timeout=10) as r:
            token = json.loads(r.read().decode()).get("access_token", "")
    except Exception as e:
        return {"ok": False, "error": "OAUTH_FAIL: " + str(e)}
    if not token:
        return {"ok": False, "error": "OAUTH_NO_TOKEN"}
    # exec_scoped 호출
    call_body = {
        "actor_id": "caddy",
        "approval_id": approval_id,
        "command": command,
        "params": params,
    }
    raw = json.dumps(call_body).encode()
    try:
        req = urllib.request.Request(
            BRIDGE_BASE + "/caddy/exec_scoped", data=raw,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token,
                     "Content-Length": str(len(raw))}, method="POST")
        with urllib.request.urlopen(req, timeout=BRIDGE_TIMEOUT) as r:
            return {"ok": True, "result": json.loads(r.read().decode())}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = "<unreadable>"
        return {"ok": False, "error": "HTTP_" + str(e.code) + ": " + detail}
    except Exception as e:
        return {"ok": False, "error": "EXEC_UNREACHABLE: " + str(e)}


def run_orchestration(payload):
    """메인 오케스트레이션 루프.
    payload: {"task": "...", "context": "...", "session": "S285", "command": "pytest", "params": {...}}
    """
    task = payload.get("task", "")
    context = payload.get("context", "")
    session = payload.get("session", "S000")
    command = payload.get("command", "")
    params = payload.get("params", {})

    audit.log_stage(session, "INPUT", "RECEIVED",
                    "task=" + task[:80], command=command, exec_mode=EXEC_MODE)

    # Veto 선제점검
    if _check_veto(session):
        return {"status": "VETOED", "reason": "Guardian PAUSED", "session": session}

    # 오케스트레이션 루프 (Domi -> Jeni -> REVISE 반복)
    design_text = ""
    verdict = "UNKNOWN"
    rounds = 0

    while rounds < MAX_ROUNDS:
        rounds += 1

        # Veto 각 라운드 재검사
        if _check_veto(session):
            return {"status": "VETOED", "reason": "Guardian PAUSED mid-loop",
                    "session": session, "round": rounds}

        # STEP 1: Domi 설계
        domi_prompt = task if rounds == 1 else (
            task + "\n\n[제니 REVISE 요청 - 이전 설계 재검토]\n" + design_text)
        domi_resp = agent.ask_domi(domi_prompt, context, session)
        if not domi_resp.get("ok"):
            audit.log_stage(session, "DOMI", "FAIL",
                            domi_resp.get("error", ""), round=rounds)
            return {"status": "FAILED", "stage": "DOMI",
                    "error": domi_resp.get("error"), "session": session, "round": rounds}
        design_text = domi_resp.get("text", "")
        audit.log_stage(session, "DOMI", "PASS", "design received", round=rounds)

        # STEP 2: Jeni 검증
        jeni_prompt = ("다음 도미 설계를 검증하십시오. TRUST_READY 판정 형식으로 응답.\n\n" + design_text)
        jeni_resp = agent.ask_jeni(jeni_prompt, context, session)
        if not jeni_resp.get("ok"):
            audit.log_stage(session, "JENI", "FAIL",
                            jeni_resp.get("error", ""), round=rounds)
            return {"status": "FAILED", "stage": "JENI",
                    "error": jeni_resp.get("error"), "session": session, "round": rounds}
        verdict = agent.parse_jeni_verdict(jeni_resp.get("text", ""))
        audit.log_stage(session, "JENI", verdict, "verdict parsed", round=rounds)

        if verdict == "TRUST_READY":
            break
        # TRUST_NOT_READY / TRUST_ADVISORY / UNKNOWN -> 다음 라운드 REVISE

    # MAX_ROUNDS 초과 처리
    if verdict != "TRUST_READY":
        audit.log_stage(session, "ESCALATE", "MAX_ROUNDS_EXCEEDED",
                        "verdict=" + verdict, rounds=rounds)
        return {"status": "ESCALATED", "reason": "MAX_ROUNDS_EXCEEDED",
                "rounds": rounds, "last_verdict": verdict, "session": session,
                "escalation": {"event": "WF05_ESCALATION",
                               "cause": "MAX_ROUNDS_EXCEEDED", "rounds": rounds}}

    # STEP 3: Guardian 승인
    if _check_veto(session):
        return {"status": "VETOED", "reason": "Guardian PAUSED before authorize",
                "session": session}
    auth = guardian.authorize(command, session)
    if not auth.get("ok"):
        audit.log_stage(session, "GUARDIAN", "DENIED",
                        auth.get("error", ""))
        return {"status": "FAILED", "stage": "GUARDIAN",
                "error": auth.get("error"), "session": session}
    approval_id = auth.get("approval_id", "")
    if not approval_id:
        # 승인 우회 불가 가드레일: approval_id 없으면 즉시 FAIL
        audit.log_stage(session, "GUARDIAN", "FAIL", "no approval_id")
        return {"status": "FAILED", "stage": "GUARDIAN",
                "error": "APPROVAL_REQUIRED", "session": session}
    audit.log_stage(session, "GUARDIAN", "APPROVED",
                    "approval_id=" + approval_id,
                    budget_remaining=auth.get("budget_remaining"))

    # STEP 4: MCP exec_scoped 실행
    if EXEC_MODE == "dry_run":
        audit.log_stage(session, "EXEC", "DRY_RUN_SKIP",
                        "command=" + command + " approval_id=" + approval_id)
        return {"status": "DRY_RUN_COMPLETE", "approval_id": approval_id,
                "command": command, "params": params,
                "budget_remaining": auth.get("budget_remaining"),
                "rounds": rounds, "session": session,
                "note": "EXEC_MODE=dry_run -- exec_scoped 실제 호출 SKIP. live 모드로 전환 시 실행."}

    # live 모드
    exec_result = _mcp_exec_scoped(command, approval_id, params, session)
    if not exec_result.get("ok"):
        audit.log_stage(session, "EXEC", "FAIL", exec_result.get("error", ""))
        return {"status": "FAILED", "stage": "EXEC",
                "error": exec_result.get("error"),
                "approval_id": approval_id, "session": session}
    audit.log_stage(session, "EXEC", "PASS", "command=" + command)
    audit.log_stage(session, "RESULT", "COMPLETE", "approval_id=" + approval_id)
    return {"status": "COMPLETE", "approval_id": approval_id,
            "command": command, "result": exec_result.get("result"),
            "rounds": rounds, "session": session}


def load_input():
    """--payload <json> 또는 stdin으로 payload 수신."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=str, default="")
    args = parser.parse_args()
    if args.payload:
        return json.loads(args.payload)
    data = sys.stdin.read()
    if data.strip():
        return json.loads(data)
    return {}


def main():
    payload = load_input()
    if not payload:
        print(json.dumps({"status": "FAILED", "error": "NO_PAYLOAD"}))
        return
    result = run_orchestration(payload)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

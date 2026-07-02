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
import time as _time_mod
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import audit_wf05 as audit
import guardian_client as guardian
import agent_client as agent
import ollama_classifier

ORCH_VERSION = "1.9.1"
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
    # MCP JSON-RPC exec_scoped 호출 (POST /mcp) -- EAG-S300-ORCH-FIX-001
    # S300 수정: /caddy/exec_scoped(bridge 미존재) -> /mcp JSON-RPC tools/call
    import uuid as _uuid
    call_body = {
        "jsonrpc": "2.0",
        "id": str(_uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": "exec_scoped",
            "arguments": {
                "actor_id": "caddy",
                "approval_id": approval_id,
                "command": command,
                "params": params,
            },
        },
    }
    raw = json.dumps(call_body).encode()
    try:
        req = urllib.request.Request(
            BRIDGE_BASE + "/mcp", data=raw,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + token,
                     "Content-Length": str(len(raw))}, method="POST")
        with urllib.request.urlopen(req, timeout=BRIDGE_TIMEOUT) as r:
            resp = json.loads(r.read().decode())
            # MCP 응답: {"jsonrpc":"2.0","result":{"isError":bool,"content":[{"type":"text","text":"..."}]}}
            mcp_result = resp.get("result", {})
            if mcp_result.get("isError"):
                content_text = ""
                try:
                    content_text = mcp_result["content"][0]["text"]
                except Exception:
                    pass
                return {"ok": False, "error": "MCP_EXEC_ERROR: " + content_text}
            content_text = ""
            try:
                content_text = mcp_result["content"][0]["text"]
                exec_result = json.loads(content_text)
            except Exception:
                exec_result = {"raw": content_text}
            return {"ok": True, "result": exec_result}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = "<unreadable>"
        return {"ok": False, "error": "HTTP_" + str(e.code) + ": " + detail}
    except Exception as e:
        return {"ok": False, "error": "EXEC_UNREACHABLE: " + str(e)}


def _build_vps_path_context(base_session):
    """OI-S301-001: Domi 호출 전 VPS 확정 경로 가이드 주입.
    경로 미명시 -> 추측 탐색 -> DENY 403 x2 -> CIRCUIT_BREAKER 패턴 원천 차단.
    EAG-S302-WF05-PATHFIX-001.
    """
    r = "/opt/arss/engine/arss-protocol"
    return (
        "[VPS \ud30c\uc77c \uacbd\ub85c \uac00\uc774\ub4dc - \uacbd\ub85c \ucd94\uce21 \uae08\uc9c0, \uc544\ub798 \uacbd\ub85c\ub9cc \uc0ac\uc6a9]\n"
        f"WF-05 orchestrator : {r}/runtime/governance/wf05/wf05_orchestrator.py\n"
        f"WF-05 agent_client : {r}/runtime/governance/wf05/agent_client.py\n"
        f"WF-05 guardian     : {r}/runtime/governance/wf05/guardian_client.py\n"
        f"MCP Bridge         : {r}/tools/mcp/mcp_http_bridge.py\n"
        f"ROOL observation   : {r}/tools/mcp/rool_observation.py\n"
        f"Domi runtime       : {r}/tools/domi_runtime/aiba_domi_runtime.py\n"
        f"Session pointer    : {r}/SESSION_CONTEXT_POINTER.json\n\n"
        "[OI-S305-001 서비스 관찰 주의사항]\n"
        "서비스명은 하이픈 표기: aiba-mcp-bridge / aiba-jeni-runtime / aiba-domi-runtime / aiba-exec-runtime\n"
        "-> 파일 경로 아님. read_file 시도 불가.\n"
        "/health 는 HTTP 엔드포인트(포트 8443/8447/8448/8449), 파일 아님.\n"
        "-> read_file('/health') 시도 금지.\n"
        "서비스 상태 확인은 check_service_state 툴만 사용.\n\n"
        "\u26a0 SESSION_CONTEXT_S{n}_FINAL.json\uc740 SESSION CLOSE \ud6c4 \uc0dd\uc131\ub428. "
        "WF-05 \uc2e4\ud589 \uc911 read_file \uc2dc\ub3c4 \uae08\uc9c0. "
        "\uc138\uc158 \ucee8\ud14d\uc2a4\ud2b8\ub294 Domi \ub7f0\ud0c0\uc784\uc774 \uc790\ub3d9 \uc8fc\uc785 \uc644\ub8cc.\n"
        f"\ud604\uc7ac WF-05 \uc0ac\uc774\ud074 \uc138\uc158: {base_session}"
    )


def run_orchestration(payload, max_rounds=None):
    """메인 오케스트레이션 루프.
    payload: {"task": "...", "context": "...", "session": "S285", "command": "pytest", "params": {...}}
    """
    task = payload.get("task", "")
    context = payload.get("context", "")
    base_session = payload.get("session", "S000")
    # Nesting 방지: -Cy 접미사 이미 있으면 원본만 추출 (제니 TRUST-ADVISORY S301)
    if "-Cy" in base_session:
        base_session = base_session.split("-Cy")[0]
    # cycle별 고유 session ID (OI-S300-001: Persistent Memory 오염 차단)
    session = base_session + "-Cy" + str(int(_time_mod.time()))
    command = payload.get("command", "")
    params = payload.get("params", {})

    audit.log_stage(session, "INPUT", "RECEIVED",
                    "task=" + task[:80], command=command, exec_mode=EXEC_MODE)

    # OI-S301-001: VPS 경로 가이드 주입 (EAG-S302-WF05-PATHFIX-001)
    vps_path_guide = _build_vps_path_context(base_session)
    enriched_context = (
        (vps_path_guide + "\n\n" + context).strip() if context else vps_path_guide
    )

    # Veto 선제점검
    if _check_veto(session):
        return {"status": "VETOED", "reason": "Guardian PAUSED", "session": session}

    # 오케스트레이션 루프 (Domi -> Jeni -> REVISE 반복)
    design_text = ""
    verdict = "UNKNOWN"
    jeni_feedback = ""
    rounds = 0

    while rounds < MAX_ROUNDS:
        rounds += 1

        # Veto 각 라운드 재검사
        if _check_veto(session):
            return {"status": "VETOED", "reason": "Guardian PAUSED mid-loop",
                    "session": session, "round": rounds}

        # STEP 1: Domi 설계
        if rounds == 1:
            domi_prompt = task
        else:
            domi_prompt = (
                task + "\n\n[제니 REVISE 요청 - 이전 설계 재검토]\n" + design_text
                + (("\n\n[제니 판정 피드백]\n" + jeni_feedback) if jeni_feedback else ""))
        domi_resp = agent.ask_domi(domi_prompt, enriched_context, session, max_rounds=max_rounds)
        if not domi_resp.get("ok"):
            domi_error = domi_resp.get("error", "")
            if domi_error == "DESIGN_PARSE_FAILURE":
                # Layer 2 (EAG-S305-DOMI-RETRY-001): OpenAI API 실패 -> escalate 1회 재시도
                audit.log_stage(session, "DOMI_ESCALATE", "RETRY",
                                "DESIGN_PARSE_FAILURE -> escalate=True", round=rounds)
                domi_resp = agent.ask_domi(domi_prompt, enriched_context, session, escalate=True, max_rounds=max_rounds)
                if not domi_resp.get("ok"):
                    audit.log_stage(session, "DOMI_ESCALATE", "FAIL",
                                    domi_resp.get("error", ""), round=rounds)
                    return {"status": "FAILED", "stage": "DOMI_ESCALATE",
                            "error": domi_resp.get("error"), "session": session, "round": rounds}
                audit.log_stage(session, "DOMI_ESCALATE", "PASS", "escalate succeeded", round=rounds)
            else:
                audit.log_stage(session, "DOMI", "FAIL",
                                domi_error, round=rounds)
                return {"status": "FAILED", "stage": "DOMI",
                        "error": domi_error, "session": session, "round": rounds}
        design_text = domi_resp.get("text", "")
        audit.log_stage(session, "DOMI", "PASS", "design received", round=rounds)

        # STEP 2: Jeni 검증
        jeni_prompt = ("다음 도미 설계를 검증하십시오. TRUST_READY 판정 형식으로 응답.\n\n" + design_text)
        jeni_resp = agent.ask_jeni(jeni_prompt, context, session)
        if not jeni_resp.get("ok"):
            jeni_error = jeni_resp.get("error", "")
            if jeni_error == "VALIDATION_PARSE_FAILURE":
                # OI-S302-001: Gemini API 실패(503/429) -> gemini-2.5-pro escalate 1회 재시도
                audit.log_stage(session, "JENI_ESCALATE", "RETRY",
                                "VALIDATION_PARSE_FAILURE -> escalate=True", round=rounds)
                jeni_resp = agent.ask_jeni(jeni_prompt, context, session, escalate=True)
                if not jeni_resp.get("ok"):
                    audit.log_stage(session, "JENI_ESCALATE", "FAIL",
                                    jeni_resp.get("error", ""), round=rounds)
                    return {"status": "FAILED", "stage": "JENI_ESCALATE",
                            "error": jeni_resp.get("error"),
                            "session": session, "round": rounds}
                audit.log_stage(session, "JENI_ESCALATE", "PASS",
                                "escalate succeeded", round=rounds)
            else:
                audit.log_stage(session, "JENI", "FAIL", jeni_error, round=rounds)
                return {"status": "FAILED", "stage": "JENI",
                        "error": jeni_error, "session": session, "round": rounds}
        verdict = agent.parse_jeni_verdict(jeni_resp.get("text", ""))
        audit.log_stage(session, "JENI", verdict, "verdict parsed", round=rounds)

        if verdict == "TRUST_READY":
            break
        jeni_feedback = jeni_resp.get("text", "")
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


def run_cycle_with_retry(payload, max_rounds=None):
    """Layer 3 (EAG-S305-DOMI-RETRY-L3-001): 외부 API 계열 실패 시 cycle 1회 재시도.
    DOMI_ESCALATE/JENI_ESCALATE(Layer 1·2 소진) 실패만 대상. budget>=1 확인 후 재시도.
    재시도는 run_orchestration 재호출로 새 -Cy epoch 자동 부여(OI-S300 오염 방지).
    Guardian DENIED/EXEC/MAX_ROUNDS/VETO/Logic은 제외(복구 불가 반복 차단).
    """
    result = run_orchestration(payload, max_rounds=max_rounds)
    if (result.get("status") == "FAILED"
            and result.get("stage") in ("DOMI_ESCALATE", "JENI_ESCALATE")):
        st = guardian.status()
        if st.get("ok") and st.get("budget_remaining", 0) >= 1:
            audit.log_stage(result.get("session", "S000"), "CYCLE_RETRY", "RETRY",
                            "stage=" + str(result.get("stage"))
                            + " budget=" + str(st.get("budget_remaining")))
            result = run_orchestration(payload, max_rounds=max_rounds)
    return result




def _write_fallback_log(session, category, status, stage, result):
    """caddy_errors.jsonl 에 WF-05 최종 실패 기록.
    EAG-S310-WF05-FALLBACK-001.
    Jeni TRUST-ADVISORY: 로깅 실패가 오케스트레이터 크래시로 전이 금지.
    """
    import datetime as _dt
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(_this_dir)))
    log_path = os.path.join(repo_root, "tools", "caddy_error_log", "caddy_errors.jsonl")
    error_str = result.get("error", result.get("reason", ""))
    entry = {
        "timestamp": _dt.datetime.utcnow().isoformat() + "+00:00",
        "session": session,
        "error_id": "WF05-" + session + "-" + status,
        "category": category,
        "description": "WF-05 최종 실패: status=" + status + " stage=" + stage,
        "root_cause": error_str,
        "beo_burden": "",
        "resolution": "",
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False))
            f.write(chr(10))
    except Exception:
        pass  # 로깅 실패 무음 처리 — 오케스트레이터 크래시 전이 차단


def fallback_router(result):
    """Layer 4: WF-05 최종 실패 후 Fallback Router.
    EAG-S310-WF05-FALLBACK-001.
    run_cycle_with_retry() 결과를 받아 실패 유형별 분류 후 기록.
    exec_scoped / AI 호출 없음 (예산 소비 0).
    CATEGORY:
      WF05-GOVERNANCE : VETOED / GUARDIAN DENIED / CADDY_OAUTH_NOT_CONFIGURED
      WF05-LOGICAL    : MAX_ROUNDS_EXCEEDED / ESCALATED
      WF05-INFRA      : 외부 API 실패 / 통신 오류 (기본값)
    성공(COMPLETE / DRY_RUN_COMPLETE)은 그대로 통과.
    """
    status = result.get("status", "")
    stage = result.get("stage", "")
    error_str = result.get("error", result.get("reason", ""))

    # SUCCESS passthrough — 변경 없이 그대로 반환
    if status in ("COMPLETE", "DRY_RUN_COMPLETE"):
        return result

    # 실패 분류
    if status == "VETOED":
        failure_type = "GOVERNANCE_FAILURE"
    elif stage == "GUARDIAN":
        failure_type = "GOVERNANCE_FAILURE"
    elif stage == "EXEC" and "OAUTH" in error_str:
        failure_type = "GOVERNANCE_FAILURE"
    elif status == "ESCALATED":
        failure_type = "LOGICAL_FAILURE"
    else:
        # INFRA: DOMI_ESCALATE / JENI_ESCALATE / DOMI / JENI / EXEC(통신) 전부 포함
        failure_type = "INFRA_FAILURE"

    _category_map = {
        "GOVERNANCE_FAILURE": "WF05-GOVERNANCE",
        "LOGICAL_FAILURE":    "WF05-LOGICAL",
        "INFRA_FAILURE":      "WF05-INFRA",
    }
    category = _category_map[failure_type]
    session = result.get("session", "S000")

    # audit 기록
    audit.log_stage(session, "FALLBACK_ROUTER", failure_type,
                    "stage=" + stage + " status=" + status)

    # caddy_errors.jsonl 기록 (예외처리 가드레일 내부)
    _write_fallback_log(session, category, status, stage, result)

    # 결과에 fallback_category 추가 후 반환
    result["fallback_category"] = failure_type
    return result

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
    # Ollama 분류레이어 (S315 Step 3 - EAG-S315-OLLAMA-STEP3-001)
    task = payload.get('task', '')
    classify = ollama_classifier.classify_task(task)
    if classify.get('verdict') == 'SIMPLE' and classify.get('ok'):
        session = payload.get('session', 'S000')
        audit.log_stage(session, 'OLLAMA_CLASSIFY', 'SIMPLE', 'phi4-mini direct')
        print(json.dumps({'status': 'COMPLETE_VIA_OLLAMA',
                          'response': classify.get('raw', ''),
                          'model': 'phi4-mini',
                          'session': session}, ensure_ascii=False))
        return

    # ROUNDS-SCALE-01 WF-05 연동 (EAG-S319-ROUNDS-WF05-001)
    max_rounds_for_domi = payload.get('max_rounds', None)
    if max_rounds_for_domi is None:
        if classify.get('ok') and classify.get('verdict') == 'COMPLEX':
            max_rounds_for_domi = 12  # 확인된 복잡 태스트 -> 툴 라운드 상향
    result = run_cycle_with_retry(payload, max_rounds=max_rounds_for_domi)
    result = fallback_router(result)  # Layer 4: Fallback Router (EAG-S310-WF05-FALLBACK-001)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

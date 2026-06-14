"""
autoroute_caller.py
AutoRouter 캐디 세션 측 호출 래퍼 (단일 진입점) + 가드 B-2/B-3
EAG: EAG-S244-DEP-G2-003-001
Version: 1.0.0

가드:
  B-3: 세션당 최대 3회 (success+error 합산)
  B-2: error 누적 2회 → 차단 + AutoRouter deactivate
  모든 호출 AUTO_ROUTE WORM 기록
  카운터: SSOT 격리 전용 경로 (BOOT/CLOSE/context_hash 미참조)
"""

import json
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# 상수
VPS_ROOT      = Path("/opt/arss/engine/arss-protocol")
SECRETS_PATH  = "/etc/aiba/secrets.env"
WEBHOOK_URL   = "http://127.0.0.1:5678/webhook/DEP-G2-002-AutoRouter"
N8N_API_BASE  = "http://127.0.0.1:5678/api/v1"
WF_ID         = "LzApNQOOl6hqGtOM"
RUNTIME_DIR   = VPS_ROOT / "tools" / "autoroute" / "runtime"
APPEND_AUTO_ROUTE = VPS_ROOT / "tools" / "journal" / "append_auto_route.py"
APPEND_INCIDENT   = VPS_ROOT / "tools" / "journal" / "append_incident.py"

MAX_CALLS_PER_SESSION = 3   # B-3
MAX_ERRORS            = 2   # B-2
CALL_TIMEOUT          = 35  # webhook 자체 timeout(제니 30s) + 여유

SCHEMA = "autoroute_counter_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def load_api_key() -> str:
    with open(SECRETS_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("N8N_API_KEY=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    raise ValueError("N8N_API_KEY not found")


def counter_path(session: int) -> Path:
    return RUNTIME_DIR / f"autoroute_counter_S{session}.json"


def load_counter(session: int) -> dict:
    p = counter_path(session)
    if not p.exists():
        return {"session_id": f"S{session}", "success_count": 0, "error_count": 0, "schema": SCHEMA}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_counter(session: int, counter: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with open(counter_path(session), "w", encoding="utf-8") as f:
        json.dump(counter, f, ensure_ascii=False, indent=2)


def record_auto_route(session: int, route_id: str, prompt_summary: str, jeni_ok: bool, error_occurred: bool) -> bool:
    """AUTO_ROUTE WORM 기록. 실패 시 False (호출측 HARD STOP 판단)."""
    summary = prompt_summary[:80]
    r = subprocess.run(
        ["python3", str(APPEND_AUTO_ROUTE),
         "--session", str(session), "--route-id", route_id,
         "--prompt-summary", summary,
         "--jeni-ok", "true" if jeni_ok else "false",
         "--error-occurred", "true" if error_occurred else "false"],
        capture_output=True, text=True, cwd=str(VPS_ROOT)
    )
    print(r.stdout, end="")
    if r.returncode != 0:
        print(f"[WORM-FAIL] {r.stderr}", file=sys.stderr)
        return False
    return True


def record_incident(session: int, incident_id: str, itype: str, desc: str) -> None:
    subprocess.run(
        ["python3", str(APPEND_INCIDENT),
         "--session", str(session), "--incident-id", incident_id,
         "--type", itype, "--description", desc],
        capture_output=True, text=True, cwd=str(VPS_ROOT)
    )


def deactivate_autorouter(key: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{N8N_API_BASE}/workflows/{WF_ID}/deactivate",
            data=b"", headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        return not result.get("active", True)
    except Exception as e:
        print(f"[DEACTIVATE-FAIL] {e}", file=sys.stderr)
        return False


def route(session: int, prompt: str, context: str = "", route_seq: int = 1) -> dict:
    """
    단일 호출 진입점.
    Returns: {status, detail, counter}
    status: OK | BLOCKED_MAX_CALLS | ERROR | DEACTIVATED | WORM_HARD_STOP
    """
    counter = load_counter(session)
    total = counter["success_count"] + counter["error_count"]
    route_id = f"AR-S{session}-{route_seq:03d}"

    # ── 가드 B-3: 3회 초과 사전 차단 ──
    if total >= MAX_CALLS_PER_SESSION:
        return {"status": "BLOCKED_MAX_CALLS", "detail": f"session calls {total} >= {MAX_CALLS_PER_SESSION}", "counter": counter}

    # ── 호출 실행 ──
    jeni_ok = False
    error_occurred = False
    detail = ""
    try:
        body = json.dumps({"prompt": prompt, "context": context}).encode()
        req = urllib.request.Request(WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
            rb = resp.read().decode()
            if resp.status == 200 and rb:
                try:
                    parsed = json.loads(rb)
                    jeni_ok = bool(parsed.get("ok", False))
                    detail = parsed.get("text", "")[:120]
                except json.JSONDecodeError:
                    jeni_ok = False
                    detail = "non-json response"
            else:
                detail = f"HTTP {resp.status} len={len(rb)}"
    except Exception as e:
        error_occurred = True
        detail = f"exception: {e}"

    if not jeni_ok:
        error_occurred = True

    # ── 카운터 갱신 ──
    if jeni_ok and not error_occurred:
        counter["success_count"] += 1
    else:
        counter["error_count"] += 1
    save_counter(session, counter)

    # ── AUTO_ROUTE WORM 기록 (실패 시 HARD STOP) ──
    worm_ok = record_auto_route(session, route_id, prompt, jeni_ok, error_occurred)
    if not worm_ok:
        record_incident(session, f"INC-S{session}-AR-WORM", "AUTOROUTE_WORM_FAIL",
                         f"AUTO_ROUTE WORM 기록 실패 route_id={route_id}. fail-closed 라우팅 중단.")
        key = load_api_key()
        deactivate_autorouter(key)
        return {"status": "WORM_HARD_STOP", "detail": "WORM record failed → deactivated", "counter": counter}

    # ── 가드 B-2: error 누적 2회 → deactivate ──
    if counter["error_count"] >= MAX_ERRORS:
        key = load_api_key()
        deact = deactivate_autorouter(key)
        record_incident(session, f"INC-S{session}-AR-B2", "AUTOROUTE_ERROR_LIMIT",
                         f"error_count={counter['error_count']} ≥ {MAX_ERRORS}. AutoRouter deactivate={deact}. 재활성화는 비오님 EAG.")
        return {"status": "DEACTIVATED", "detail": f"error limit reached, deactivated={deact}", "counter": counter}

    if error_occurred:
        return {"status": "ERROR", "detail": detail, "counter": counter}
    return {"status": "OK", "detail": detail, "counter": counter}



# ──────────────────────────────────────────────
# BidirRouter 확장 — EAG-S247-G2-BIDIR-002
# ──────────────────────────────────────────────

BIDIR_WEBHOOK_URL = "http://127.0.0.1:5678/webhook/DEP-G2-003-BidirRouter"
BIDIR_WF_ID       = "dq7ub7AVYZULm3c1"


def bidir_counter_path(session: int) -> Path:
    return RUNTIME_DIR / f"autoroute_bidir_counter_S{session}.json"


def load_bidir_counter(session: int) -> dict:
    p = bidir_counter_path(session)
    if not p.exists():
        return {"session_id": f"S{session}", "success_count": 0, "error_count": 0, "schema": SCHEMA}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_bidir_counter(session: int, counter: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with open(bidir_counter_path(session), "w", encoding="utf-8") as f:
        json.dump(counter, f, ensure_ascii=False, indent=2)


def deactivate_bidir(key: str) -> bool:
    """BidirRouter WF 비활성화 (BIDIR_WF_ID 대상)."""
    try:
        req = urllib.request.Request(
            f"{N8N_API_BASE}/workflows/{BIDIR_WF_ID}/deactivate",
            data=b"", headers={"X-N8N-API-KEY": key, "Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        return not result.get("active", True)
    except Exception as e:
        print(f"[BIDIR-DEACTIVATE-FAIL] {e}", file=sys.stderr)
        return False


def route_bidir(session: int, prompt: str, context: str = "", route_seq: int = 1) -> dict:
    """
    BidirRouter 호출 래퍼 (제니→도미→제니 2단계).
    Returns: {status, detail, stage, redesigned, counter}
    status: OK | BLOCKED_MAX_CALLS | ERROR | DEACTIVATED | WORM_HARD_STOP
    """
    counter = load_bidir_counter(session)
    total = counter["success_count"] + counter["error_count"]
    route_id = f"BR-S{session}-{route_seq:03d}"

    # ── 가드 B-3: 3회 초과 사전 차단 ──
    if total >= MAX_CALLS_PER_SESSION:
        return {"status": "BLOCKED_MAX_CALLS", "detail": f"session calls {total} >= {MAX_CALLS_PER_SESSION}",
                "stage": None, "redesigned": None, "counter": counter}

    # ── 호출 실행 ──
    jeni_ok = False
    error_occurred = False
    detail = ""
    stage = None
    redesigned = None
    try:
        body = json.dumps({"prompt": prompt, "context": context, "session_id": str(session)}).encode()
        req = urllib.request.Request(BIDIR_WEBHOOK_URL, data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
            rb = resp.read().decode()
            if resp.status == 200 and rb:
                try:
                    parsed = json.loads(rb)
                    jeni_ok = bool(parsed.get("ok", False))
                    detail = parsed.get("text", "")[:120]
                    stage = parsed.get("stage")
                    redesigned = parsed.get("redesigned")
                except json.JSONDecodeError:
                    jeni_ok = False
                    detail = "non-json response"
            else:
                detail = f"HTTP {resp.status} len={len(rb)}"
    except Exception as e:
        error_occurred = True
        detail = f"exception: {e}"

    if not jeni_ok:
        error_occurred = True

    # ── 카운터 갱신 ──
    if jeni_ok and not error_occurred:
        counter["success_count"] += 1
    else:
        counter["error_count"] += 1
    save_bidir_counter(session, counter)

    # ── AUTO_ROUTE WORM 기록 (stage 정보를 prompt_summary에 포함) ──
    stage_info = f"[stage={stage},redesigned={redesigned}]"
    prompt_with_stage = f"{prompt[:60]} {stage_info}"
    worm_ok = record_auto_route(session, route_id, prompt_with_stage, jeni_ok, error_occurred)
    if not worm_ok:
        record_incident(session, f"INC-S{session}-BR-WORM", "BIDIRROUTE_WORM_FAIL",
                        f"BIDIR_ROUTE WORM 기록 실패 route_id={route_id}. fail-closed 라우팅 중단.")
        key = load_api_key()
        deactivate_bidir(key)
        return {"status": "WORM_HARD_STOP", "detail": "WORM record failed → deactivated",
                "stage": stage, "redesigned": redesigned, "counter": counter}

    # ── 가드 B-2: error 누적 2회 → deactivate ──
    if counter["error_count"] >= MAX_ERRORS:
        key = load_api_key()
        deact = deactivate_bidir(key)
        record_incident(session, f"INC-S{session}-BR-B2", "BIDIRROUTE_ERROR_LIMIT",
                        f"error_count={counter['error_count']} >= {MAX_ERRORS}. BidirRouter deactivate={deact}. 재활성화는 비오님 EAG.")
        return {"status": "DEACTIVATED", "detail": f"error limit reached, deactivated={deact}",
                "stage": stage, "redesigned": redesigned, "counter": counter}

    if error_occurred:
        return {"status": "ERROR", "detail": detail, "stage": stage, "redesigned": redesigned, "counter": counter}
    return {"status": "OK", "detail": detail, "stage": stage, "redesigned": redesigned, "counter": counter}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AutoRouter caller wrapper")
    ap.add_argument("--session", type=int, required=True)
    ap.add_argument("--prompt", type=str, required=True)
    ap.add_argument("--context", type=str, default="")
    ap.add_argument("--seq", type=int, default=1)
    a = ap.parse_args()
    result = route(a.session, a.prompt, a.context, a.seq)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] in ("OK",) else 1)

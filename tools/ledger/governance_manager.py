"""
governance_manager.py
AIBA EAG-3 Governance Manager — EAG-S209-EAG3-001
Constitution 제4조(불변 장부) · 제5조(독립 관측) 구현
상태 전환: AUDIT → READY_FOR_ENFORCE → ENFORCE → FAIL_CLOSED
"""
from __future__ import annotations
import json, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
OBSERVATION_DIR = Path(ARSS_ROOT) / "observation"
EAG3_STATE_PATH = OBSERVATION_DIR / "eag3_state.json"
FAIL_CLOSED_FLAG = OBSERVATION_DIR / "fail_closed.flag"
OBS_LOG_PATH     = OBSERVATION_DIR / "observation_log.jsonl"
KST = timezone(timedelta(hours=9))

CLEAN_SESSION_THRESHOLD = 3

def _now_iso():
    return datetime.now(KST).isoformat()

def _append_obs(path: Path, record: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

# ── eag3_state 관리 ──────────────────────────────────────────────────────────

_DEFAULT_STATE = {
    "mode": "audit",
    "consecutive_clean_sessions": 0,
    "enforce_ready": False,
    "last_verified_session": None,
    "enforced_at": None,
}

def load_eag3_state() -> dict:
    """eag3_state.json 로드. 미존재 시 초기값 자동 생성."""
    if not EAG3_STATE_PATH.exists():
        save_eag3_state(_DEFAULT_STATE.copy())
        return _DEFAULT_STATE.copy()
    try:
        with open(EAG3_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        save_eag3_state(_DEFAULT_STATE.copy())
        return _DEFAULT_STATE.copy()

def save_eag3_state(state: dict):
    EAG3_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EAG3_STATE_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, EAG3_STATE_PATH)

# ── fail_closed.flag 관리 ────────────────────────────────────────────────────

def is_fail_closed() -> bool:
    """fail_closed.flag 존재 여부. 미존재 시 False 폴백."""
    return Path(FAIL_CLOSED_FLAG).exists()

def _set_fail_closed():
    FAIL_CLOSED_FLAG.parent.mkdir(parents=True, exist_ok=True)
    FAIL_CLOSED_FLAG.touch()

def _clear_fail_closed():
    if FAIL_CLOSED_FLAG.exists():
        FAIL_CLOSED_FLAG.unlink()

# ── 세션 검증 결과 반영 ──────────────────────────────────────────────────────

def record_session_verification(session: str, passed: bool) -> dict:
    """
    세션 종료 시 검증 결과를 eag3_state에 반영.
    PASS → consecutive_clean_sessions +1 (3 달성 시 enforce_ready=True)
    FAIL → count=0 리셋 + fail_closed.flag 생성
    """
    state = load_eag3_state()
    if passed:
        state["consecutive_clean_sessions"] += 1
        state["last_verified_session"] = session
        if state["consecutive_clean_sessions"] >= CLEAN_SESSION_THRESHOLD:
            state["enforce_ready"] = True
        save_eag3_state(state)
        _append_obs(OBS_LOG_PATH, {
            "obs_type": "SESSION_VERIFICATION",
            "session": session,
            "status": "PASS",
            "consecutive_clean_sessions": state["consecutive_clean_sessions"],
            "enforce_ready": state["enforce_ready"],
            "timestamp": _now_iso(),
        })
        return {"ok": True, "status": "PASS",
                "consecutive_clean_sessions": state["consecutive_clean_sessions"],
                "enforce_ready": state["enforce_ready"]}
    else:
        state["consecutive_clean_sessions"] = 0
        state["enforce_ready"] = False
        state["last_verified_session"] = session
        save_eag3_state(state)
        _set_fail_closed()
        _append_obs(OBS_LOG_PATH, {
            "obs_type": "SESSION_VERIFICATION",
            "session": session,
            "status": "FAIL",
            "consecutive_clean_sessions": 0,
            "enforce_ready": False,
            "fail_closed_activated": True,
            "timestamp": _now_iso(),
        })
        return {"ok": True, "status": "FAIL",
                "consecutive_clean_sessions": 0,
                "fail_closed_activated": True}

# ── ENFORCE 활성화 ───────────────────────────────────────────────────────────

def release_enforce(beo_token: str, approval_id: str, session: str) -> dict:
    """
    READY_FOR_ENFORCE → ENFORCE 전환.
    S209: approval_id 존재 여부로 Beo 승인 검증 (S210에서 토큰 저장소 강화 예정).
    조건 5개 모두 충족 시에만 전환.
    """
    # 조건 1: approval_id 존재
    if not approval_id or not approval_id.strip():
        return {"ok": False, "error": "APPROVAL_ID_MISSING"}
    # 조건 2: beo_token 존재 (S209 간소화 검증)
    if not beo_token or not beo_token.strip():
        return {"ok": False, "error": "BEO_TOKEN_MISSING"}

    state = load_eag3_state()

    # 조건 3: consecutive_clean_sessions >= 3
    if state["consecutive_clean_sessions"] < CLEAN_SESSION_THRESHOLD:
        return {"ok": False, "error": f"INSUFFICIENT_CLEAN_SESSIONS: {state['consecutive_clean_sessions']}/{CLEAN_SESSION_THRESHOLD}"}
    # 조건 4: enforce_ready == True
    if not state.get("enforce_ready"):
        return {"ok": False, "error": "ENFORCE_NOT_READY"}
    # 조건 5: 현재 mode == audit
    if state.get("mode") != "audit":
        return {"ok": False, "error": f"MODE_INVALID: current={state.get('mode')}"}

    state["mode"] = "enforce"
    state["enforced_at"] = _now_iso()
    save_eag3_state(state)

    _append_obs(OBS_LOG_PATH, {
        "obs_type": "ENFORCE_ACTIVATED",
        "approval_id": approval_id,
        "session": session,
        "timestamp": _now_iso(),
    })
    return {"ok": True, "mode": "enforce", "enforced_at": state["enforced_at"],
            "approval_id": approval_id}

# ── FAIL_CLOSED 복구 ─────────────────────────────────────────────────────────

def release_fail_closed(beo_token: str, approval_id: str) -> dict:
    """
    FAIL_CLOSED 해제.
    선행 조건: flag 존재 + 체인 검증 PASS + Beo 승인.
    """
    import sys as _sys
    lp = "/opt/arss/engine/arss-protocol/tools/ledger"
    if lp not in _sys.path:
        _sys.path.insert(0, lp)
    from ledger_verifier import verify_all_chains, verify_manifest

    # 조건 1: fail_closed.flag 존재
    if not is_fail_closed():
        return {"ok": False, "error": "FAIL_CLOSED_FLAG_NOT_PRESENT"}
    # 조건 2: approval_id 존재
    if not approval_id or not approval_id.strip():
        return {"ok": False, "error": "APPROVAL_ID_MISSING"}
    # 조건 3: beo_token 존재
    if not beo_token or not beo_token.strip():
        return {"ok": False, "error": "BEO_TOKEN_MISSING"}
    # 조건 4: verify_all_chains PASS
    chain_result = verify_all_chains()
    if chain_result.get("status") != "PASS":
        return {"ok": False, "error": "CHAIN_VERIFICATION_FAIL", "detail": chain_result}
    # 조건 5: verify_manifest PASS
    manifest_result = verify_manifest()
    if manifest_result.get("status") != "PASS":
        return {"ok": False, "error": "MANIFEST_VERIFICATION_FAIL", "detail": manifest_result}

    _clear_fail_closed()

    _append_obs(OBS_LOG_PATH, {
        "obs_type": "FAIL_CLOSED_RELEASED",
        "approval_id": approval_id,
        "timestamp": _now_iso(),
    })
    return {"ok": True, "event": "FAIL_CLOSED_RELEASED", "approval_id": approval_id}

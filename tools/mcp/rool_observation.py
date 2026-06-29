"""
rool_observation.py v1.0.0
ROOL — Role-Oriented Observation Layer
EAG-S294-ROOL-IMPL-001

설계 출처: Domi DESIGN v0.2 (S294) + Jeni TRUST_READY (S294)

목적:
  각 에이전트가 역할에 맞는 읽기전용 관측능력을 직접 보유하는 계층.
  실행권한 미부여. 기존 AGENT_ROOT_ALLOWLIST / FORBIDDEN_PATH_PATTERNS 불변.
  Caddy 중개 의존 제거 (Domi 자율 관측).

핵심 구성:
  1. Observation-ID: HMAC-SHA256(Bridge_Secret, actor:session_id:issued_at:nonce:allowlist_hash)
     hex 인코딩 (기존 mcp_read_server.py _make_internal_hmac 패턴 정합)
  2. FAIL_CLOSED 상태머신: INIT → ACTIVE → HARD_STOP → TERMINATED (복귀 불가)
  3. Observation Manifest: HMAC-SHA256 부인방지 + append-only

거버넌스 불변 원칙:
  - Freeze Guard 우회 불가
  - EAG 없이 실행 불가 (ROOL은 관측만)
  - FORBIDDEN_PATH_PATTERNS 완화 불가 (Bridge 커널 레벨 강제)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid

# ── 상수 ──────────────────────────────────────────────────────────────────────

ROOL_VERSION = "1.0.0"

# Bridge_Secret — 기존 bridge READ_HMAC_SECRET와 동일 환경변수 사용 (정합성)
def _get_bridge_secret() -> str:
    """Lazy secret read — avoids module-load-time env capture."""
    return os.environ.get("AIBA_READ_HMAC_SECRET", "")

# TTL 15분 (Jeni 권고: 초기값, 실측 후 조정 가능)
OBSERVATION_TTL_SECONDS = 900

# Manifest 저장 경로 (Jeni 확정 경로)
MANIFEST_DIR = "/opt/arss/engine/arss-protocol/aiba-mcp-bridge/manifests"

# FORBIDDEN_PATH_PATTERNS — mcp_read_server.py와 동일 (Bridge 커널 레벨 강제)
FORBIDDEN_PATH_PATTERNS = [
    r"\.env",
    r"\.key$",
    r"\.pem$",
    r"\.cert$",
    r"token",
    r"secret",
    r"credential",
    r"oauth",
    r"private",
    r"id_rsa",
    r"id_ed25519",
    r"\.ssh",
    r"approval",
]

# ROOL 허용 도구 (실행권한 없음 — 읽기 전용)
ROOL_ALLOWED_TOOLS = frozenset({
    "read", "list", "grep", "log", "snapshot",
})

# 에이전트별 Allowlist Root (mcp_read_server.py AGENT_ROOT_ALLOWLIST 정합)
_CODE_ROOT = "/opt/arss/engine/arss-protocol"
_GOVERNANCE_ROOT = "/opt/arss/engine/arss-protocol/tools/governance"
_EVIDENCE_ROOT = "/opt/arss/engine/arss-protocol/tests"
_METADATA_ROOT = "/opt/arss/engine/arss-protocol"
_LOG_ROOT = "/opt/arss/engine/arss-protocol/tools/mcp"
_ARSS_HUB_ROOT = "/opt/arss/engine/arss-protocol/ARSS_HUB"
_EVIDENCE_CODE_ROOT = "/opt/arss/engine/arss-protocol/tools/evidence"
_SESSION_JOURNAL_ROOT = "/opt/arss/engine/arss-protocol/session_journal"

AGENT_ROOT_ALLOWLIST = {
    "domi": [_CODE_ROOT, _GOVERNANCE_ROOT, _METADATA_ROOT, _EVIDENCE_ROOT, _SESSION_JOURNAL_ROOT],
    "jeni": [_EVIDENCE_ROOT, _LOG_ROOT, _METADATA_ROOT, _GOVERNANCE_ROOT,
             _ARSS_HUB_ROOT, _EVIDENCE_CODE_ROOT, _SESSION_JOURNAL_ROOT],
    "caddy": [_CODE_ROOT, _EVIDENCE_ROOT, _LOG_ROOT, _METADATA_ROOT, _SESSION_JOURNAL_ROOT],
}

# ── FAIL_CLOSED 상태머신 ───────────────────────────────────────────────────────

STATE_INIT = "INIT"
STATE_ACTIVE = "ACTIVE"
STATE_HARD_STOP = "HARD_STOP"
STATE_TERMINATED = "TERMINATED"
STATE_ABORTED = "ABORTED"

# 인메모리 세션 상태 저장소: observation_id → session dict
_observation_sessions: dict = {}


# ── Allowlist Hash ─────────────────────────────────────────────────────────────

def _compute_allowlist_hash(actor: str) -> str:
    """SHA256(정렬된 Allowlist) — Allowlist 변경 시 Observation-ID 자동 무효화."""
    roots = AGENT_ROOT_ALLOWLIST.get(actor, [])
    canonical = json.dumps(sorted(roots), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Observation-ID 발급 ────────────────────────────────────────────────────────

def _build_payload(actor: str, session_id: str, issued_at: int,
                   nonce: str, allowlist_hash: str) -> str:
    """기존 mcp_read_server.py _make_internal_hmac 패턴 정합: ':' 구분자."""
    return f"{actor}:{session_id}:{issued_at}:{nonce}:{allowlist_hash}"


def _sign_payload(payload: str) -> str:
    """HMAC-SHA256 hex 인코딩 (기존 bridge hexdigest 패턴 정합)."""
    return hmac.new(
        _get_bridge_secret().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def begin_observation(actor: str, session_id: str) -> dict:
    """
    /observe/begin — Observation-ID 발급.
    조건: actor 유효 + session_id 존재 + Bridge_Secret 설정.
    INIT_DESIGN 트리거 시에만 호출 (호출자 책임).
    """
    if not _get_bridge_secret():
        return {"status": "FAIL_CLOSED", "reason": "BRIDGE_SECRET_NOT_CONFIGURED"}
    if actor not in AGENT_ROOT_ALLOWLIST:
        return {"status": "FAIL_CLOSED", "reason": f"UNKNOWN_ACTOR:{actor}"}
    if not session_id:
        return {"status": "FAIL_CLOSED", "reason": "SESSION_ID_REQUIRED"}

    issued_at = int(time.time() * 1000)  # UTC Epoch ms
    nonce = uuid.uuid4().hex  # 128bit random
    allowlist_hash = _compute_allowlist_hash(actor)
    payload = _build_payload(actor, session_id, issued_at, nonce, allowlist_hash)
    signature = _sign_payload(payload)
    observation_id = signature  # hex 서명 자체를 ID로 사용 (위조 불가)

    _observation_sessions[observation_id] = {
        "actor": actor,
        "session_id": session_id,
        "issued_at": issued_at,
        "nonce": nonce,
        "allowlist_hash": allowlist_hash,
        "state": STATE_ACTIVE,
    }

    return {
        "status": "ALLOW",
        "observation_id": observation_id,
        "actor": actor,
        "session_id": session_id,
        "issued_at": issued_at,
        "allowlist_hash": allowlist_hash,
        "ttl_seconds": OBSERVATION_TTL_SECONDS,
    }


# ── Observation-ID 검증 ────────────────────────────────────────────────────────

def verify_observation(observation_id: str, actor: str, session_id: str) -> dict:
    """
    5단계 검증: HMAC + TTL + actor + session + allowlist_hash.
    하나라도 실패 시 FAIL_CLOSED.
    """
    session = _observation_sessions.get(observation_id)
    if session is None:
        return {"ok": False, "reason": "INVALID_SIGNATURE", "http_status": 403}

    # 세션 상태 확인 (HARD_STOP/TERMINATED는 복귀 불가)
    if session["state"] in (STATE_HARD_STOP, STATE_TERMINATED, STATE_ABORTED):
        return {"ok": False, "reason": "SESSION_TERMINATED", "http_status": 403}

    # actor 일치
    if session["actor"] != actor:
        return {"ok": False, "reason": "ACTOR_MISMATCH", "http_status": 403}

    # session_id 일치
    if session["session_id"] != session_id:
        return {"ok": False, "reason": "SESSION_MISMATCH", "http_status": 403}

    # HMAC 재계산 검증 (위조 차단)
    payload = _build_payload(actor, session_id, session["issued_at"],
                             session["nonce"], session["allowlist_hash"])
    expected = _sign_payload(payload)
    if not hmac.compare_digest(expected, observation_id):
        return {"ok": False, "reason": "INVALID_SIGNATURE", "http_status": 403}

    # allowlist_hash 일치 (런타임 Allowlist 변경 시 자동 무효화)
    current_allowlist_hash = _compute_allowlist_hash(actor)
    if current_allowlist_hash != session["allowlist_hash"]:
        return {"ok": False, "reason": "ALLOWLIST_CHANGED", "http_status": 403}

    # TTL 검증
    now_ms = int(time.time() * 1000)
    age_seconds = (now_ms - session["issued_at"]) / 1000.0
    if age_seconds > OBSERVATION_TTL_SECONDS:
        return {"ok": False, "reason": "SESSION_EXPIRED", "http_status": 403}

    return {"ok": True, "reason": None, "http_status": 200}


# ── FORBIDDEN_PATH 검사 (Bridge 커널 레벨) ───────────────────────────────────────

def _is_forbidden_path(target_path: str) -> bool:
    """FORBIDDEN_PATH_PATTERNS 매칭 — Bridge 커널 레벨 강제."""
    if not target_path:
        return False
    path_lower = target_path.lower()
    for pattern in FORBIDDEN_PATH_PATTERNS:
        if re.search(pattern, path_lower):
            return True
    return False


def _terminate_session(observation_id: str, new_state: str = STATE_TERMINATED) -> None:
    """세션을 불가역 종료 상태로 전이."""
    session = _observation_sessions.get(observation_id)
    if session is not None:
        session["state"] = new_state


# ── Manifest 부인 방지 ─────────────────────────────────────────────────────────

def _canonical_manifest(manifest: dict) -> str:
    """
    Canonical JSON — sort_keys=True + separators 공백 제거.
    Jeni Advisory: 공백/키정렬 불일치로 인한 HMAC False-Positive 방지.
    integrity_manifest 필드는 계산 대상에서 제외.
    """
    body = {k: v for k, v in manifest.items() if k != "integrity_manifest"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_integrity_manifest(manifest: dict) -> str:
    """HMAC-SHA256(Bridge_Secret, canonical_manifest)."""
    canonical = _canonical_manifest(manifest)
    return hmac.new(
        _get_bridge_secret().encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def write_observation_manifest(actor: str, session_id: str, observation_id: str,
                               tool: str, target: str, result: str,
                               http_status: int, allowlist_root: str = "",
                               bytes_read: int = 0) -> dict:
    """
    Observation Manifest 생성 + integrity_manifest 부인방지 해시 첨부.
    append-only: OBS_{session_id}_{observation_id앞12}.json
    """
    manifest = {
        "actor": actor,
        "session_id": session_id,
        "tool": tool,
        "target": target,
        "observation_id": observation_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "result": result,
        "http_status": http_status,
        "bytes_read": bytes_read,
        "allowlist_root": allowlist_root,
    }
    manifest["integrity_manifest"] = _compute_integrity_manifest(manifest)

    try:
        os.makedirs(MANIFEST_DIR, exist_ok=True)
        oid_short = observation_id[:12]
        fname = f"OBS_{session_id}_{oid_short}.json"
        fpath = os.path.join(MANIFEST_DIR, fname)
        # append-only: 동일 파일 존재 시 라인 추가 (JSONL)
        with open(fpath, "a", encoding="utf-8") as f:
            f.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        return {"ok": True, "manifest_path": fpath, "manifest": manifest}
    except Exception as e:
        return {"ok": False, "reason": f"MANIFEST_WRITE_FAILED: {e}"}


def verify_manifest_integrity(manifest: dict) -> dict:
    """
    Jeni 검증 절차: integrity_manifest 제거 → canonical 재생성 → HMAC 재계산 → 대조.
    일치 PASS / 불일치 TAMPER_DETECTED.
    """
    stored = manifest.get("integrity_manifest", "")
    if not stored:
        return {"ok": False, "reason": "NO_INTEGRITY_FIELD"}
    recomputed = _compute_integrity_manifest(manifest)
    if hmac.compare_digest(stored, recomputed):
        return {"ok": True, "result": "PASS"}
    return {"ok": False, "result": "TAMPER_DETECTED"}


# ── ObservationFailureEvent (Caddy 전달용) ──────────────────────────────────────

def make_failure_event(session_id: str, actor: str, observation_id: str,
                       reason: str, http_status: int) -> dict:
    """Bridge → Caddy 전달 형식. Caddy는 해석 없이 전달만."""
    return {
        "event_type": "ObservationFailureEvent",
        "session_id": session_id,
        "actor": actor,
        "observation_id": observation_id,
        "reason": reason,
        "http_status": http_status,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    }


# ── ROOL 관측 실행 (검증 → FORBIDDEN 검사 → Manifest 기록) ─────────────────────

def observe(observation_id: str, actor: str, session_id: str,
            tool: str, target: str = "") -> dict:
    """
    ROOL 관측 진입점.
    흐름: ID 검증 → 도구 허용 확인 → FORBIDDEN 검사 → (호출자가 실제 read 수행) → Manifest.
    실제 파일 읽기는 호출자(bridge)가 기존 _handle_read_tool로 수행.
    이 함수는 게이트 + Manifest만 담당.
    """
    # 1. 도구 허용 확인
    if tool not in ROOL_ALLOWED_TOOLS:
        return {"status": "FAIL_CLOSED", "reason": f"TOOL_NOT_ALLOWED:{tool}",
                "http_status": 403}

    # 2. Observation-ID 5단계 검증
    v = verify_observation(observation_id, actor, session_id)
    if not v["ok"]:
        return {"status": "FAIL_CLOSED", "reason": v["reason"],
                "http_status": v["http_status"],
                "failure_event": make_failure_event(
                    session_id, actor, observation_id, v["reason"], v["http_status"])}

    # 3. FORBIDDEN_PATH 검사 (Bridge 커널 레벨) → 위반 시 세션 TERMINATED
    if target and _is_forbidden_path(target):
        _terminate_session(observation_id, STATE_TERMINATED)
        reason = "FORBIDDEN_PATH"
        write_observation_manifest(actor, session_id, observation_id,
                                   tool, target, "DENY", 403)
        return {"status": "FAIL_CLOSED", "reason": reason, "http_status": 403,
                "session_state": STATE_TERMINATED,
                "failure_event": make_failure_event(
                    session_id, actor, observation_id, reason, 403)}

    # 4. 게이트 통과 — 호출자가 실제 read 수행하도록 ALLOW 반환
    return {"status": "ALLOW", "observation_id": observation_id,
            "actor": actor, "tool": tool, "target": target}


def record_observe_result(actor: str, session_id: str, observation_id: str,
                          tool: str, target: str, success: bool,
                          bytes_read: int = 0, allowlist_root: str = "") -> dict:
    """관측 성공/실패 후 Manifest 기록 (호출자가 read 완료 후 호출)."""
    result = "ALLOW" if success else "DENY"
    http_status = 200 if success else 403
    return write_observation_manifest(
        actor, session_id, observation_id, tool, target,
        result, http_status, allowlist_root, bytes_read)


# ── 상태 조회 (테스트/감사용) ──────────────────────────────────────────────────

def get_session_state(observation_id: str) -> str:
    session = _observation_sessions.get(observation_id)
    return session["state"] if session else "NOT_FOUND"


def _reset_sessions_for_test() -> None:
    """테스트 전용 — 세션 저장소 초기화."""
    _observation_sessions.clear()

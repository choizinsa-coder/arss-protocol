#!/usr/bin/env python3
"""
AIBA VPS /status Server — v0.5
설계: 도미 v0.3 확정안
보정: 도미 검토 지적 5개 + 보조 2개 반영 (2026-03-28)
조건부 EAG 승인: 비오 (TASK-SSOT-STEP3 v0.4)
담당: 캐디 (Claude)

변경 내역 v0.3 → v0.4:
  [수정-1] READ signature 필수화 — 조건부 통과 제거
  [수정-2] WRITE auth → agent-specific (AGENT_TOKENS 통일 + WRITE_ALLOWED_AGENTS)
  [수정-3] integrity.signature → HMAC-SHA256, 필드명 server_hmac으로 변경
  [수정-4] session_context_ref hash/url 기준 통일 — state에서 명시적 관리
  [수정-5] interpretation.status="pending" + activation_status 추가
  [보조-A] write_lock 서버 내부 실제 파일 기반 락 구현
  [보조-B] POST /status/update 실제 state 저장 구현

엔드포인트:
  GET  /status         — 상태 주입 (읽기 전용, SSOT + SSOI)
  POST /status/update  — 상태 갱신 (쓰기 경로, collision control)
  GET  /health         — 헬스체크 (인증 불필요)
"""

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

# ─────────────────────────────────────────────
# 설정 (환경변수 또는 기본값)
# ─────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("AIBA_BASE_DIR", "/opt/arss/engine/arss-protocol"))
STATUS_STATE_FILE = BASE_DIR / "status_state.json"
SIGNED_CACHE_FILE = BASE_DIR / "status_cache.json"
WRITE_LOCK_FILE   = BASE_DIR / "status_write.lock"  # [보조-A] 파일 기반 락

# [수정-2] Agent 토큰 — READ/WRITE 모두 동일 딕셔너리 사용
AGENT_TOKENS = {
    "caddy":  os.environ.get("AIBA_TOKEN_CADDY",  "caddy-token-placeholder"),
    "domi":   os.environ.get("AIBA_TOKEN_DOMI",   "domi-token-placeholder"),
    "jeni":   os.environ.get("AIBA_TOKEN_JENI",   "jeni-token-placeholder"),
    "system": os.environ.get("AIBA_TOKEN_SYSTEM", "system-token-placeholder"),
}

# [수정-2] WRITE 허용 agent 목록 별도 관리
WRITE_ALLOWED_AGENTS = set(
    s.strip() for s in os.environ.get("AIBA_WRITE_AGENTS", "caddy,system").split(",")
)

# [수정-3] HMAC 서명 키
SIGNATURE_KEY = os.environ.get("AIBA_SIGNATURE_KEY", "aiba-signature-key-placeholder").encode()

# Stability: fallback 최대 허용 staleness (초)
MAX_STALENESS_SECONDS = int(os.environ.get("AIBA_MAX_STALENESS", "300"))

# VPS 공개 베이스 URL
VPS_BASE_URL = os.environ.get("AIBA_VPS_BASE_URL", "https://aiba.xyz")


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────

def canonical_json(obj: dict) -> bytes:
    """무결성 서명용 canonical JSON (sort_keys=True, ensure_ascii=False)"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_sha256_hex(data: bytes, key: bytes) -> str:
    """[수정-3] HMAC-SHA256"""
    return hmac.new(key, data, hashlib.sha256).hexdigest()


def compute_payload_hash(payload: dict) -> str:
    return sha256_hex(canonical_json(payload))


def verify_request_signature(agent_id: str, body_bytes: bytes, sig_header: str) -> bool:
    """request body + agent_id 기반 HMAC-SHA256 서명 검증"""
    expected = hmac.new(
        SIGNATURE_KEY,
        agent_id.encode() + b":" + body_bytes,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state() -> dict | None:
    if STATUS_STATE_FILE.exists():
        try:
            return json.loads(STATUS_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_state(state: dict):
    STATUS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_cache() -> dict | None:
    if SIGNED_CACHE_FILE.exists():
        try:
            return json.loads(SIGNED_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save_cache(payload: dict, payload_hash: str):
    cache = {
        "last_valid_hash": payload_hash,
        "cache_source":    "local_signed",
        "cached_at":       now_iso(),
        "payload":         payload,
    }
    SIGNED_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNED_CACHE_FILE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


# ─────────────────────────────────────────────
# [보조-A] 파일 기반 write_lock
# ─────────────────────────────────────────────

def acquire_write_lock(agent_id: str) -> bool:
    """
    [권장-3] 원자적 락 획득 — os.open O_CREAT|O_EXCL 사용.
    O_EXCL은 파일이 이미 존재하면 FileExistsError를 발생시켜
    TOCTOU 경쟁 상태를 방지합니다.
    """
    WRITE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            str(WRITE_LOCK_FILE),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY
        )
        try:
            os.write(fd, json.dumps(
                {"locked_by": agent_id, "locked_at": now_iso()}
            ).encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return False


def release_write_lock():
    """락 파일 삭제"""
    if WRITE_LOCK_FILE.exists():
        WRITE_LOCK_FILE.unlink(missing_ok=True)


def read_write_lock() -> dict | None:
    if WRITE_LOCK_FILE.exists():
        try:
            return json.loads(WRITE_LOCK_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return None


# ─────────────────────────────────────────────
# 인증 데코레이터 (READ / WRITE 공통)
# ─────────────────────────────────────────────

def require_auth(f):
    """
    Auth v0.3 (수정-1, 수정-2 반영):
    - Authorization: Bearer <agent_token>      필수
    - X-AIBA-Agent-ID: <agent_id>              필수
    - X-AIBA-Signature: <HMAC-SHA256(...)>     필수 (READ 포함 — 수정-1)
    agent_id → AGENT_TOKENS 검증 (READ/WRITE 동일 — 수정-2)
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        agent_id    = request.headers.get("X-AIBA-Agent-ID", "")
        sig_header  = request.headers.get("X-AIBA-Signature", "")

        # Bearer 토큰
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header"}), 401
        token = auth_header[len("Bearer "):].strip()

        # agent_id 유효성
        if agent_id not in AGENT_TOKENS:
            return jsonify({"error": "Unknown agent_id"}), 401

        # 토큰 매칭 (agent-specific)
        if not hmac.compare_digest(AGENT_TOKENS[agent_id], token):
            return jsonify({"error": "Invalid token for agent"}), 401

        # [수정-1] Signature 필수 — 조건부 없음
        if not sig_header:
            return jsonify({"error": "X-AIBA-Signature required"}), 401
        body_bytes = request.get_data()
        if not verify_request_signature(agent_id, body_bytes, sig_header):
            return jsonify({"error": "Signature mismatch — request rejected"}), 401

        request.aiba_agent_id = agent_id
        return f(*args, **kwargs)
    return decorated


def require_write_auth(f):
    """
    WRITE 전용 추가 검증:
    require_auth 통과 후 WRITE_ALLOWED_AGENTS 확인
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        agent_id = getattr(request, "aiba_agent_id", None)
        if agent_id not in WRITE_ALLOWED_AGENTS:
            return jsonify({
                "error": f"Agent '{agent_id}' is not authorized for WRITE operations"
            }), 403
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# payload 빌더
# ─────────────────────────────────────────────

def build_status_payload(raw_state: dict) -> dict:
    """
    v0.3 payload 스키마 빌드 (구조 변경 없음)
    Top-Level: meta / state / interpretation / integrity / stability
    """
    chain_data  = raw_state.get("chain", {})
    system_data = raw_state.get("system", {})

    # ── meta ──────────────────────────────────
    meta = {
        "schema_version": "status-1.2",
        "generated_at":   now_iso(),
        "source":         "VPS",
        "environment":    raw_state.get("environment", "prod"),
        "phase":          raw_state.get("phase", "PHASE 2"),
        "webhook": {
            "enabled":          False,
            "endpoint":         None,
            "events": [
                "state_updated",
                "chain_updated",
                "interpretation_updated"
            ],
            "signature_header": "X-AIBA-Webhook-Signature"
        }
    }

    # ── state (SSOT) ──────────────────────────
    # [수정-4] session_context_ref: hash/url 기준 통일
    # hash는 state 파일에서 명시적으로 관리 — 자동 계산 제거
    session_ref = raw_state.get("session_context_ref", {})
    state = {
        "session_context_ref": {
            "version": session_ref.get("version", "2.3"),
            "hash":    session_ref.get("hash", ""),    # state 파일에 명시된 값 사용
            "url":     session_ref.get("url",          # url도 state에서 관리
                           f"{VPS_BASE_URL}/SESSION_CONTEXT.json")
        },
        "chain": {
            "tip":      chain_data.get("tip", ""),
            "last_rpu": chain_data.get("last_rpu", "")
        },
        "system": {
            "version":      system_data.get("version", "v1.3"),
            "architecture": system_data.get("architecture", "AIBA Session Sync")
        }
    }

    # ── interpretation (SSOI) ────────────────
    # [수정-5] interpretation.status 명시
    interp = raw_state.get("interpretation", {})
    interp_status = interp.get("status", "pending")
    interpretation = {
        "mode":    interp.get("mode", "external_ref"),
        "ref":     interp.get("ref",
                       f"{VPS_BASE_URL}/INTERPRETATION_RULE.json"),
        "version": interp.get("version", "v1.0"),
        "hash":    interp.get("hash", ""),
        "status":  interp_status,   # [수정-5] "pending" | "active"
        "fallback": {
            "allow":  False,
            "reason": "해석 규칙 없이 실행 금지 — SSOI 붕괴 위험"
        }
    }

    # ── 무결성 서명 ───────────────────────────
    core = {"meta": meta, "state": state, "interpretation": interpretation}
    payload_hash  = compute_payload_hash(core)
    canonical_bytes = canonical_json(core)

    # [수정-3] HMAC-SHA256, 필드명 server_hmac
    integrity = {
        "payload_hash": payload_hash,
        "server_hmac":  hmac_sha256_hex(canonical_bytes, SIGNATURE_KEY),  # 수정-3
        "prev_hash":    raw_state.get("prev_hash", None),
        "verification_hint": "ARSS-compatible"
    }

    # ── stability ─────────────────────────────
    issued_at  = now_iso()
    expires_ts = int(time.time()) + MAX_STALENESS_SECONDS
    expires_at = datetime.fromtimestamp(expires_ts, tz=timezone.utc).isoformat()

    stability = {
        "fallback_policy": {
            "allow_fallback":          True,
            "max_staleness_seconds":   MAX_STALENESS_SECONDS,
            "require_integrity_match": True
        },
        "ttl": {
            "issued_at":  issued_at,
            "expires_at": expires_at
        },
        "cache": {
            "last_valid_hash": payload_hash,
            "cache_source":    "local_signed"
        }
    }

    # [수정-5] activation_status — interpretation pending 시 pre-activation
    activation_status = (
        "active" if interp_status == "active" else "pre-activation"
    )

    return {
        "meta":              meta,
        "state":             state,
        "interpretation":    interpretation,
        "integrity":         integrity,
        "stability":         stability,
        "activation_status": activation_status,  # [수정-5]
    }


# ─────────────────────────────────────────────
# Mismatch + Fallback 정책
# ─────────────────────────────────────────────

MISMATCH_POLICY = {
    "chain_mismatch":               "STOP",
    "schema_mismatch":              "STOP",
    "interpretation_hash_mismatch": "WARN_STOP",
    "vps_unreachable":              "CONDITIONAL_FALLBACK"
}


def check_payload_integrity(payload: dict) -> tuple[bool, str]:
    """
    무결성 자가 검증:
    integrity.payload_hash == sha256(canonical(meta+state+interpretation))
    """
    core = {k: payload[k] for k in ("meta", "state", "interpretation") if k in payload}
    expected = compute_payload_hash(core)
    actual   = payload.get("integrity", {}).get("payload_hash", "")
    if expected != actual:
        return False, f"hash_mismatch: expected={expected} actual={actual}"
    return True, "ok"


# ─────────────────────────────────────────────
# Route: GET /status  (읽기 전용)
# ─────────────────────────────────────────────

@app.route("/status", methods=["GET"])
@require_auth
def get_status():
    raw_state = load_state()

    if raw_state is None:
        # state 로드 실패 → signed cache fallback 시도
        cache = load_cache()
        if cache and cache.get("payload"):
            cached_payload = cache["payload"]
            ok, _ = check_payload_integrity(cached_payload)
            # TTL 검증
            expires_str = cached_payload.get("stability", {}).get("ttl", {}).get("expires_at", "")
            ttl_valid = False
            try:
                ttl_valid = datetime.now(timezone.utc) < datetime.fromisoformat(expires_str)
            except ValueError:
                pass
            if ok and ttl_valid:
                cached_payload["_fallback"] = {
                    "active": True,
                    "reason": "state_load_failed",
                    "policy": MISMATCH_POLICY["vps_unreachable"]
                }
                return jsonify(cached_payload), 200
        return jsonify({
            "error": "State unavailable — STOP. No valid fallback.",
            "mismatch_policy": MISMATCH_POLICY
        }), 503

    payload = build_status_payload(raw_state)

    # 무결성 자가 검증
    ok, reason = check_payload_integrity(payload)
    if not ok:
        return jsonify({
            "error": f"Integrity check failed — STOP. {reason}",
            "mismatch_policy": MISMATCH_POLICY
        }), 500

    # TTL 검증
    try:
        expires_at = datetime.fromisoformat(
            payload["stability"]["ttl"]["expires_at"]
        )
        if datetime.now(timezone.utc) > expires_at:
            return jsonify({
                "error": "TTL expired — STOP.",
                "mismatch_policy": MISMATCH_POLICY
            }), 503
    except ValueError:
        pass

    # signed cache 갱신
    save_cache(payload, payload["integrity"]["payload_hash"])

    return jsonify(payload), 200


# ─────────────────────────────────────────────
# Route: POST /status/update  (쓰기 경로)
# ─────────────────────────────────────────────

@app.route("/status/update", methods=["POST"])
@require_auth
@require_write_auth   # [수정-2] WRITE 허용 agent 검증
def post_status_update():
    """
    상태 갱신 이벤트.
    READ 경로와 완전 분리.
    [보조-A] 파일 기반 write_lock 실제 구현.
    [보조-B] 실제 state 저장 구현.
    """
    agent_id = request.aiba_agent_id

    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    if not body:
        return jsonify({"error": "Empty body"}), 400

    # [보조-A] 파일 기반 write_lock 획득
    lock_info = read_write_lock()
    if lock_info is not None:
        return jsonify({
            "error": f"Write lock active — locked by '{lock_info.get('locked_by', 'unknown')}'. Collision prevented.",
            "lock_info": lock_info
        }), 409

    if not acquire_write_lock(agent_id):
        return jsonify({"error": "Failed to acquire write lock"}), 409

    try:
        # 현재 state 로드
        current_state = load_state() or {}

        # 상태 병합: write_control 이외 필드만 업데이트
        updated_state = current_state.copy()
        for k, v in body.items():
            if k != "write_control":
                updated_state[k] = v

        # write_control 갱신
        current_version = current_state.get("write_control", {}).get("version", 0)
        updated_state["write_control"] = {
            "last_updated_by": agent_id,
            "write_lock":      False,
            "version":         int(current_version) + 1,
            "timestamp":       now_iso()
        }

        # [보조-B] 실제 state 저장
        save_state(updated_state)

    finally:
        # 락 해제 (예외 발생해도 반드시 해제)
        release_write_lock()

    return jsonify({
        "status":       "updated",
        "updated_by":   agent_id,
        "write_control": updated_state["write_control"]
    }), 200


# ─────────────────────────────────────────────
# Health check (인증 불필요)
# ─────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":    "ok",
        "system":    "AIBA /status v0.5",
        "timestamp": now_iso()
    }), 200


# ─────────────────────────────────────────────
# 초기 state 파일 생성 헬퍼
# ─────────────────────────────────────────────

def initialize_default_state():
    """
    status_state.json이 없을 경우 기본값으로 초기화.
    SESSION_CONTEXT v2.3 기준값 반영.
    [수정-4] session_context_ref.hash = 명시적 관리값 (자동 계산 아님)
    [수정-5] interpretation.status = "pending"
    """
    if STATUS_STATE_FILE.exists():
        return

    default_state = {
        "environment": "prod",
        "phase":       "PHASE 2",
        # [수정-4] hash/url 동일 소스 기준 — 명시적으로 관리
        "session_context_ref": {
            "version": "2.3",
            "hash":    "3a97b31b09c7bdfe7a4c22eb7713459a2c2d25e2e9bca588b9f572a0e9445839",
            "url":     f"{VPS_BASE_URL}/SESSION_CONTEXT.json"
        },
        "chain": {
            "tip":      "3a97b31b09c7bdfe7a4c22eb7713459a2c2d25e2e9bca588b9f572a0e9445839",
            "last_rpu": "RPU-0012"
        },
        "system": {
            "version":      "v1.3",
            "architecture": "AIBA Session Sync"
        },
        # [수정-5] interpretation.status = "pending" 명시
        "interpretation": {
            "mode":    "external_ref",
            "ref":     f"{VPS_BASE_URL}/INTERPRETATION_RULE.json",
            "version": "v1.0",
            "hash":    "",
            "status":  "pending"
        },
        "prev_hash": None,
        "write_control": {
            "last_updated_by": "system",
            "write_lock":      False,
            "version":         0,
            "timestamp":       now_iso()
        }
    }

    STATUS_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_STATE_FILE.write_text(
        json.dumps(default_state, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[AIBA] Initialized default state: {STATUS_STATE_FILE}")


# ─────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────

if __name__ == "__main__":
    initialize_default_state()
    port = int(os.environ.get("AIBA_STATUS_PORT", "8080"))
    print(f"[AIBA] /status server v0.5 starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)

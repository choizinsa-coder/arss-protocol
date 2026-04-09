#!/usr/bin/env python3
"""
arss_generator_v1.py — ARSS 프로덕션 RPU 생성기

기준: ARSS-RPU-Production-Spec-v1.0
알고리즘: IMMUTABLE (LESSON-005)
EAG-1 조건부 승인: 비오(Joshua) 2026-04-06
EAG-2 승인: 비오(Joshua) 2026-04-06

책임 범위:
  - RPU 후보 객체 생성 (해싱 포함)
  - verifier PASS 확인
  - persistence_allowed 플래그 반환
  ※ 파일 저장·GitHub push는 상위 실행 계층 책임 (EAG-1 조건)
  ※ single-writer 보장은 상위 오케스트레이션 책임 (Phase 2-A 단일 writer 원칙)
"""

import hashlib
import json
import os
import struct
import time
import random
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer


# ── 상수 (governance_context 고정값) ──────────────────────────────
GOVERNANCE_CONTEXT = {
    "policy_id": "ARSS_HUB_PROTOCOL_v1.2",
    "authority_root": "Beo",
    "jurisdiction": "AIBA_GLOBAL",
}
GENESIS_PREV_HASH = "0" * 64
INTERPRETATION_RULE_PATH = os.environ.get(
    "INTERPRETATION_RULE_PATH",
    "/opt/arss/engine/arss-protocol/INTERPRETATION_RULE.json",
)
RPU_VERSION = "rpu/1.0"


# ── INTERPRETATION_RULE 로딩 (기동 시 1회) ───────────────────────
def load_allowed_event_types(path: str) -> set:
    """SSOI 기준 허용 event_type 목록 로딩. 기동 시 1회, 재기동 시 갱신."""
    with open(path, "r", encoding="utf-8") as f:
        rule = json.load(f)
    event_types = rule.get("score_rules", {}).get("event_types", {})
    return set(event_types.keys())


# ── 해싱 알고리즘 (IMMUTABLE — LESSON-005) ───────────────────────
def canonical_json(obj: dict) -> str:
    """recursive dict 알파벳 정렬 + json.dumps(ensure_ascii=False)."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_payload_hash(payload: dict) -> str:
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def compute_chain_hash(prev_chain_hash: str, payload_hash: str) -> str:
    material = (prev_chain_hash + ":" + payload_hash).encode("utf-8")
    return sha256_hex(material)


# ── UUIDv7 내부 구현 (Python 3.10 환경 — 표준 미지원) ───────────
def generate_uuidv7() -> str:
    """
    UUIDv7 스펙 호환 문자열 생성.
    - ms 단위 timestamp (48bit) + version(4bit=7) + rand_a(12bit)
    + variant(2bit) + rand_b(62bit)
    """
    ms = int(time.time() * 1000)
    rand_a = random.getrandbits(12)
    rand_b = random.getrandbits(62)

    hi = (ms << 16) | (0x7 << 12) | rand_a
    lo = (0b10 << 62) | rand_b

    b = struct.pack(">QQ", hi, lo)
    h = b.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ── 타임스탬프 (UTC RFC3339 마이크로초) ──────────────────────────
def utc_timestamp_microseconds() -> str:
    """예: 2026-04-06T17:30:00.123456Z"""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


# ── 입력 검증 ──────────────────────────────────────────────────
class GeneratorError(Exception):
    pass

class ValidationError(GeneratorError):
    pass

class VerificationError(GeneratorError):
    pass


def validate_request(req: dict, allowed_event_types: set):
    required = ["event_type", "actor_id", "content", "prev_chain_hash"]
    for field in required:
        if field not in req:
            raise ValidationError(f"Missing field: {field}")
        if not isinstance(req[field], str) or not req[field].strip():
            raise ValidationError(f"Empty or invalid field: {field}")

    pch = req["prev_chain_hash"]
    if len(pch) != 64 or not all(c in "0123456789abcdef" for c in pch):
        raise ValidationError(f"Invalid prev_chain_hash format: {pch[:16]}...")

    if req["event_type"] not in allowed_event_types:
        raise ValidationError(
            f"ERR-005: event_type '{req['event_type']}' not in INTERPRETATION_RULE. "
            f"Allowed: {sorted(allowed_event_types)}"
        )


# ── RPU 생성 코어 ──────────────────────────────────────────────
def build_rpu(req: dict, allowed_event_types: set) -> dict:
    validate_request(req, allowed_event_types)

    payload = {
        "event_type": req["event_type"],
        "content": req["content"],
    }
    payload_hash = compute_payload_hash(payload)
    chain_hash = compute_chain_hash(req["prev_chain_hash"], payload_hash)

    return {
        "schema_version": "ARSS-RPU-1.0",
        "rpu_id": generate_uuidv7(),
        "timestamp": utc_timestamp_microseconds(),
        "actor_id": req["actor_id"],
        "payload": payload,
        "chain": {
            "payload_hash": payload_hash,
            "prev_chain_hash": req["prev_chain_hash"],
            "chain_hash": chain_hash,
        },
        "governance_context": GOVERNANCE_CONTEXT,
    }


# ── verifier 연동 (subprocess — EAG-2 현행, HTTP 전환은 EAG-2 후 결정) ─
def verify_candidate_rpu(candidate: dict) -> dict:
    import subprocess
    import tempfile

    bridge_path = os.environ.get(
        "VERIFIER_BRIDGE_PATH",
        "/opt/arss/engine/arss-protocol/scripts/vps_verifier_bridge.py",
    )
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(candidate, tmp, ensure_ascii=False)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["python3", bridge_path, "--single", tmp_path],
            capture_output=True, text=True, timeout=30
        )
        ok = result.returncode == 0
        return {
            "ok": ok,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "errors": [] if ok else [result.stderr],
        }
    finally:
        os.unlink(tmp_path)


# ── 생성 + 검증 통합 게이트 ────────────────────────────────────
def generate_and_validate(req: dict, allowed_event_types: set) -> dict:
    """
    반환값:
      { "status": "PASS", "candidate_rpu": {...}, "persistence_allowed": True }
    실패 시 VerificationError 발생 — 파일 저장 단계 진입 불가.
    """
    candidate = build_rpu(req, allowed_event_types)
    verification = verify_candidate_rpu(candidate)

    if not verification["ok"]:
        raise VerificationError({
            "code": "ERR_VERIFY_FAIL",
            "message": "Verifier rejected candidate RPU",
            "details": verification,
            "persistence": "blocked",
        })

    return {
        "status": "PASS",
        "candidate_rpu": candidate,
        "persistence_allowed": True,
    }


# ── HTTP 어댑터 ────────────────────────────────────────────────
class GeneratorHandler(BaseHTTPRequestHandler):
    allowed_event_types: set = set()

    def log_message(self, format, *args):
        pass

    def _send_json(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _check_auth(self) -> bool:
        token = os.environ.get("AIBA_TOKEN_CADDY", "")
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {token}"

    def do_POST(self):
        if self.path != "/generate":
            self._send_json(404, {"error": "Not found"})
            return
        if not self._check_auth():
            self._send_json(401, {"error": "Unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            result = generate_and_validate(body, self.allowed_event_types)
            self._send_json(200, result)
        except ValidationError as e:
            self._send_json(400, {"error": "ValidationError", "detail": str(e)})
        except VerificationError as e:
            self._send_json(422, {"error": "VerificationError", "detail": str(e)})
        except Exception as e:
            self._send_json(500, {"error": "InternalError", "detail": str(e)})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "version": "arss_generator_v1"})
        else:
            self._send_json(404, {"error": "Not found"})


# ── 진입점 ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("GENERATOR_PORT", "8001"))
    allowed = load_allowed_event_types(INTERPRETATION_RULE_PATH)
    print(f"[arss_generator_v1] Loaded {len(allowed)} event types from INTERPRETATION_RULE")
    GeneratorHandler.allowed_event_types = allowed
    server = HTTPServer(("127.0.0.1", port), GeneratorHandler)
    print(f"[arss_generator_v1] Listening on 127.0.0.1:{port}")
    server.serve_forever()

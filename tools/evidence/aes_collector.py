"""
aes_collector.py
AIBA Evidence Standard (AES) v1.0 Collector
EAG-S211-AES-001 — 비오(Joshua) S211 승인
설계: 도미(Domi) Rev.1 / 검증: 제니(Jeni) TRUST_READY PASS

역할:
  - AES Record 생성 (SHA256 계산 + 메타데이터 조립)
  - aes_index.jsonl append (참조 무결성 검증 포함)

원칙:
  - Ledger / Observation 인터페이스 무변경
  - payload_ref 존재 체크 필수 (Jeni 강제 조건 1)
  - aes_index.jsonl chattr +a 적용 (Jeni 강제 조건 2)
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
AES_INDEX_DIR = Path(ARSS_ROOT) / "ARSS_HUB" / "04_EVIDENCE" / "AES_INDEX"
AES_INDEX_PATH = AES_INDEX_DIR / "aes_index.jsonl"

KST = timezone(timedelta(hours=9))

VALID_TYPES = frozenset({
    "WORM_PHYSICAL",
    "LEDGER_CHAIN",
    "OBSERVATION",
    "CODE_METRIC",
    "EAG_ARTIFACT",
})

VALID_COLLECTORS = frozenset({"system", "caddy", "jeni"})


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _sha256_file(path: str) -> str:
    """파일 SHA256 계산."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_payload_path(payload_ref: str) -> str:
    """
    payload_ref → 절대 경로 변환.
    절대 경로면 그대로, 상대 경로면 ARSS_ROOT 기준.
    """
    if os.path.isabs(payload_ref):
        return payload_ref
    return os.path.join(ARSS_ROOT, payload_ref)


def _next_evidence_id(session: str) -> str:
    """
    aes_index.jsonl 기존 레코드 수 기준 시퀀스 생성.
    형식: AES-{SESSION}-{6자리}
    """
    count = 0
    if AES_INDEX_PATH.exists():
        try:
            with open(AES_INDEX_PATH, "r", encoding="utf-8") as f:
                count = sum(1 for line in f if line.strip())
        except Exception:
            count = 0
    return f"AES-{session}-{count + 1:06d}"


def _ensure_index_append_only() -> None:
    """
    aes_index.jsonl 신규 생성 시 chattr +a 적용.
    Jeni 강제 조건 2 — AES-OP-003 준수.
    """
    if not AES_INDEX_PATH.exists():
        AES_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        AES_INDEX_PATH.touch()
        try:
            subprocess.run(
                ["chattr", "+a", str(AES_INDEX_PATH)],
                capture_output=True, check=True
            )
        except Exception:
            # chattr 실패 시 경고만 (권한 환경에 따라 실패 가능)
            pass


def _append_record(record: dict) -> None:
    """aes_index.jsonl에 레코드 append."""
    AES_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    with open(AES_INDEX_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


# ── 공개 API ──────────────────────────────────────────────────────────────────

def register_evidence(
    evidence_type: str,
    session: str,
    eag_id: Optional[str],
    payload_ref: str,
    collector: str,
    metadata: Optional[dict] = None,
) -> dict:
    """
    AES Record 생성 및 aes_index.jsonl append.

    Args:
        evidence_type: VALID_TYPES 중 하나
        session: 세션 식별자 (예: 'S211')
        eag_id: 연결 EAG ID. 없으면 None (session 필수)
        payload_ref: 실제 증거 경로 (절대 또는 ARSS_ROOT 기준 상대)
        collector: 'system' | 'caddy' | 'jeni'
        metadata: 타입별 확장 필드 (선택)

    Returns:
        생성된 AES Record dict

    Raises:
        ValueError: 유효하지 않은 파라미터
        FileNotFoundError: payload_ref 대상 파일 미존재
    """
    # 파라미터 검증
    if evidence_type not in VALID_TYPES:
        raise ValueError(f"AES_ERROR: invalid type '{evidence_type}'. valid={VALID_TYPES}")
    if collector not in VALID_COLLECTORS:
        raise ValueError(f"AES_ERROR: invalid collector '{collector}'. valid={VALID_COLLECTORS}")
    if not session:
        raise ValueError("AES_ERROR: session required")
    if not eag_id and not session:
        raise ValueError("AES_ERROR: eag_id 없는 증거는 session 필수 (AES-OP-004)")

    # Jeni 강제 조건 1 — 참조 무결성 검증
    abs_path = _resolve_payload_path(payload_ref)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(
            f"AES_INTEGRITY_ERROR: payload_ref not found at '{abs_path}'"
        )

    # SHA256 계산
    integrity_hash = f"sha256:{_sha256_file(abs_path)}"

    # aes_index.jsonl 초기화 + chattr +a (신규 생성 시)
    _ensure_index_append_only()

    # evidence_id 생성
    evidence_id = _next_evidence_id(session)

    # AES Record 조립
    record: dict = {
        "evidence_id": evidence_id,
        "type": evidence_type,
        "session": session,
        "eag_id": eag_id,
        "timestamp": _now_iso(),
        "collector": collector,
        "payload_ref": payload_ref,
        "integrity_hash": integrity_hash,
        "metadata": metadata or {},
    }

    # aes_index.jsonl append
    _append_record(record)

    return record


def verify_evidence(evidence_id: str) -> dict:
    """
    AES Index에서 evidence_id를 찾아 무결성 재검증.
    제니 독립 검증 경로에서 호출.

    Returns:
        {"ok": bool, "evidence_id": str, "status": "PASS"|"FAIL"|"NOT_FOUND", "detail": str}
    """
    if not AES_INDEX_PATH.exists():
        return {"ok": False, "evidence_id": evidence_id,
                "status": "NOT_FOUND", "detail": "aes_index.jsonl not found"}

    record = None
    with open(AES_INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("evidence_id") == evidence_id:
                    record = r
                    break
            except Exception:
                continue

    if record is None:
        return {"ok": False, "evidence_id": evidence_id,
                "status": "NOT_FOUND", "detail": "evidence_id not in index"}

    abs_path = _resolve_payload_path(record["payload_ref"])
    if not os.path.exists(abs_path):
        return {"ok": False, "evidence_id": evidence_id,
                "status": "FAIL", "detail": f"payload_ref missing: {abs_path}"}

    actual_hash = f"sha256:{_sha256_file(abs_path)}"
    if actual_hash != record["integrity_hash"]:
        return {"ok": False, "evidence_id": evidence_id,
                "status": "FAIL",
                "detail": f"hash mismatch: expected={record['integrity_hash']} actual={actual_hash}"}

    return {"ok": True, "evidence_id": evidence_id,
            "status": "PASS", "detail": "integrity verified"}


def list_evidence(session: Optional[str] = None,
                  evidence_type: Optional[str] = None) -> list:
    """
    aes_index.jsonl에서 조건에 맞는 레코드 목록 반환.
    session 또는 evidence_type으로 필터링 가능.
    """
    if not AES_INDEX_PATH.exists():
        return []
    records = []
    with open(AES_INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if session and r.get("session") != session:
                    continue
                if evidence_type and r.get("type") != evidence_type:
                    continue
                records.append(r)
            except Exception:
                continue
    return records

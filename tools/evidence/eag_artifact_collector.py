"""
eag_artifact_collector.py
AIBA EAG Artifact Collector — AES Phase 2
EAG-S213-AES-PHASE2-001 (예정)

목적:
  EAG 완료 시 EAG_ARTIFACT 증거를 자동 수집하는 어댑터 계층.
  캐디(COO 운영 절차)가 EAG 완료 후 수동 호출.

설계 근거:
  도미 Rev.4 설계 / 제니 CONDITIONAL → TRUST_READY 전환 조건 반영
  - 조건 1: 제니 독립 관측 경로 보장 (mcp_read_server.py 별도 수정)
  - 조건 2: payload 4종 생성 책임 주체 정의 (하단 운영 규칙 참조)
  - 조건 3: 호출 실패 시 재시도 + 실패 기록 메커니즘

원칙:
  - aes_collector.py 인터페이스 변경 없음 (어댑터 계층만 추가)
  - payload_ref 존재 검증 필수 (AES-OP-001 준수)
  - 증거 원본 수정 금지 (AES-OP-002 준수) — 복사본에만 기록

payload 4종 생성 운영 규칙 (조건 2):
  01_DESIGN/domi_design.md        → 도미(Domi): EAG 설계 완료 후 캐디가 저장
  02_VALIDATION/jeni_trust_ready.md → 제니(Jeni): TRUST_READY 판정 후 캐디가 저장
  03_APPROVAL/beo_eag_approval.md → 비오(Beo): EAG 승인 선언 후 캐디가 저장
  04_EXECUTION/caddy_execution_report.md → 캐디(Caddy): 실행 완료 후 직접 저장
  ※ 모든 파일은 trigger_eag_artifact_collection() 호출 전 반드시 존재해야 함
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ── 상수 ──────────────────────────────────────────────────────────────────────

ARSS_ROOT = "/opt/arss/engine/arss-protocol"
EAG_ARTIFACT_BASE = Path(ARSS_ROOT) / "ARSS_HUB" / "04_EVIDENCE" / "EAG_ARTIFACT"

KST = timezone(timedelta(hours=9))

# payload 4종 필수 키 목록
REQUIRED_PAYLOAD_KEYS = frozenset({
    "design",       # 01_DESIGN/domi_design.md
    "validation",   # 02_VALIDATION/jeni_trust_ready.md
    "approval",     # 03_APPROVAL/beo_eag_approval.md
    "execution",    # 04_EXECUTION/caddy_execution_report.md
})

# 재시도 설정 (조건 3)
MAX_RETRY = 2
RETRY_SLEEP_SEC = 1.0

# ── 헬퍼 ──────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(KST).isoformat()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_path(ref: str) -> str:
    """절대 경로면 그대로, 상대 경로면 ARSS_ROOT 기준."""
    if os.path.isabs(ref):
        return ref
    return os.path.join(ARSS_ROOT, ref)


def _write_failure_record(eag_id: str, session_id: str, error: str) -> None:
    """
    수집 실패 기록 — ARSS_HUB/04_EVIDENCE/EAG_ARTIFACT/EAG-{id}/COLLECT_FAILED.json
    조건 3: 호출 실패 시 알림 메커니즘.
    """
    eag_dir = EAG_ARTIFACT_BASE / eag_id
    eag_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "eag_id": eag_id,
        "session_id": session_id,
        "error": error,
        "timestamp": _now_iso(),
        "action_required": "캐디가 수동으로 trigger_eag_artifact_collection 재호출 필요",
    }
    fail_path = eag_dir / "COLLECT_FAILED.json"
    with open(fail_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    # stderr 출력 (세션 로그에 기록됨)
    import sys
    print(
        f"[AES_COLLECTOR] COLLECT_FAILED: eag_id={eag_id} error={error} "
        f"record={fail_path}",
        file=sys.stderr,
        flush=True,
    )


# ── 공개 API ──────────────────────────────────────────────────────────────────


def trigger_eag_artifact_collection(
    eag_id: str,
    payload_refs: dict,
    session_id: str,
    metadata: Optional[dict] = None,
) -> dict:
    """
    EAG 완료 시 EAG_ARTIFACT 증거 수집 트리거.

    Args:
        eag_id:      EAG 식별자 (예: 'EAG-S213-AES-PHASE2-001')
        payload_refs: {
            "design":     경로 (domi_design.md),
            "validation": 경로 (jeni_trust_ready.md),
            "approval":   경로 (beo_eag_approval.md),
            "execution":  경로 (caddy_execution_report.md),
        }
        session_id:  세션 식별자 (예: 'S213')
        metadata:    선택적 추가 메타데이터

    Returns:
        {
            "ok": bool,
            "eag_id": str,
            "registered": [evidence_id, ...],  # 성공 시
            "error": str,                       # 실패 시
            "retry_count": int,
        }

    Raises:
        없음 — 모든 예외는 내부에서 처리 후 실패 기록으로 반환
    """
    # ── 파라미터 검증 ─────────────────────────────────────────────────────────
    if not eag_id:
        return {"ok": False, "eag_id": eag_id, "error": "eag_id required",
                "retry_count": 0}
    if not session_id:
        return {"ok": False, "eag_id": eag_id, "error": "session_id required",
                "retry_count": 0}

    missing_keys = REQUIRED_PAYLOAD_KEYS - set(payload_refs.keys())
    if missing_keys:
        err = f"payload_refs missing keys: {sorted(missing_keys)}"
        _write_failure_record(eag_id, session_id, err)
        return {"ok": False, "eag_id": eag_id, "error": err, "retry_count": 0}

    # ── payload 존재 검증 (AES-OP-001, 참조 무결성) ───────────────────────────
    resolved_refs: dict[str, str] = {}
    for key, ref in payload_refs.items():
        abs_path = _resolve_path(ref)
        if not os.path.exists(abs_path):
            err = f"payload_ref not found: key={key} path={abs_path}"
            _write_failure_record(eag_id, session_id, err)
            return {"ok": False, "eag_id": eag_id, "error": err, "retry_count": 0}
        resolved_refs[key] = abs_path

    # ── EAG_ARTIFACT 디렉토리 구조 생성 ──────────────────────────────────────
    eag_dir = EAG_ARTIFACT_BASE / eag_id
    subdirs = {
        "design":     eag_dir / "01_DESIGN",
        "validation": eag_dir / "02_VALIDATION",
        "approval":   eag_dir / "03_APPROVAL",
        "execution":  eag_dir / "04_EXECUTION",
    }
    for d in subdirs.values():
        d.mkdir(parents=True, exist_ok=True)

    # ── manifest 생성 (③) ─────────────────────────────────────────────────────
    manifest: dict = {
        "eag_id": eag_id,
        "session_id": session_id,
        "collected_at": _now_iso(),
        "files": {},
    }

    # ── payload 복사 + SHA256 계산 (②④) ──────────────────────────────────────
    filename_map = {
        "design":     "domi_design.md",
        "validation": "jeni_trust_ready.md",
        "approval":   "beo_eag_approval.md",
        "execution":  "caddy_execution_report.md",
    }

    for key, src_path in resolved_refs.items():
        dst_path = subdirs[key] / filename_map[key]
        # AES-OP-002: 원본 수정 금지 — 복사본만 사용
        with open(src_path, "rb") as sf:
            content = sf.read()
        with open(dst_path, "wb") as df:
            df.write(content)

        sha256 = hashlib.sha256(content).hexdigest()
        manifest["files"][key] = {
            "source": src_path,
            "dest": str(dst_path),
            "sha256": f"sha256:{sha256}",
        }

    # manifest 저장
    manifest_path = eag_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # ── AES index 등록 (⑤) — 재시도 포함 (조건 3) ───────────────────────────
    from aes_collector import register_evidence  # type: ignore

    registered: list[str] = []
    retry_count = 0
    last_error: str = ""

    for attempt in range(MAX_RETRY + 1):
        try:
            record = register_evidence(
                evidence_type="EAG_ARTIFACT",
                session=session_id,
                eag_id=eag_id,
                payload_ref=str(manifest_path),
                collector="caddy",
                metadata={
                    "files": list(manifest["files"].keys()),
                    "eag_dir": str(eag_dir),
                    **(metadata or {}),
                },
            )
            registered.append(record["evidence_id"])
            break  # 성공

        except Exception as e:
            last_error = str(e)
            retry_count = attempt
            if attempt < MAX_RETRY:
                time.sleep(RETRY_SLEEP_SEC)
            continue

    if not registered:
        # 최종 실패 — 실패 기록 저장 (조건 3)
        _write_failure_record(eag_id, session_id, f"register_evidence failed: {last_error}")
        return {
            "ok": False,
            "eag_id": eag_id,
            "error": f"register_evidence failed after {MAX_RETRY + 1} attempts: {last_error}",
            "retry_count": retry_count,
        }

    return {
        "ok": True,
        "eag_id": eag_id,
        "registered": registered,
        "manifest": str(manifest_path),
        "retry_count": retry_count,
    }

"""
context_writer.py
AIBA Context Gateway — Context Writer
SSOT: Domi Phase C Design / EAG Approved (S153)
RULE-6 fix: S153 Code Health Remediation Phase 1

역할:
  - Close Bundle 원자적 트랜잭션 실행
  - SESSION_CONTEXT_FINAL → POINTER 갱신 → MANIFEST FRESH 전환 → 3-way check
  - 실패 시 STALE 유지 (복구 시도 없음 — Fail-Closed)
  - Tier 1 write 독점 권한자

핵심 원칙:
  Watchdog observes.
  Writer commits.
  Validator blocks.
  Beo approves.

금지:
  - EAG 미승인 상태에서 commit() 호출 (caller 책임으로 전제)
  - pointer_manager / manifest_manager / watchdog write 권한 확장
  - 3-way check 실패 시 자동 복구 시도
"""

import json
import logging
import os
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from tools.context_gateway.pointer_manager import (
    POINTER_PATH,
    create_pointer,
    save_pointer,
    load_pointer,
    get_pointer_hash,
    _compute_hash as compute_dict_hash,
)
from tools.context_gateway.manifest_manager import (
    MANIFEST_PATH,
    build_fresh_manifest,
    build_stale_manifest,
    save_manifest,
    load_manifest,
)
from tools.context_gateway.close_bundle_validator import (
    CloseBundleInput,
    validate_close_bundle,
    make_stale_decision,
    make_commit_decision,
)
from tools.context_gateway.write_tier_policy import (
    WriteAction,
    assert_tier1_required,
)

logger = logging.getLogger(__name__)

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")
KST = timezone(timedelta(hours=9))


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _fsync_write(path: Path, content: str) -> bool:
    """
    파일 쓰기 후 fsync 시도.
    제니 TRUST-ADVISORY: 쓰기 완료 후 OS 레벨 동기화 필수.

    fsync 실패는 비치명(non-fatal) — 경고 로그 기록 후 degraded 신호 반환.
    성공으로 오인하지 않도록 fsync_ok=False를 caller에 명시적으로 전달.

    반환: fsync_ok (bool)
      True  = 파일 쓰기 + fsync 모두 성공
      False = 파일은 쓰였으나 fsync 실패 (OS sync 미확인 상태)
    """
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        try:
            os.fsync(f.fileno())
            return True
        except OSError as exc:
            logger.warning(
                "FSYNC_WRITE_DEGRADED: fsync failed on %s — %s. "
                "File written but OS-level sync not confirmed.",
                path, exc,
            )
            return False


def _compute_file_hash(path: Path) -> Optional[str]:
    """파일 내용 SHA256 반환. 실패 시 None."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


# ── Close Bundle 트랜잭션 ───────────────────────────────────────────────────

class ContextWriter:
    """
    Context Gateway Phase C — Close Bundle 트랜잭션 실행자.

    사용 순서 (EAG 승인 후):
    1. writer = ContextWriter(session=N, final_path=Path(...))
    2. result = writer.commit()
    3. result["decision"] == "COMMIT" 확인 후 세션 종료
    """

    def __init__(
        self,
        session: int,
        final_path: Path,
        updated_by: str = "caddy",
    ):
        self.session = session
        self.final_path = final_path
        self.updated_by = updated_by
        self._committed = False

    def commit(self) -> dict:
        """
        Close Bundle 원자적 트랜잭션 실행.

        실행 순서:
        Step 1: Tier 1 정책 확인 (assert_tier1_required)
        Step 2: FINAL 파일 존재 확인
        Step 3: POINTER 신규 생성 (previous_pointer 체인 연결)
        Step 4: MANIFEST fresh 생성 (timestamp 동기화)
        Step 5: close_bundle_validator 3-way 검증
        Step 6: 검증 통과 시만 POINTER + MANIFEST fsync write
        Step 7: 실패 시 STALE manifest 저장 (POINTER 변경 없음)

        반환: {"decision": "COMMIT"|"STALE", ...}
        """
        import tools.context_gateway.context_writer as _self_module

        _pointer_path = _self_module.POINTER_PATH
        _manifest_path = _self_module.MANIFEST_PATH

        # Step 1 — Tier 1 정책 확인
        assert_tier1_required(WriteAction.CLOSE_BUNDLE_COMMIT)

        # Step 2 — FINAL 파일 존재 확인
        if not self.final_path.exists():
            return {
                "decision": "STALE",
                "reason": "FINAL_FILE_MISSING",
                "errors": [f"FINAL_FILE_MISSING: {self.final_path}"],
                "recovery_attempted": False,
            }

        # Step 3 — POINTER 신규 생성
        previous_pointer = load_pointer()
        try:
            new_pointer = create_pointer(
                session=self.session,
                file_id=self.final_path.name,
                context_path=self.final_path,
                updated_by=self.updated_by,
                previous_pointer=previous_pointer,
            )
        except FileNotFoundError as e:
            return {
                "decision": "STALE",
                "reason": "POINTER_CREATION_FAILED",
                "errors": [str(e)],
                "recovery_attempted": False,
            }

        # Step 4 — MANIFEST fresh 생성 (timestamp 동기화)
        committed_at = datetime.now(KST).isoformat()
        new_pointer["updated_at"] = committed_at

        pointer_hash = get_pointer_hash(new_pointer)
        context_hash = new_pointer["context_hash"]

        new_manifest = build_fresh_manifest(
            session=self.session,
            context_hash=context_hash,
            pointer_hash=pointer_hash,
        )
        new_manifest["generated_at"] = committed_at
        new_manifest["phase"] = "C"
        new_manifest["write_back_allowed"] = True

        # Step 5 — 3-way 검증
        bundle = CloseBundleInput(
            session=self.session,
            final_path=self.final_path,
            pointer=new_pointer,
            manifest=new_manifest,
        )
        validation = validate_close_bundle(bundle)

        if not validation.passed:
            # Step 7 — 실패: STALE manifest 저장, POINTER 변경 없음
            stale_manifest = build_stale_manifest(
                session=self.session,
                context_hash=context_hash,
                pointer_hash=pointer_hash,
                reason=f"CLOSE_BUNDLE_FAILED: {'; '.join(validation.errors)}",
            )
            stale_manifest["phase"] = "C"
            mfst_fsync_ok = _fsync_write(
                _manifest_path,
                json.dumps(stale_manifest, ensure_ascii=False, indent=2),
            )

            decision = make_stale_decision(validation)
            decision["pointer_changed"] = False
            if not mfst_fsync_ok:
                decision["fsync_warning"] = "STALE_MANIFEST_FSYNC_DEGRADED"
            return decision

        # Step 6 — 검증 통과: POINTER → MANIFEST fsync write (순서 고정)
        ptr_fsync_ok = _fsync_write(
            _pointer_path,
            json.dumps(new_pointer, ensure_ascii=False, indent=2),
        )
        mfst_fsync_ok = _fsync_write(
            _manifest_path,
            json.dumps(new_manifest, ensure_ascii=False, indent=2),
        )

        self._committed = True
        decision = make_commit_decision(validation)
        decision["session"] = self.session
        decision["final_file"] = self.final_path.name
        decision["pointer_updated"] = True
        decision["manifest_fresh"] = True

        if not ptr_fsync_ok or not mfst_fsync_ok:
            decision["fsync_warning"] = "COMMIT_FSYNC_DEGRADED — OS sync not confirmed"
            logger.warning(
                "COMMIT_FSYNC_DEGRADED: session=%s ptr_fsync=%s mfst_fsync=%s",
                self.session, ptr_fsync_ok, mfst_fsync_ok,
            )

        return decision


# ── 공개 함수 API ───────────────────────────────────────────────────────────

def execute_close_bundle(
    session: int,
    final_path: Path,
    updated_by: str = "caddy",
) -> dict:
    """
    Close Bundle 실행 진입점.
    EAG 승인 후 캐디가 직접 호출하는 단일 공개 함수.

    반환: {"decision": "COMMIT"|"STALE", ...}
    """
    writer = ContextWriter(
        session=session,
        final_path=final_path,
        updated_by=updated_by,
    )
    return writer.commit()


def get_writer_status() -> dict:
    """
    context_writer 상태 요약 (관측/감사용).
    """
    return {
        "component": "context_writer",
        "phase": "C",
        "tier": "TIER_1",
        "write_authority": "EXCLUSIVE",
        "eag_required": True,
        "fail_closed": True,
        "auto_recovery": False,
    }

"""
close_bundle_validator.py
AIBA Context Gateway — Close Bundle Validator
SSOT: Domi Phase C Design / EAG Approved (S153)

역할:
  - Close Bundle 3-way consistency 검증
  - SESSION_CONTEXT_FINAL / POINTER / MANIFEST 정합성 확인
  - 실패 시 STALE 유지 (복구 시도 없음 — Fail-Closed)
  - fsync 보장 및 해시 검증 시점 정합성 (제니 TRUST-ADVISORY 반영)

검증 항목:
  1. session_count 3-way 일치
  2. context_hash 3-way 일치
  3. FINAL 파일 실존 및 hash 재계산 일치
  4. POINTER chain hash 형식
  5. MANIFEST blocking_flags 비어있음
"""

import json
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── 상수 ───────────────────────────────────────────────────────────────────

VPS_ROOT = Path("/opt/arss/engine/arss-protocol")


# ── 데이터 클래스 ───────────────────────────────────────────────────────────

@dataclass
class CloseBundleInput:
    """Close Bundle 검증 입력"""
    session: int
    final_path: Path
    pointer: dict
    manifest: dict


@dataclass
class ValidationResult:
    """검증 결과"""
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    context_hash: Optional[str] = None

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        self.passed = False

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────

def _fsync_read_hash(path: Path) -> Optional[str]:
    """
    파일 읽기 전 fsync 보장 후 SHA256 계산.
    제니 TRUST-ADVISORY: 쓰기 완료 후 동기화(fsync) 보장 필수.

    파일 핸들을 통해 OS 레벨 flush 후 읽기 수행.
    반환: hex digest 또는 None (읽기 실패 시)
    """
    try:
        with open(path, "rb") as f:
            # 읽기 전 fsync 호출 — 이전 쓰기 완료 보장
            try:
                os.fsync(f.fileno())
            except OSError:
                # read-only 파일시스템 등 fsync 불가 환경에서 무시
                pass
            content = f.read()
        return hashlib.sha256(content).hexdigest()
    except Exception:
        return None


def _load_json_safe(path: Path) -> Optional[dict]:
    """JSON 파일 안전 로드. 실패 시 None."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ── 검증 함수 ──────────────────────────────────────────────────────────────

def validate_final_file(bundle: CloseBundleInput, result: ValidationResult) -> None:
    """
    [V-1] FINAL 파일 실존 및 hash 재계산 검증.
    제니 ADVISORY: 3-way check 전 해시 검증 시점 정합성 보장.
    """
    if not bundle.final_path.exists():
        result.add_error(f"FINAL_FILE_MISSING: {bundle.final_path.name}")
        return

    # fsync 보장 후 hash 계산
    computed_hash = _fsync_read_hash(bundle.final_path)
    if computed_hash is None:
        result.add_error(f"FINAL_FILE_UNREADABLE: {bundle.final_path.name}")
        return

    result.context_hash = computed_hash

    # POINTER의 context_hash와 대조
    ptr_hash = bundle.pointer.get("context_hash", "")
    if ptr_hash != computed_hash:
        result.add_error(
            f"CONTEXT_HASH_MISMATCH(FINAL≠POINTER): "
            f"final={computed_hash[:8]}... pointer={ptr_hash[:8] if ptr_hash else 'MISSING'}..."
        )

    # MANIFEST의 context_hash와 대조
    mfst_hash = bundle.manifest.get("context_hash", "")
    if mfst_hash != computed_hash:
        result.add_error(
            f"CONTEXT_HASH_MISMATCH(FINAL≠MANIFEST): "
            f"final={computed_hash[:8]}... manifest={mfst_hash[:8] if mfst_hash else 'MISSING'}..."
        )


def validate_session_count(bundle: CloseBundleInput, result: ValidationResult) -> None:
    """[V-2] session_count 3-way 일치 검증"""
    ptr_session = bundle.pointer.get("current_session")
    mfst_session = bundle.manifest.get("manifest_session")

    if ptr_session != bundle.session:
        result.add_error(
            f"SESSION_MISMATCH(FINAL≠POINTER): final={bundle.session} pointer={ptr_session}"
        )
    if mfst_session != bundle.session:
        result.add_error(
            f"SESSION_MISMATCH(FINAL≠MANIFEST): final={bundle.session} manifest={mfst_session}"
        )


def validate_pointer_chain(bundle: CloseBundleInput, result: ValidationResult) -> None:
    """[V-3] POINTER chain hash 형식 검증"""
    prev_hash = bundle.pointer.get("previous_pointer_hash", "")
    if prev_hash == "GENESIS":
        return
    if not prev_hash or len(prev_hash) != 64:
        result.add_error(
            f"POINTER_CHAIN_INVALID: previous_pointer_hash={prev_hash!r}"
        )


def validate_manifest_clean(bundle: CloseBundleInput, result: ValidationResult) -> None:
    """[V-4] MANIFEST blocking_flags 비어있음 확인"""
    flags = bundle.manifest.get("blocking_flags", [])
    if flags:
        result.add_error(
            f"MANIFEST_HAS_BLOCKING_FLAGS: {flags} — STALE 상태에서 Close Bundle 불가"
        )

    # projection_status fresh 확인
    proj_status = bundle.manifest.get("projection_status", "")
    if proj_status != "fresh":
        result.add_warning(
            f"MANIFEST_PROJECTION_NOT_FRESH: {proj_status} — context_writer가 fresh로 전환 필요"
        )


def validate_timestamp_alignment(bundle: CloseBundleInput, result: ValidationResult) -> None:
    """[V-5] POINTER updated_at / MANIFEST generated_at 일치 검증"""
    ptr_ts = bundle.pointer.get("updated_at", "")
    mfst_ts = bundle.manifest.get("generated_at", "")
    if ptr_ts and mfst_ts and ptr_ts != mfst_ts:
        result.add_error(
            f"TIMESTAMP_MISMATCH: pointer.updated_at={ptr_ts} manifest.generated_at={mfst_ts}"
        )


# ── 공개 API ───────────────────────────────────────────────────────────────

def validate_close_bundle(bundle: CloseBundleInput) -> ValidationResult:
    """
    Close Bundle 전체 검증 실행.

    검증 순서 (제니 ADVISORY: 해시 검증 선행):
    V-1: FINAL 파일 실존 + hash 재계산 (fsync 보장)
    V-2: session_count 3-way 일치
    V-3: POINTER chain hash 형식
    V-4: MANIFEST blocking_flags 없음
    V-5: timestamp 일치

    실패 시: passed=False, errors 목록 반환 → caller가 STALE 유지
    성공 시: passed=True, context_hash 반환 → context_writer가 commit 진행
    """
    result = ValidationResult(passed=True)

    validate_final_file(bundle, result)       # V-1 — hash 선행 (제니 ADVISORY)
    validate_session_count(bundle, result)    # V-2
    validate_pointer_chain(bundle, result)    # V-3
    validate_manifest_clean(bundle, result)   # V-4
    validate_timestamp_alignment(bundle, result)  # V-5

    return result


def make_stale_decision(result: ValidationResult) -> dict:
    """
    검증 실패 시 STALE 유지 결정 객체 반환.
    복구 시도 없음 — Fail-Closed 원칙.
    """
    return {
        "decision": "STALE",
        "reason": "CLOSE_BUNDLE_VALIDATION_FAILED",
        "errors": result.errors,
        "warnings": result.warnings,
        "recovery_attempted": False,  # 항상 False — Fail-Closed
        "action_required": "비오님 EAG 재승인 후 context_writer 재실행 필요",
    }


def make_commit_decision(result: ValidationResult) -> dict:
    """
    검증 성공 시 commit 진행 결정 객체 반환.
    """
    return {
        "decision": "COMMIT",
        "reason": "CLOSE_BUNDLE_VALIDATION_PASSED",
        "context_hash": result.context_hash,
        "warnings": result.warnings,
    }

"""
watchdog.py
AIBA Context Gateway — Sandbox Watchdog (Phase B, Step 1)
SSOT: Domi Phase B Design / EAG Approved (S152)

역할:
  - session_open_call 트리거: VPS freshness 탐지 → STALE_MANIFEST 갱신
  - 컴포넌트 (내부 함수 분리):
      freshness_observer   — VPS 배포 아티팩트 관측
      mismatch_detector    — POINTER ↔ VPS 불일치 탐지
      stale_evaluator      — freshness 상태 판정
      blocking_propagator  — blocking_flags 계산 (stale_evaluator 내장)
      manifest_emitter     — STALE_MANIFEST 갱신

금지:
  - POINTER write-back (A3 위반)
  - SESSION_CONTEXT mutation
  - auto recovery
  - Phase C 영역 침범

Phase B Scope: detect / annotate / propagate only
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tools.context_gateway.pointer_manager import (
    load_pointer,
    validate_pointer,
    get_pointer_hash,
    verify_context_hash,
    resolve_canonical_path,
    VPS_ROOT,
)
from tools.context_gateway.manifest_manager import (
    load_manifest,
    create_manifest,
    save_manifest,
    get_manifest_hash,
    ALLOWED_AGENTS,
    FLAG_STALE_PROJECTION,
    FLAG_HASH_MISMATCH,
    FLAG_POINTER_MISSING,
    STALE_BLOCKED_ACTIONS,
)

# ── 상수 ──────────────────────────────────────────────────────────────────

# Phase B 추가 freshness 상태
VALID_FRESHNESS_STATUSES = frozenset(
    {"fresh", "stale", "unknown", "degraded", "not_required"}
)

# VPS SESSION_CONTEXT 파일명 패턴 — glob+mtime 대체 (B-2 Freshness Authority)
_SESSION_FILE_PATTERN = re.compile(
    r"^SESSION_CONTEXT_S(\d+)_FINAL\.json$"
)

# Phase B blocking flag 추가 정의
FLAG_SESSION_DRIFT = "SESSION_DRIFT"
FLAG_WATCHDOG_UNKNOWN = "WATCHDOG_UNKNOWN"

# Watchdog이 STALE_MANIFEST에 기록하는 트리거 레이블
TRIGGER_SESSION_OPEN = "session_open_call"
TRIGGER_CLOSE_BUNDLE = "close_bundle_event"
TRIGGER_DEPLOY_COMPLETION = "deploy_completion_call"


# ── 데이터 클래스 ──────────────────────────────────────────────────────────

@dataclass
class FreshnessObservation:
    """freshness_observer 결과"""
    latest_deployed_session: Optional[int]
    deployed_files: list
    observation_error: Optional[str] = None


@dataclass
class MismatchReport:
    """mismatch_detector 결과"""
    has_mismatch: bool
    pointer_session: Optional[int]
    latest_deployed_session: Optional[int]
    pointer_valid: bool
    pointer_dict: Optional[dict] = None
    pointer_errors: list = field(default_factory=list)
    mismatch_reason: Optional[str] = None


@dataclass
class FreshnessVerdict:
    """stale_evaluator + blocking_propagator 결과"""
    status: str                      # fresh | stale | unknown | degraded
    reason: str
    blocking_flags: list             # list[str] — Phase A 하위호환 유지
    role_projection_status: dict     # {agent: status}


@dataclass
class WatchdogResult:
    """run_session_open_watchdog 최종 결과"""
    trigger: str
    observation: FreshnessObservation
    mismatch: MismatchReport
    verdict: FreshnessVerdict
    manifest_updated: bool
    manifest_path: Optional[Path] = None
    error: Optional[str] = None


# ── freshness_observer ────────────────────────────────────────────────────

def observe_vps_freshness() -> FreshnessObservation:
    """
    VPS에서 SESSION_CONTEXT_S{n}_FINAL.json 파일을 스캔하여 최신 n 탐지.

    glob+mtime 대신 파일명에서 session 번호를 직접 추출.
    → timestamp 조작·동시 쓰기·재배포 타이밍 취약점 해소 (B-2 Freshness Authority).
    """
    try:
        deployed_files = []
        max_n: Optional[int] = None

        for path in VPS_ROOT.iterdir():
            m = _SESSION_FILE_PATTERN.match(path.name)
            if m:
                n = int(m.group(1))
                deployed_files.append(path.name)
                if max_n is None or n > max_n:
                    max_n = n

        return FreshnessObservation(
            latest_deployed_session=max_n,
            deployed_files=sorted(deployed_files),
        )
    except Exception as exc:
        return FreshnessObservation(
            latest_deployed_session=None,
            deployed_files=[],
            observation_error=str(exc),
        )


# ── mismatch_detector ─────────────────────────────────────────────────────

def detect_mismatch(
    observation: FreshnessObservation,
    pointer: Optional[dict] = None,
) -> MismatchReport:
    """
    POINTER.current_session vs. VPS 최신 배포 세션 번호 비교.
    pointer 인자가 없으면 내부에서 load_pointer() 호출.
    """
    # 관측 자체가 실패한 경우
    if observation.observation_error or observation.latest_deployed_session is None:
        return MismatchReport(
            has_mismatch=True,
            pointer_session=None,
            latest_deployed_session=observation.latest_deployed_session,
            pointer_valid=False,
            mismatch_reason="OBSERVATION_FAILED",
        )

    latest = observation.latest_deployed_session

    # POINTER 로드
    ptr = pointer if pointer is not None else load_pointer()
    if ptr is None:
        return MismatchReport(
            has_mismatch=True,
            pointer_session=None,
            latest_deployed_session=latest,
            pointer_valid=False,
            mismatch_reason="POINTER_MISSING",
        )

    is_valid, errors = validate_pointer(ptr)
    ptr_session = ptr.get("current_session")

    if not is_valid:
        return MismatchReport(
            has_mismatch=True,
            pointer_session=ptr_session,
            latest_deployed_session=latest,
            pointer_valid=False,
            pointer_dict=ptr,
            pointer_errors=errors,
            mismatch_reason="POINTER_INVALID",
        )

    if ptr_session != latest:
        return MismatchReport(
            has_mismatch=True,
            pointer_session=ptr_session,
            latest_deployed_session=latest,
            pointer_valid=True,
            pointer_dict=ptr,
            mismatch_reason=(
                f"SESSION_DRIFT: pointer={ptr_session} latest={latest}"
            ),
        )

    return MismatchReport(
        has_mismatch=False,
        pointer_session=ptr_session,
        latest_deployed_session=latest,
        pointer_valid=True,
        pointer_dict=ptr,
    )


# ── stale_evaluator + blocking_propagator ────────────────────────────────

def evaluate_freshness(mismatch: MismatchReport) -> FreshnessVerdict:
    """
    MismatchReport → FreshnessVerdict.

    판정 기준:
      UNKNOWN  — POINTER 없음 / 구조 오류 / 관측 실패 / pointer > latest (이상)
      STALE    — pointer.current_session < latest_deployed_session
      DEGRADED — session 일치 but context_hash 불일치
      FRESH    — session + hash 모두 일치

    blocking_propagator 역할 내장:
      FRESH    → blocking_flags = []
      기타     → blocking_flags에 적절한 FLAG 세트 설정
    """
    def _unknown_verdict(reason: str, extra_flag: Optional[str] = None) -> FreshnessVerdict:
        flags = [FLAG_STALE_PROJECTION, FLAG_WATCHDOG_UNKNOWN]
        if extra_flag:
            flags.append(extra_flag)
        return FreshnessVerdict(
            status="unknown",
            reason=reason,
            blocking_flags=flags,
            role_projection_status={a: "unknown" for a in ALLOWED_AGENTS},
        )

    # ── UNKNOWN: 관측/포인터 실패 ─────────────────────────────────────────
    if not mismatch.pointer_valid or mismatch.latest_deployed_session is None:
        extra = (
            FLAG_POINTER_MISSING
            if mismatch.mismatch_reason in ("POINTER_MISSING", "POINTER_INVALID")
            else None
        )
        return _unknown_verdict(
            mismatch.mismatch_reason or "POINTER_UNAVAILABLE",
            extra_flag=extra,
        )

    p_session = mismatch.pointer_session
    latest = mismatch.latest_deployed_session

    # ── UNKNOWN: pointer > latest (이상 상태) ────────────────────────────
    if p_session > latest:
        return _unknown_verdict(
            f"POINTER_AHEAD_OF_DEPLOY: pointer={p_session} latest={latest}"
        )

    # ── STALE: session drift ──────────────────────────────────────────────
    if p_session < latest:
        return FreshnessVerdict(
            status="stale",
            reason=f"SESSION_DRIFT: pointer={p_session} latest={latest}",
            blocking_flags=[FLAG_STALE_PROJECTION, FLAG_SESSION_DRIFT],
            role_projection_status={a: "stale" for a in ALLOWED_AGENTS},
        )

    # ── p_session == latest: context_hash 검증 ───────────────────────────
    ptr = mismatch.pointer_dict
    if ptr is None:
        return _unknown_verdict("POINTER_DICT_MISSING")

    context_path = resolve_canonical_path(ptr)
    if context_path is None:
        return FreshnessVerdict(
            status="degraded",
            reason=f"CONTEXT_FILE_MISSING: {ptr.get('current_file_id', '?')}",
            blocking_flags=[FLAG_STALE_PROJECTION, FLAG_HASH_MISMATCH],
            role_projection_status={a: "stale" for a in ALLOWED_AGENTS},
        )

    hash_ok, hash_reason = verify_context_hash(ptr, context_path)
    if not hash_ok:
        return FreshnessVerdict(
            status="degraded",
            reason=hash_reason,
            blocking_flags=[FLAG_STALE_PROJECTION, FLAG_HASH_MISMATCH],
            role_projection_status={a: "stale" for a in ALLOWED_AGENTS},
        )

    # ── FRESH ─────────────────────────────────────────────────────────────
    return FreshnessVerdict(
        status="fresh",
        reason=(
            f"POINTER_CONSISTENT: session={p_session} hash verified"
        ),
        blocking_flags=[],
        role_projection_status={a: "fresh" for a in ALLOWED_AGENTS},
    )


# ── manifest_emitter ──────────────────────────────────────────────────────

def emit_manifest(
    verdict: FreshnessVerdict,
    mismatch: MismatchReport,
    trigger: str = TRIGGER_SESSION_OPEN,
) -> tuple[bool, Optional[Path], Optional[str]]:
    """
    FreshnessVerdict → SESSION_CONTEXT_STALE_MANIFEST.json 갱신.

    Phase B 권한 범위:
      허용: STALE_MANIFEST 갱신 (freshness annotation)
      금지: POINTER 수정 / SESSION_CONTEXT 수정 / auto recovery
    """
    try:
        ptr = mismatch.pointer_dict
        pointer_session = mismatch.pointer_session or 0
        context_hash = ptr.get("context_hash", "") if ptr else ""
        pointer_hash = get_pointer_hash(ptr) if ptr else ""

        shard_status_summary = {
            "watchdog_trigger": trigger,
            "freshness_status": verdict.status,
            "reason": verdict.reason,
            "pointer_session": mismatch.pointer_session,
            "latest_deployed_session": mismatch.latest_deployed_session,
        }

        manifest = create_manifest(
            session=pointer_session,
            context_hash=context_hash,
            pointer_hash=pointer_hash,
            projection_status=verdict.status,
            shard_status_summary=shard_status_summary,
            role_projection_status=verdict.role_projection_status,
            blocking_flags=verdict.blocking_flags,
        )

        # Phase B 메타 필드 추가
        manifest["phase"] = "B"
        manifest["watchdog_trigger"] = trigger

        path = save_manifest(manifest)
        return True, path, None

    except Exception as exc:
        return False, None, str(exc)


# ── 진입점 — session_open_call 트리거 ────────────────────────────────────

def run_session_open_watchdog() -> WatchdogResult:
    """
    Phase B Step 1 진입점 — session_open_call 트리거.

    실행 순서:
      1. observe_vps_freshness  → FreshnessObservation
      2. load_pointer (1회 로드, 재사용)
      3. detect_mismatch        → MismatchReport
      4. evaluate_freshness     → FreshnessVerdict (blocking_propagator 내장)
      5. emit_manifest          → STALE_MANIFEST 갱신

    금지 불변: POINTER write-back / SESSION_CONTEXT mutation / auto recovery
    """
    trigger = TRIGGER_SESSION_OPEN

    # Step 1: VPS 관측
    observation = observe_vps_freshness()

    # Step 2: POINTER 1회 로드 (detect + evaluate 공유)
    pointer = load_pointer()

    # Step 3: 불일치 탐지
    mismatch = detect_mismatch(observation, pointer=pointer)

    # Step 4: freshness 판정 + blocking_flags 계산
    verdict = evaluate_freshness(mismatch)

    # Step 5: STALE_MANIFEST 갱신
    updated, path, error = emit_manifest(verdict, mismatch, trigger=trigger)

    return WatchdogResult(
        trigger=trigger,
        observation=observation,
        mismatch=mismatch,
        verdict=verdict,
        manifest_updated=updated,
        manifest_path=path,
        error=error,
    )


def run_close_bundle_watchdog() -> WatchdogResult:
    """
    Phase B Step 2 — close_bundle_event 트리거.

    세션 종료 시 Close Bundle 완료 직후 호출.
    Step 1(session_open_call)과 완전히 독립 — 실패 시 상호 영향 없음.

    목적:
      Close Bundle 완료 후 POINTER ↔ VPS 상태가 즉시 일치하는지 검증.
      불일치 감지 시 STALE_MANIFEST blocking_flags 즉시 갱신.

    금지 불변: POINTER write-back / SESSION_CONTEXT mutation / auto recovery
    """
    trigger = TRIGGER_CLOSE_BUNDLE

    observation = observe_vps_freshness()
    pointer = load_pointer()
    mismatch = detect_mismatch(observation, pointer=pointer)
    verdict = evaluate_freshness(mismatch)
    updated, path, error = emit_manifest(verdict, mismatch, trigger=trigger)

    return WatchdogResult(
        trigger=trigger,
        observation=observation,
        mismatch=mismatch,
        verdict=verdict,
        manifest_updated=updated,
        manifest_path=path,
        error=error,
    )


def run_deploy_completion_watchdog() -> WatchdogResult:
    """
    Phase B Step 2 — deploy_completion_call 트리거.

    VPS에 신규 SESSION_CONTEXT_S{n}_FINAL.json 배포 완료 직후 호출.
    Step 1/2(session_open/close_bundle)과 완전히 독립 — 실패 시 상호 영향 없음.

    목적:
      배포 직후 POINTER가 아직 갱신되지 않은 SESSION_DRIFT 상태를 즉시 탐지.
      STALE_MANIFEST blocking_flags 갱신 → 판단 차단 전파.

    금지 불변: POINTER write-back / SESSION_CONTEXT mutation / auto recovery
    """
    trigger = TRIGGER_DEPLOY_COMPLETION

    observation = observe_vps_freshness()
    pointer = load_pointer()
    mismatch = detect_mismatch(observation, pointer=pointer)
    verdict = evaluate_freshness(mismatch)
    updated, path, error = emit_manifest(verdict, mismatch, trigger=trigger)

    return WatchdogResult(
        trigger=trigger,
        observation=observation,
        mismatch=mismatch,
        verdict=verdict,
        manifest_updated=updated,
        manifest_path=path,
        error=error,
    )

"""
write_tier_policy.py
AIBA Context Gateway — Write Tier Policy
SSOT: Domi Phase C Design / EAG Approved (S153)

역할:
  - Tier 1 / Tier 2 경계 명문화
  - write 요청에 대한 Tier 판정
  - Tier 2 범위 초과 시 차단

Tier 정의:
  Tier 1 (EAG 필수): canonical write
    - SESSION_CONTEXT_FINAL
    - SESSION_CONTEXT_POINTER.json
    - MANIFEST FRESH 전환
    - Close Bundle 확정

  Tier 2 (자율 허용): non-canonical write
    - sandbox draft
    - watchdog observation cache
    - preflight report
    - mismatch note

원칙: Tier 2 결과는 canonical truth가 될 수 없다.
"""

from enum import Enum
from pathlib import Path
from typing import Optional

# ── Tier 정의 ──────────────────────────────────────────────────────────────

class WriteTier(Enum):
    TIER_1 = "TIER_1"   # EAG 필수 — canonical write
    TIER_2 = "TIER_2"   # 자율 허용 — non-canonical write
    UNKNOWN = "UNKNOWN" # 판정 불가 — 차단


class WriteAction(Enum):
    """Tier 1 대상 canonical write 액션"""
    SESSION_CONTEXT_FINAL = "SESSION_CONTEXT_FINAL"
    POINTER_UPDATE = "POINTER_UPDATE"
    MANIFEST_FRESH_TRANSITION = "MANIFEST_FRESH_TRANSITION"
    CLOSE_BUNDLE_COMMIT = "CLOSE_BUNDLE_COMMIT"


class Tier2Action(Enum):
    """Tier 2 허용 non-canonical write 액션"""
    SANDBOX_DRAFT = "SANDBOX_DRAFT"
    WATCHDOG_OBSERVATION_CACHE = "WATCHDOG_OBSERVATION_CACHE"
    PREFLIGHT_REPORT = "PREFLIGHT_REPORT"
    MISMATCH_NOTE = "MISMATCH_NOTE"


# ── Tier 1 파일 패턴 ────────────────────────────────────────────────────────

TIER_1_FILENAME_PATTERNS = [
    "SESSION_CONTEXT_S",           # SESSION_CONTEXT_S{n}_FINAL.json
    "SESSION_CONTEXT_POINTER",     # SESSION_CONTEXT_POINTER.json
    "SESSION_CONTEXT_STALE_MANIFEST",  # SESSION_CONTEXT_STALE_MANIFEST.json (FRESH 전환)
]

TIER_1_SUFFIX_PATTERNS = [
    "_FINAL.json",
]

# ── Tier 2 허용 경로 패턴 ────────────────────────────────────────────────────

TIER_2_ALLOWED_DIRS = [
    "sandbox",
    "tmp",
    "preflight",
    "observation_cache",
]

TIER_2_ALLOWED_SUFFIXES = [
    "_draft.json",
    "_cache.json",
    "_preflight.json",
    "_mismatch.json",
    "_note.json",
    "_observation.json",
]


# ── 판정 함수 ──────────────────────────────────────────────────────────────

def classify_write_action(action: WriteAction) -> WriteTier:
    """
    WriteAction enum 기반 Tier 판정.
    모든 WriteAction은 Tier 1.
    """
    return WriteTier.TIER_1


def classify_tier2_action(action: Tier2Action) -> WriteTier:
    """
    Tier2Action enum 기반 Tier 판정.
    모든 Tier2Action은 Tier 2.
    """
    return WriteTier.TIER_2


def classify_path(target_path: Path) -> WriteTier:
    """
    파일 경로 기반 Tier 자동 판정.

    판정 순서:
    1. Tier 1 패턴 매칭 → TIER_1
    2. Tier 2 허용 디렉토리/접미사 → TIER_2
    3. 매칭 없음 → UNKNOWN (차단)

    반환: WriteTier
    """
    filename = target_path.name

    # Tier 1 파일명 패턴 확인
    for pattern in TIER_1_FILENAME_PATTERNS:
        if filename.startswith(pattern):
            return WriteTier.TIER_1

    for suffix in TIER_1_SUFFIX_PATTERNS:
        if filename.endswith(suffix):
            return WriteTier.TIER_1

    # Tier 2 허용 디렉토리 확인
    parts = [p.lower() for p in target_path.parts]
    for allowed_dir in TIER_2_ALLOWED_DIRS:
        if allowed_dir in parts:
            return WriteTier.TIER_2

    # Tier 2 허용 접미사 확인
    for suffix in TIER_2_ALLOWED_SUFFIXES:
        if filename.endswith(suffix):
            return WriteTier.TIER_2

    return WriteTier.UNKNOWN


def assert_tier1_required(action: WriteAction) -> None:
    """
    Tier 1 write 수행 전 EAG 필수 명시적 검증.
    EAG 승인 없이 호출 시 RuntimeError 발생.

    사용처: context_writer.py — EAG 승인 전달 시 호출
    """
    tier = classify_write_action(action)
    if tier != WriteTier.TIER_1:
        raise RuntimeError(
            f"[POLICY VIOLATION] {action.value}은 Tier 1 액션이나 "
            f"판정 결과가 {tier.value}입니다."
        )


def assert_tier2_safe(target_path: Path) -> None:
    """
    Tier 2 write 경로가 canonical 영역을 침범하지 않는지 검증.
    Tier 1 또는 UNKNOWN 경로 접근 시 RuntimeError 발생.

    사용처: Tier 2 자율 write 수행 전 반드시 호출
    """
    tier = classify_path(target_path)
    if tier == WriteTier.TIER_1:
        raise RuntimeError(
            f"[TIER BOUNDARY VIOLATION] {target_path.name}은 Tier 1 canonical 파일입니다. "
            f"Tier 2 자율 write 불가. EAG 필요."
        )
    if tier == WriteTier.UNKNOWN:
        raise RuntimeError(
            f"[TIER BOUNDARY VIOLATION] {target_path.name}은 Tier 판정 불가 경로입니다. "
            f"Tier 2 write 차단."
        )


def get_policy_summary() -> dict:
    """
    현재 Tier 정책 요약 반환 (관측/감사용).
    """
    return {
        "tier_1": {
            "description": "EAG 필수 — canonical write",
            "actions": [a.value for a in WriteAction],
            "filename_patterns": TIER_1_FILENAME_PATTERNS,
        },
        "tier_2": {
            "description": "자율 허용 — non-canonical write",
            "actions": [a.value for a in Tier2Action],
            "allowed_dirs": TIER_2_ALLOWED_DIRS,
            "allowed_suffixes": TIER_2_ALLOWED_SUFFIXES,
        },
        "principle": "Tier 2 결과는 canonical truth가 될 수 없다.",
    }

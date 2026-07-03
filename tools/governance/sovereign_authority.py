#!/usr/bin/env python3
"""
sovereign_authority.py v1.0.0
AIF Area 5: Beo Sovereign Authority (Constitutional Override)
EAG: EAG-S320-AIF-AREA5-001

멄오님의 최고 권한 선언 메커니즘.
Override 발동 기록, 유효성 검증, 로그 관리를 담당합니다.

허용 Override 대상:
  - DEP 절차 (설계·판정 순서)
  - EAG 승인 요건
  - 에이전트 역할 규칙
  - OI 보류 조건
  - 작업 우선순위

Override 불가 대상 (IMMUTABLE):
  - chain.tip / context_hash 무결성
  - govdoc_freeze_gate 통과 요건
  - SC_FINAL 직접 변조
"""
import json
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"
EAG_ID  = "EAG-S320-AIF-AREA5-001"

ROOT     = Path("/opt/arss/engine/arss-protocol")
LOG_PATH = ROOT / "tools/governance/sovereign_override_log.jsonl"

# Override 불가 범위 (IMMUTABLE) — PROJECT INSTRUCTIONS AUTHORITY 조항
_IMMUTABLE_SCOPES = frozenset([
    "chain_integrity",
    "context_hash",
    "govdoc_freeze_gate",
    "ssot_direct_write",
    "boot_gate",
])


class OverrideDeniedError(ValueError):
    """Override 불허 범위 접근 시 발생."""
    pass


def validate_override_scope(scope: str) -> bool:
    """
    scope가 허용된 Override 대상인지 검증합니다.
    불허 범위 접근 시 OverrideDeniedError를 발생시킵니다.
    """
    if not scope or not scope.strip():
        raise ValueError("scope cannot be empty")
    scope_key = scope.strip().lower().replace("-", "_").replace(" ", "_")
    if scope_key in _IMMUTABLE_SCOPES:
        raise OverrideDeniedError(
            f"Override DENIED: '{scope}' is IMMUTABLE. "
            f"Chain/hash/SSOT/freeze_gate integrity cannot be overridden "
            f"even by Beo (PROJECT INSTRUCTIONS AUTHORITY)."
        )
    return True


def record_override(
    eag: str,
    scope: str,
    target: str,
    rationale: str,
) -> dict:
    """
    Override 선언을 sovereign_override_log.jsonl에 append 기록합니다.

    Args:
        eag:      EAG ID (필수)
        scope:    Override 범위
        target:   Override 대상 구체 항목
        rationale: Override 근거

    Returns:
        기록된 entry dict

    Raises:
        OverrideDeniedError: scope가 IMMUTABLE 범위인 경우
        ValueError: 필수 필드 누락
    """
    for field_name, field_val in [
        ("eag", eag), ("scope", scope),
        ("target", target), ("rationale", rationale),
    ]:
        if not field_val or not str(field_val).strip():
            raise ValueError(f"required field missing: '{field_name}'")

    validate_override_scope(scope)

    entry = {
        "schema":          "sovereign_override_v1",
        "version":         VERSION,
        "eag":             eag.strip(),
        "scope":           scope.strip(),
        "override_target": target.strip(),
        "rationale":       rationale.strip(),
        "declared_at":     datetime.now(timezone.utc).isoformat(),
        "actor":           "beo",
    }

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def get_active_overrides() -> list:
    """
    sovereign_override_log.jsonl의 전체 기록을 반환합니다.
    (append-only 구조상 모든 기록이 유효합니다.)
    """
    if not LOG_PATH.exists():
        return []
    entries = []
    with open(LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


def get_override_summary() -> dict:
    """Override 로그 요약 정보를 반환합니다."""
    overrides = get_active_overrides()
    return {
        "schema":       "sovereign_override_summary_v1",
        "version":      VERSION,
        "eag":          EAG_ID,
        "total_count":  len(overrides),
        "log_path":     str(LOG_PATH),
        "latest":       overrides[-1] if overrides else None,
    }


if __name__ == "__main__":
    import sys
    summary = get_override_summary()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0)

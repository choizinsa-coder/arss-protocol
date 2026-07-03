#!/usr/bin/env python3
"""
area_11_decision_ledger.py v1.0.0
AIF Area 11: Decision Ledger (Decision Class 4종)
EAG: EAG-S321-AIF-AREA11-13-001
DC-1 Routine / DC-2 Significant / DC-3 Critical / DC-4 Constitutional

준용: sovereign_authority.py (Area 5) 패턴
  - LOG_PATH append-only jsonl
  - record_*() 필드 검증 → entry dict → jsonl append
  - get_*() 구조 일치
  - schema, declared_at, actor 필드
"""
import json
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S321-AIF-AREA11-13-001"

ROOT     = Path("/opt/arss/engine/arss-protocol")
LOG_PATH = ROOT / "tools/governance/decision_ledger.jsonl"


class DecisionClass(Enum):
    """Decision Class 4종 -- AIF v1.3 Area 11"""
    DC1 = "DC-1"  # Routine
    DC2 = "DC-2"  # Significant
    DC3 = "DC-3"  # Critical
    DC4 = "DC-4"  # Constitutional

    @property
    def requires_eag(self) -> bool:
        """DC-3/DC-4는 EAG ID 필수"""
        return self in (DecisionClass.DC3, DecisionClass.DC4)


class DecisionLedgerError(ValueError):
    """Decision Ledger 유효성 검증 실패 시 발생."""
    pass


def validate_decision_input(
    dc: "DecisionClass",
    subject: str,
    rationale: str,
    eag: Optional[str] = None,
) -> None:
    """
    Decision 입력 필드 검증.
    DC-3/DC-4: eag 필수. 미제공 시 DecisionLedgerError.
    """
    for field_name, field_val in [("subject", subject), ("rationale", rationale)]:
        if not field_val or not str(field_val).strip():
            raise DecisionLedgerError(f"required field missing: '{field_name}'")
    if dc.requires_eag:
        if not eag or not str(eag).strip():
            raise DecisionLedgerError(
                f"EAG ID is required for {dc.value} decisions. "
                "DC-3 (Critical) and DC-4 (Constitutional) require an EAG ID."
            )


def record_decision(
    dc: "DecisionClass",
    subject: str,
    rationale: str,
    eag: Optional[str] = None,
    actor: str = "unknown",
) -> dict:
    """
    Decision을 decision_ledger.jsonl에 append 기록합니다.

    Args:
        dc:        DecisionClass enum
        subject:   결정 주제
        rationale: 결정 근거
        eag:       EAG ID (DC-3/DC-4 필수, DC-1/DC-2 선택)
        actor:     결정 주체

    Returns:
        기록된 entry dict

    Raises:
        DecisionLedgerError: 필수 필드 누락 / DC-3·DC-4 EAG 미제공
    """
    validate_decision_input(dc, subject, rationale, eag)
    entry = {
        "schema":      "decision_ledger_v1",
        "version":     VERSION,
        "dc":          dc.value,
        "subject":     subject.strip(),
        "rationale":   rationale.strip(),
        "eag":         eag.strip() if eag else None,
        "declared_at": datetime.now(timezone.utc).isoformat(),
        "actor":       actor.strip(),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _load_all_entries() -> list:
    """decision_ledger.jsonl 전체 로드."""
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


def get_decisions_by_class(dc: "DecisionClass") -> list:
    """DC 분류별 결정 목록 반환."""
    dc_value = dc.value
    return [e for e in _load_all_entries() if e.get("dc") == dc_value]


def get_recent_decisions(n: int = 10) -> list:
    """\ucd5c신순 n건 반환 (jsonl 말미 = 최신)."""
    all_entries = _load_all_entries()
    return list(reversed(all_entries[-n:])) if all_entries else []


def get_decision_summary() -> dict:
    """Decision Ledger 요약 정보 반환."""
    all_entries = _load_all_entries()
    class_counts: dict = {}
    for e in all_entries:
        dc = e.get("dc", "UNKNOWN")
        class_counts[dc] = class_counts.get(dc, 0) + 1
    return {
        "schema":       "decision_ledger_summary_v1",
        "version":      VERSION,
        "eag":          EAG_ID,
        "total_count":  len(all_entries),
        "class_counts": class_counts,
        "recent_5":     list(reversed(all_entries[-5:])) if all_entries else [],
        "log_path":     str(LOG_PATH),
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(get_decision_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

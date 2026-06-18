"""
briefing_gate.py  v1.0
AIBA Governance 3-6: Briefing Quality Gate
EAG: EAG-S264-GOV-3-6-001

caddy의 ask_domi / ask_jeni 호출 전
[CONTEXT][HISTORY][GOAL][CONSTRAINT][REQUEST] 5항목 존재 여부를 검증한다.

정책:
  기본 = BLOCK  (5항목 미충족 시 호출 차단, REPORT_AND_WAIT)
  예외 = WARN   (단순 질의·관측 요청 — call_type='query' 지정 시)
  예외 세분화 기준은 3-7 구현 단계에서 정의한다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


REQUIRED_SECTIONS = [
    "[CONTEXT]",
    "[HISTORY]",
    "[GOAL]",
    "[CONSTRAINT]",
    "[REQUEST]",
]


@dataclass
class BriefingCheckResult:
    passed: bool
    policy: Literal["BLOCK", "WARN", "PASS"]
    missing_sections: list[str] = field(default_factory=list)
    message: str = ""


def validate_briefing_structure(
    prompt: str,
    call_type: Literal["design", "query"] = "design",
) -> BriefingCheckResult:
    """
    prompt 문자열에서 5개 섹션 헤더 존재 여부를 검사한다.

    call_type:
        'design' (기본) — 5항목 미충족 시 BLOCK
        'query'          — 5항목 미충족 시 WARN (단순 질의·관측 요청)

    Returns:
        BriefingCheckResult
            passed           : 모든 섹션 존재 시 True
            policy           : PASS | WARN | BLOCK
            missing_sections : 누락 섹션 목록
            message          : 사람이 읽을 수 있는 설명
    """
    missing = [
        section
        for section in REQUIRED_SECTIONS
        if section not in prompt
    ]

    if not missing:
        return BriefingCheckResult(
            passed=True,
            policy="PASS",
            missing_sections=[],
            message="Briefing structure OK — all 5 sections present.",
        )

    if call_type == "query":
        return BriefingCheckResult(
            passed=False,
            policy="WARN",
            missing_sections=missing,
            message=(
                f"[BRIEFING_GATE WARN] Missing sections: {missing}. "
                "call_type='query' — proceeding with warning."
            ),
        )

    # call_type == 'design'  →  BLOCK
    return BriefingCheckResult(
        passed=False,
        policy="BLOCK",
        missing_sections=missing,
        message=(
            f"[BRIEFING_GATE BLOCK] Missing sections: {missing}. "
            "Briefing quality gate failed. REPORT_AND_WAIT — "
            "complete all 5 sections before calling ask_domi/ask_jeni."
        ),
    )

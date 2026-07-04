#!/usr/bin/env python3
"""
clinical_framework.py v1.0.0
AIBA Clinical Framework
EAG: EAG-S326-CLINICAL-001

핵심 명제 (S258 비오님 확정):
  AIBA는 경험을 구조적 좌표로 변환하여 유전한다.

레이어 설계:
  area_15 Failure Memory  : 실패 이벤트 (RC 분류, component 중심)
  Clinical Framework (본) : 경험 좌표 (7축 분류, 학습/원인 중심)
  저장 경로 완전 분리:
    area_15 -> tools/governance/failure_memory.jsonl
    본 모듈 -> runtime/governance/clinical_experience.jsonl
"""
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S326-CLINICAL-001"

ROOT     = Path("/opt/arss/engine/arss-protocol")
LOG_PATH = ROOT / "runtime/governance/clinical_experience.jsonl"


class ClinicalAxis(Enum):
    """AIBA 7축 루프 (S258 + Manifesto v0.2 확정)"""
    MEMORY        = "MEMORY"         # 경험/코드/상태 저장
    REASONING     = "REASONING"      # 의사결정, 감별진단
    COMMUNICATION = "COMMUNICATION"  # 에이전트 간 브리핑/전달
    GOVERNANCE    = "GOVERNANCE"     # 규칙 시행, EAG 검증
    EXECUTION     = "EXECUTION"      # 코드/명령 실행
    EVOLUTION     = "EVOLUTION"      # 자기개선, DEP 보완
    SCREENING     = "SCREENING"      # 무증상 이상 탐지


class ReversibilityGrade(Enum):
    """가역성 축 3등급 (S258 가역성 2차원 격자)"""
    FULLY_REVERSIBLE     = "FULLY_REVERSIBLE"      # 완전 복원 가능
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"  # 부분 복원/보상 가능
    IRREVERSIBLE         = "IRREVERSIBLE"           # 복원 불가


class ImpactScope(Enum):
    """영향범위 축 3등급 (S258 가역성 2차원 격자)"""
    LOCAL      = "LOCAL"       # 단일 컴포넌트에만 영향
    SYSTEM     = "SYSTEM"      # 복수 컴포넌트/런타임에 영향
    GOVERNANCE = "GOVERNANCE"  # SSOT/헌법/동결 파일에 영향


class ClinicalFrameworkError(ValueError):
    """Clinical Framework 유효성 검증 실패 시 발생."""
    pass


@dataclass
class ExperienceCoordinate:
    """
    경험 좌표 — S258 확정 6필드.
    실패/성공 모두 기록 대상 (비오님: 성공 경험도 구조적 좌표로 유전).
    """
    axis: ClinicalAxis    # 7축 중 어느 축에서 경험이 발생했는가
    session: str          # 세션 ID (예: S326)
    symptom: str          # 관측된 증상 또는 상황
    root_cause: str       # 감별 진단된 근본 원인
    resolution: str       # 적용된 해결/처방
    learning: str         # 다음 세대에 전달할 학습 내용

    def validate(self) -> None:
        """필수 필드 비어있지 않은지 검증."""
        for field in ("session", "symptom", "root_cause", "resolution", "learning"):
            val = getattr(self, field)
            if not val or not str(val).strip():
                raise ClinicalFrameworkError(
                    "required field missing: '{}'".format(field)
                )
        if not isinstance(self.axis, ClinicalAxis):
            raise ClinicalFrameworkError(
                "axis must be ClinicalAxis enum, got: {}".format(type(self.axis))
            )


class ReversibilityMatrix:
    """
    3x3 가역성 격자 — S258 확정.
    (ReversibilityGrade x ImpactScope) -> 승인 요건 문자열.
    """

    _MATRIX = {
        (ReversibilityGrade.FULLY_REVERSIBLE,     ImpactScope.LOCAL):       "자율 실행 (EAG 불필요)",
        (ReversibilityGrade.FULLY_REVERSIBLE,     ImpactScope.SYSTEM):      "사후 보고 (EAG 불필요)",
        (ReversibilityGrade.FULLY_REVERSIBLE,     ImpactScope.GOVERNANCE):  "CASE-BY-CASE: 사전 EAG 권고",
        (ReversibilityGrade.PARTIALLY_REVERSIBLE, ImpactScope.LOCAL):       "사전 EAG 권고",
        (ReversibilityGrade.PARTIALLY_REVERSIBLE, ImpactScope.SYSTEM):      "사전 EAG 필수",
        (ReversibilityGrade.PARTIALLY_REVERSIBLE, ImpactScope.GOVERNANCE):  "사전 EAG 필수 + 3 agent 합의",
        (ReversibilityGrade.IRREVERSIBLE,         ImpactScope.LOCAL):       "사전 EAG 필수",
        (ReversibilityGrade.IRREVERSIBLE,         ImpactScope.SYSTEM):      "사전 EAG 필수 + 3 agent 합의",
        (ReversibilityGrade.IRREVERSIBLE,         ImpactScope.GOVERNANCE):  "EAG VETO: Sovereign 전결. 시스템 Freeze 전환 가능",
    }

    @classmethod
    def classify(cls, reversibility: ReversibilityGrade, scope: ImpactScope) -> str:
        """가역성 등급과 영향범위를 입력받아 승인 요건 문자열 반환."""
        if not isinstance(reversibility, ReversibilityGrade):
            raise ClinicalFrameworkError(
                "reversibility must be ReversibilityGrade enum"
            )
        if not isinstance(scope, ImpactScope):
            raise ClinicalFrameworkError(
                "scope must be ImpactScope enum"
            )
        key = (reversibility, scope)
        return cls._MATRIX.get(key, "UNKNOWN: 수동 검토 필요")

    @classmethod
    def get_full_matrix(cls) -> dict:
        """전체 3x3 격자를 문자열 키 dict로 반환."""
        return {
            "{}.{}".format(k[0].value, k[1].value): v
            for k, v in cls._MATRIX.items()
        }


class DiagnosticAlgorithm:
    """
    4단계 진단 알고리즘 — S258 확정.
    관측 -> 축 식별 -> 감별 진단 -> 정밀 특정.
    모든 메서드 read-only: EAG 없이 자율 실행 가능.
    """

    _AXIS_KEYWORDS = {
        ClinicalAxis.MEMORY:        {"memory", "memor", "forget", "recall", "ssot", "hash", "context"},
        ClinicalAxis.REASONING:     {"reason", "infer", "deduce", "analyz", "diagnos", "judge"},
        ClinicalAxis.COMMUNICATION: {"communicat", "report", "message", "briefing", "relay", "notify"},
        ClinicalAxis.GOVERNANCE:    {"rule", "policy", "protocol", "gate", "eag", "freeze", "constitut"},
        ClinicalAxis.EXECUTION:     {"execut", "deploy", "write", "call", "script", "run", "pytest", "commit"},
        ClinicalAxis.EVOLUTION:     {"learn", "adapt", "improv", "evolv", "dep", "design", "refactor"},
        ClinicalAxis.SCREENING:     {"risk", "threat", "anomaly", "screen", "detect", "monitor", "alert"},
    }

    @classmethod
    def observe(cls, symptom: str) -> dict:
        """
        Step 1 — 증상 관찰.
        원시 증상 문자열을 정규화하여 관측 레코드 생성.
        """
        if not symptom or not str(symptom).strip():
            raise ClinicalFrameworkError("symptom must not be empty")
        return {
            "raw": symptom,
            "normalized": symptom.strip().lower(),
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def identify_axis(cls, observation: dict) -> ClinicalAxis:
        """
        Step 2 — 축 식별.
        관측 레코드의 normalized 텍스트에서 키워드 매칭으로 7축 중 하나 배정.
        매칭 없으면 EXECUTION 기본값 반환.
        """
        if "normalized" not in observation:
            raise ClinicalFrameworkError("observation must have 'normalized' key")
        text = observation["normalized"]
        scores = {axis: 0 for axis in ClinicalAxis}
        for axis, keywords in cls._AXIS_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    scores[axis] += 1
        best = max(scores, key=lambda a: scores[a])
        return best if scores[best] > 0 else ClinicalAxis.EXECUTION

    @classmethod
    def differential_diagnosis(cls, axis: ClinicalAxis, symptom: str) -> list:
        """
        Step 3 — 감별 진단.
        특정 축 내에서 가능한 근본 원인 후보 목록 반환.
        Returns: [{"candidate": str, "confidence": float}, ...]
        """
        _CANDIDATES = {
            ClinicalAxis.MEMORY:        [
                {"candidate": "SSOT stale or context_hash mismatch",    "confidence": 0.8},
                {"candidate": "Session context not loaded correctly",    "confidence": 0.6},
                {"candidate": "File deleted or path changed",           "confidence": 0.5},
            ],
            ClinicalAxis.REASONING:     [
                {"candidate": "Inference without SSOT verification",    "confidence": 0.8},
                {"candidate": "Incomplete differential diagnosis",      "confidence": 0.6},
                {"candidate": "Pattern overfitting from prior sessions","confidence": 0.5},
            ],
            ClinicalAxis.COMMUNICATION: [
                {"candidate": "Briefing missing CONTEXT/GOAL sections", "confidence": 0.7},
                {"candidate": "Agent relay information degradation",    "confidence": 0.7},
                {"candidate": "Notification-style (no confirmation)",   "confidence": 0.5},
            ],
            ClinicalAxis.GOVERNANCE:    [
                {"candidate": "EAG approval bypassed",                  "confidence": 0.9},
                {"candidate": "Freeze file integrity violated",         "confidence": 0.8},
                {"candidate": "Role boundary crossed",                  "confidence": 0.7},
            ],
            ClinicalAxis.EXECUTION:     [
                {"candidate": "Parameter mismatch in exec_scoped",      "confidence": 0.8},
                {"candidate": "Script encoding/escape error",           "confidence": 0.7},
                {"candidate": "Path or filename unverified before use", "confidence": 0.6},
            ],
            ClinicalAxis.EVOLUTION:     [
                {"candidate": "DEP chain skipped or incomplete",        "confidence": 0.8},
                {"candidate": "Reversibility not classified before change","confidence":0.7},
                {"candidate": "Learning not recorded after incident",   "confidence": 0.6},
            ],
            ClinicalAxis.SCREENING:     [
                {"candidate": "Asymptomatic failure not detected early","confidence": 0.8},
                {"candidate": "Monitor/alert not triggered",            "confidence": 0.7},
                {"candidate": "Hash stale without visible symptom",     "confidence": 0.6},
            ],
        }
        return _CANDIDATES.get(axis, [])

    @classmethod
    def pinpoint(
        cls,
        axis: ClinicalAxis,
        candidates: list,
        session: str,
        symptom: str,
        resolution: str = "",
        learning: str = "",
    ) -> ExperienceCoordinate:
        """
        Step 4 — 정밀 특정.
        감별 진단 결과에서 최고 confidence 후보를 root_cause로 선택하여
        ExperienceCoordinate를 생성하여 반환.
        """
        if not candidates:
            root_cause = "undetermined"
        else:
            best = max(candidates, key=lambda c: c.get("confidence", 0))
            root_cause = best.get("candidate", "undetermined")
        return ExperienceCoordinate(
            axis=axis,
            session=str(session).strip(),
            symptom=str(symptom).strip(),
            root_cause=root_cause,
            resolution=str(resolution).strip() or "(not yet resolved)",
            learning=str(learning).strip() or "(pending)",
        )


class AIBAClinicalFramework:
    """
    AIBA Clinical Framework v1.0.0
    경험을 구조적 좌표로 변환하여 유전(傳言)한다.

    S258 확정 핵심 명제:
      AIBA는 사건을 유전하지 않는다.
      AIBA는 경험을 구조적 좌표로 변환하여 유전한다.
    """

    ESCALATION_THRESHOLD = 3  # 동일 axis+symptom 연속 N회 -> escalation

    def __init__(self) -> None:
        self.diagnostician = DiagnosticAlgorithm()
        self.matrix = ReversibilityMatrix()

    # ------------------------------------------------------------------
    # 기록 메서드 (EAG 연동 필요)
    # ------------------------------------------------------------------

    def record_experience(self, coordinate: ExperienceCoordinate) -> dict:
        """
        경험 좌표를 clinical_experience.jsonl에 append-only 기록.
        EAG 연동 필요 (기록은 거버넌스 행위).
        area_15 record_failure()와 동일한 jsonl append 패턴 사용.
        """
        coordinate.validate()
        entry = {
            "schema":      "clinical_experience_v1",
            "version":     VERSION,
            "eag":         EAG_ID,
            "axis":        coordinate.axis.value,
            "session":     coordinate.session,
            "symptom":     coordinate.symptom,
            "root_cause":  coordinate.root_cause,
            "resolution":  coordinate.resolution,
            "learning":    coordinate.learning,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # ------------------------------------------------------------------
    # 읽기 메서드 (자율 실행 가능, EAG 불필요)
    # ------------------------------------------------------------------

    def _load_all_experiences(self) -> list:
        """clinical_experience.jsonl 전체 로드. area_15 _load_all_entries()와 동일 패턴."""
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

    def get_experience_patterns(self, axis: Optional[ClinicalAxis] = None) -> dict:
        """
        경험 패턴 조회.
        axis 지정 시 해당 축만 필터링.
        동일 (axis, symptom) 연속 ESCALATION_THRESHOLD회 감지 시 escalation_required=True.
        """
        all_entries = self._load_all_experiences()
        if axis is not None:
            filtered = [e for e in all_entries if e.get("axis") == axis.value]
        else:
            filtered = list(all_entries)

        escalation_required = False
        if len(filtered) >= self.ESCALATION_THRESHOLD:
            count = 1
            for i in range(1, len(filtered)):
                prev = (filtered[i - 1].get("axis"), filtered[i - 1].get("symptom"))
                curr = (filtered[i].get("axis"),     filtered[i].get("symptom"))
                if prev == curr:
                    count += 1
                    if count >= self.ESCALATION_THRESHOLD:
                        escalation_required = True
                        break
                else:
                    count = 1

        return {
            "axis":                axis.value if axis else "ALL",
            "total":              len(filtered),
            "patterns":           filtered,
            "escalation_required": escalation_required,
            "escalation_threshold": self.ESCALATION_THRESHOLD,
        }

    def get_recent_experiences(self, n: int = 10) -> list:
        """최신순 n건의 경험 좌표 반환."""
        all_entries = self._load_all_experiences()
        return list(reversed(all_entries[-n:])) if all_entries else []

    def get_axis_summary(self) -> dict:
        """축별 경험 좌표 카운트 요약."""
        all_entries = self._load_all_experiences()
        summary: dict = {axis.value: 0 for axis in ClinicalAxis}
        for e in all_entries:
            ax = e.get("axis", "UNKNOWN")
            if ax in summary:
                summary[ax] += 1
            else:
                summary[ax] = summary.get(ax, 0) + 1
        return {
            "schema":      "clinical_axis_summary_v1",
            "version":     VERSION,
            "total":       len(all_entries),
            "axis_counts": summary,
            "log_path":    str(LOG_PATH),
        }


if __name__ == "__main__":
    import sys
    fw = AIBAClinicalFramework()
    print(json.dumps(fw.get_axis_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

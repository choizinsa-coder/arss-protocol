#!/usr/bin/env python3
"""
tool_gate_engine.py v1.0.0 (P1)
AIBA Tool-Friction Pre-Execution Gate — Phase 1 (Path + Regex 정적 검증)
EAG-S365-CARRYOVER-ELIM-P1-IMPL-001

설계: Domi DESIGN (S365, "이월 제거 시스템" 축1) + Caddy IMPLEMENTABLE 보정
      + Jeni TRUST_READY (S365, BLOCKING_ISSUES: NONE).
근거: model_probe.py 템플릿 일반화 (classify() → validate_*()로 사전 실시간 판정).

목적: 도구 호출 직전에 경로·정규식 파라미터의 형식 위반을 걸러 교정 힌트를 반환한다.
      캐디가 DENY를 맞고 매 세션 재학습하는 반복 루프(INC-S364-003 경로/INC-S364-004
      정규식 계열)를 원천 제거한다.

Fail-safe 원칙(model_probe 계승): 기억/추정 의심(측정 안 된 경로)은 DENY가 아닌
      WARN(RC-2)으로 완화한다. 가드가 거짓 확신으로 정상 작업을 막지 않는다.
      형식 위반이 확정적인 경우(미이스케이프 정규식 등)만 DENY.

무결성 선(C2) 비침범: 본 모듈은 순수 판정 함수만 제공한다. 파일 쓰기·상태 변경·
      chain/hash/SSOT·freeze 접근이 전혀 없다(stdlib os.path/re/dataclasses만 사용).
      measured_paths는 오직 record_measurement()로만 갱신되며, 엔진 내부 추론으로는
      절대 갱신되지 않는다(SELF-CRITIQUE (c) 이행 — 가드가 또 다른 기억 재구성 소스가
      되지 않도록).

판정 로직은 단일 함수(validate_path/validate_regex)에 집약 → 단위 테스트 용이(P1-*).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict

# ── 저장소 루트 (경로 절대/상대 등가 판정 기준) ─────────────────────────────
REPO_ROOT = "/opt/arss/engine/arss-protocol"

# ── 판정 상수 (가드 체인 공용 계약) ─────────────────────────────────────────
DECISION_ALLOW = "ALLOW"          # 통과
DECISION_WARN = "RC-2"            # 경고(fail-safe): 실행 허용 + 로그. 기억/추정 의심.
DECISION_DENY = "DENY"            # 형식 위반 확정: 교정 필요. 실행 차단.
DECISION_HARD_STOP = "HARD_STOP"  # 무결성 선(C2) 예약. P1은 발행하지 않음(계약 공유용).

# 실행 차단 대상(집계용). WARN/ALLOW은 미차단.
BLOCKING_DECISIONS = (DECISION_DENY, DECISION_HARD_STOP)

# grep_scoped 등에서 미이스케이프 시 DENY를 유발하는 정규식 메타문자(리터럴 의도 흔함)
_REGEX_LITERAL_HAZARDS = ("(", ")")


@dataclass
class GateResult:
    decision: str      # DECISION_* 중 하나
    validator: str     # 판정 주체 ("path" | "regex")
    reason: str        # 기계 판정 이유
    hint: str          # 교정 힌트 (WARN/DENY 시)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW

    @property
    def blocking(self) -> bool:
        return self.decision in BLOCKING_DECISIONS


def _repo_relative(path: str) -> str:
    """경로를 저장소 기준 상대형으로 정규화한다.
    절대경로(/opt/arss/.../X)와 상대경로(X)를 같은 형태로 환원 → 절대/상대 혼동
    (INC-S364-003 계열)을 등가 판정한다. os.path.normpath로 './' 및 중복 슬래시 제거."""
    p = (path or "").strip()
    if not p:
        return ""
    p = os.path.normpath(p)
    root = os.path.normpath(REPO_ROOT)
    if p == root:
        return "."
    prefix = root + os.sep
    if p.startswith(prefix):
        p = p[len(prefix):]
    # 선행 './' 및 '/' 제거로 순수 상대형 확보
    return p.lstrip("/").lstrip("./") if p not in (".", "") else p


def validate_path(path: str, measured_paths) -> GateResult:
    """경로가 직전 측정(read_file/grep_scoped/list_dir/ls 반환값) 결과에서 유래했는가.
    측정된 경로와 저장소 기준 등가면 ALLOW. 아니면 WARN(기억 재구성 의심) — DENY 아님.

    measured_paths: 측정으로 확보된 경로 집합(문자열 iterable).
    """
    cand = _repo_relative(path)
    if not cand:
        return GateResult(
            DECISION_WARN, "path",
            "Empty or whitespace path.",
            "Provide a concrete path measured from a tool return.")
    measured_rel = {_repo_relative(m) for m in (measured_paths or [])}
    if cand in measured_rel:
        return GateResult(DECISION_ALLOW, "path", "", "")
    return GateResult(
        DECISION_WARN, "path",
        f"Path '{path}' not found among measured results "
        f"(normalized '{cand}'). Possible remembered/reconstructed path.",
        "Re-measure with list_dir/read_file before using this path, "
        "then retry. (Fail-safe: execution not blocked, but verify.)")


def validate_regex(pattern: str) -> GateResult:
    """정규식/검색 패턴에 미이스케이프 리터럴 hazard가 있는가.
    grep_scoped가 DENY하는 미이스케이프 괄호(INC-S364-004 계열)와 혼합 따옴표를 사전 차단.
    확정적 형식 위반이므로 DENY + 교정 힌트."""
    if pattern is None:
        return GateResult(
            DECISION_DENY, "regex", "Pattern is None.",
            "Provide a valid pattern string.")
    hazards = []
    # 이스케이프 인식 스캔: 백슬래시로 이스케이프되지 않은 리터럴 괄호 탐지
    escaped = False
    for ch in pattern:
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in _REGEX_LITERAL_HAZARDS:
            hazards.append(
                f"unescaped '{ch}' — escape as '\\{ch}' for a literal match")
    # 혼합 따옴표 hazard (쉘 이스케이프 문제 유발)
    if "'" in pattern and '"' in pattern:
        hazards.append(
            "mixed single/double quotes may break shell escaping")
    if hazards:
        # 중복 메시지 정리(괄호가 여러 개여도 한 번만 안내)
        uniq = []
        for h in hazards:
            if h not in uniq:
                uniq.append(h)
        return GateResult(
            DECISION_DENY, "regex", "; ".join(uniq),
            "Escape special chars with backslash, or use a fixed-string "
            "search (grep -F) for literals.")
    return GateResult(DECISION_ALLOW, "regex", "", "")


class ToolGateEngine:
    """도구 호출 직전 사전검사 P1. 경로·정규식 정적 검증.

    measured_paths는 오직 record_measurement()로만 갱신된다. 엔진은 스스로 측정하지
    않으며, 유사도/추론 기반 경로 생성도 하지 않는다(SELF-CRITIQUE (c) 구조적 보장).
    """

    def __init__(self):
        self._measured_paths: set = set()

    def record_measurement(self, path: str) -> None:
        """실제 도구 반환값에서 얻은 경로만 등록하는 단일 진입점.
        호출부는 read_file/list_dir/grep_scoped 성공 반환 직후에만 호출해야 한다."""
        rel = _repo_relative(path)
        if rel:
            self._measured_paths.add(rel)

    @property
    def measured_paths(self) -> set:
        return set(self._measured_paths)

    def check_path(self, path: str) -> GateResult:
        return validate_path(path, self._measured_paths)

    def check_regex(self, pattern: str) -> GateResult:
        return validate_regex(pattern)

    @staticmethod
    def violations(results) -> list:
        """실행 차단 대상(DENY/HARD_STOP)만 반환. 오탐 방지 핵심(WARN 미포함)."""
        return [r for r in results if r.decision in BLOCKING_DECISIONS]

    @staticmethod
    def warnings(results) -> list:
        """경고(RC-2)만 반환. 감사 추적/미검증 항목 병기용."""
        return [r for r in results if r.decision == DECISION_WARN]

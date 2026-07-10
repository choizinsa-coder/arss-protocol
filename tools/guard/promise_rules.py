#!/usr/bin/env python3
"""
promise_rules.py — PromiseGate(P3) SSOT 하드카피 + drift 검출 헬퍼
이월제거시스템 축2. 순수 데이터/추출 로직만(부작용 없음, stdlib only).

설계: Domi DESIGN (S367) + Caddy IMPLEMENTABLE 정합.
전문(prevention_rule 등) 전사 대신 rule_id + severity만 하드카피하고,
원본 텍스트는 실행 시 SSOT 파일에서 추출하여 해시로 drift를 검출한다
(장문 전사 손상 계열 INC-S359 회피). id 존재 검증 + 콘텐츠 해시 대조 2중.
"""
from __future__ import annotations

import hashlib
import json
import os

from tools.guard.tool_gate_engine import (
    REPO_ROOT,
    DECISION_DENY,
    DECISION_WARN,
)

# ── SSOT 파일 상대경로 ──
SSOT_RULES_RELPATH = "context/governance/rules.json"
SSOT_LESSONS_RELPATH = "context/lessons/lessons.json"

# ── CLASS_A: rules.json preflight_check_protocol.checks (PC-1~6) ──
# severity: HARD_GATE → DENY 가능, WARNING → WARN
CLASS_A = [
    {"rule_id": "PC-1", "severity": DECISION_DENY},
    {"rule_id": "PC-2", "severity": DECISION_WARN},
    {"rule_id": "PC-3", "severity": DECISION_WARN},
    {"rule_id": "PC-4", "severity": DECISION_DENY},
    {"rule_id": "PC-5", "severity": DECISION_WARN},
    {"rule_id": "PC-6", "severity": DECISION_WARN},
]

# ── CLASS_B: rules.json simple_change_rule (SC/CC/OB/FC) — WARN 전용 ──
CLASS_B = [
    {"rule_id": rid, "severity": DECISION_WARN}
    for rid in (
        "SC-1", "SC-2", "SC-3", "SC-4", "SC-5",
        "CC-1", "CC-2", "CC-3", "CC-4", "CC-5",
        "OB-1", "OB-2", "OB-3",
        "FC-1", "FC-2", "FC-3",
    )
]

# ── CLASS_C: lessons.json 명령형 조건문 prevention_rule (WARN 전용, DENY 불가)
# 문자열 id 사용(배열 인덱스 금지 — 재정렬 취약). LESSON-014는 body 부재로 제외.
CLASS_C = [
    {"rule_id": rid, "severity": DECISION_WARN}
    for rid in (
        "LESSON-001", "LESSON-002", "LESSON-003", "LESSON-005", "LESSON-006",
        "LESSON-011", "LESSON-012", "LESSON-013", "LESSON-015", "LESSON-016",
        "LESSON-017", "LESSON-018", "LESSON-019", "LESSON-020", "LESSON-021",
        "LESSON-022", "LESSON-023",
    )
]

# 배포 시 실제 SSOT 파일 기준으로 재계산·주입(로컴 픽스처 기준 초기값).
# drift 가드 테스트가 실행 시 SSOT에서 재계산한 값과 대조한다.
EXPECTED_SSOT_HASH = "034aa81a82409f0ccbad696b98ca684add6d3275609c57c84ecc5b8006e61abb"


# ── SSOT 추출 ──

def _load_json(root: str, relpath: str) -> dict:
    with open(os.path.join(root, relpath), encoding="utf-8") as f:
        return json.load(f)


def extract_class_a_items(root: str = REPO_ROOT) -> dict:
    """{PC-id: canonical_text} — preflight_check_protocol.checks에서 실추출."""
    data = _load_json(root, SSOT_RULES_RELPATH)
    checks = data["body"]["preflight_check_protocol"]["checks"]
    out = {}
    for c in checks:
        cid = c.get("id")
        if cid:
            out[cid] = json.dumps(
                {
                    "id": cid,
                    "severity": c.get("severity", ""),
                    "requirement": c.get("requirement", ""),
                    "violation": c.get("violation", ""),
                    "action": c.get("action", ""),
                },
                ensure_ascii=False, sort_keys=True,
            )
    return out


def extract_class_b_items(root: str = REPO_ROOT) -> dict:
    """{SC/CC/OB/FC-id: 원문} — simple_change_rule 배열에서 순서 기반 id 부여."""
    data = _load_json(root, SSOT_RULES_RELPATH)
    scr = data["body"]["simple_change_rule"]
    out = {}
    for key, prefix in (
        ("simple_change_criteria", "SC"),
        ("complex_change_criteria", "CC"),
        ("caddy_obligations", "OB"),
        ("fail_closed", "FC"),
    ):
        for i, text in enumerate(scr.get(key, []), 1):
            out[f"{prefix}-{i}"] = text
    return out


def extract_class_c_items(root: str = REPO_ROOT) -> dict:
    """{LESSON-id: prevention_rule} — lessons.json body에서 id로 실추출."""
    data = _load_json(root, SSOT_LESSONS_RELPATH)
    by_id = {}
    for item in data.get("body", []):
        lid = item.get("id")
        if lid:
            by_id[lid] = item
    out = {}
    for entry in CLASS_C:
        lid = entry["rule_id"]
        item = by_id.get(lid)
        if item is not None:
            out[lid] = item.get("prevention_rule", "")
    return out


# ── drift 검출 ──

def missing_ids(root: str = REPO_ROOT) -> list:
    """하드카피 rule_id 중 SSOT 실추출에서 누락된 id 목록(존재 검증, 블로킹)."""
    a = extract_class_a_items(root)
    b = extract_class_b_items(root)
    c = extract_class_c_items(root)
    missing = []
    for entry in CLASS_A:
        if entry["rule_id"] not in a:
            missing.append(entry["rule_id"])
    for entry in CLASS_B:
        if entry["rule_id"] not in b:
            missing.append(entry["rule_id"])
    for entry in CLASS_C:
        if entry["rule_id"] not in c:
            missing.append(entry["rule_id"])
    return missing


def compute_ssot_hash(root: str = REPO_ROOT) -> str:
    """하드카피 대상 rule_id들의 SSOT 실텍스트를 정규 직렬화 후 sha256.
    콘텐츠 drift(값 변경)를 검출한다. id 순서 고정으로 결정적."""
    a = extract_class_a_items(root)
    b = extract_class_b_items(root)
    c = extract_class_c_items(root)
    parts = []
    for entry in CLASS_A:
        parts.append("A|" + entry["rule_id"] + "|" + a.get(entry["rule_id"], "\x00MISSING"))
    for entry in CLASS_B:
        parts.append("B|" + entry["rule_id"] + "|" + b.get(entry["rule_id"], "\x00MISSING"))
    for entry in CLASS_C:
        parts.append("C|" + entry["rule_id"] + "|" + c.get(entry["rule_id"], "\x00MISSING"))
    canonical = "\n".join(parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def all_rules() -> list:
    """CLASS_A + CLASS_B + CLASS_C 통합(각 {rule_id, severity, cls})."""
    out = []
    for entry in CLASS_A:
        out.append({"rule_id": entry["rule_id"], "severity": entry["severity"], "cls": "A"})
    for entry in CLASS_B:
        out.append({"rule_id": entry["rule_id"], "severity": entry["severity"], "cls": "B"})
    for entry in CLASS_C:
        out.append({"rule_id": entry["rule_id"], "severity": entry["severity"], "cls": "C"})
    return out

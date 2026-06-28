"""
EAG-S290-ANALYZER-PHASE15-001
Phase 1.5 단위 테스트 — 도미 조건 5 (최소 2개 자동화 테스트)

Test 1: RC-2 2건, root_cause 서로 다름 → category_recurrence 감지
Test 2: RC-2 1건 → category_recurrence 미감지
"""
import json
import os
import sys
import tempfile
import pytest

# 경로 설정
sys.path.insert(0, "/opt/arss/engine/arss-protocol/tools/analysis")
from incident_analyzer import IncidentAnalyzer


def _make_jsonl(records):
    """임시 JSONL 파일 생성 후 경로 반환."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for r in records:
        tmp.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.close()
    return tmp.name


# ── Test 1: RC-2 2건 / root_cause 문자열이 다름 → Category Recurrence 감지 ────
def test_category_recurrence_detected():
    """
    도미 조건 5 / Test 1
    RC-2 category에 root_cause가 서로 다른 2건이 있을 때,
    기존 Phase 1(root_cause 완전일치)은 재발을 못 잡지만
    Phase 1.5(category 단위)는 RECURRING으로 감지해야 한다.
    """
    records = [
        {
            "timestamp": "2026-06-01T00:00:00Z",
            "session": "S286",
            "error_id": "INC-S286-001",
            "category": "RC-2",
            "description": "PowerShell 따옴표 충돌",
            "root_cause": "기존 제약 B-4 미참조",
            "beo_burden": "yes",
            "resolution": "파일 배포 방식으로 전환",
        },
        {
            "timestamp": "2026-06-02T00:00:00Z",
            "session": "S289",
            "error_id": "INC-S289-001",
            "category": "RC-2",
            "description": "python 인터프리터 미실측",
            "root_cause": "VPS 환경 실측 미수행",  # 다른 root_cause
            "beo_burden": "yes",
            "resolution": "python3 명시",
        },
    ]
    path = _make_jsonl(records)
    try:
        analyzer = IncidentAnalyzer(path)
        analyzer.run()

        # Phase 1 (root_cause 완전일치): 재발 미탐지 확인
        recurring_rc = analyzer.recurring["recurring_root_causes"]
        assert len(recurring_rc) == 0, (
            "Phase 1 root_cause 완전일치는 서로 다른 root_cause를 재발로 탐지하면 안 됨"
        )

        # Phase 1.5 (category 단위): RECURRING 탐지 확인
        recurring_cats = analyzer.recurring["recurring_categories"]
        assert "RC-2" in recurring_cats, "RC-2 category 재발이 recurring_categories에 있어야 함"
        rc2_info = recurring_cats["RC-2"]
        assert rc2_info["count"] == 2
        assert rc2_info["severity"] in ("RECURRING", "SYSTEMIC")
        assert set(rc2_info["sessions"]) == {"S286", "S289"}
        assert rc2_info["distinct_root_causes"] == 2  # 원시 데이터 (도미 조건 2)

        # 스키마 통일 확인 (도미 조건 3): RC-2도 evidence_missing_count 키 존재
        cat_details = analyzer.recurring["category_details"]
        assert "evidence_missing_count" in cat_details["RC-2"]
        assert "unverified_count" in cat_details["RC-2"]

        # CAT-GRD ID 체계 확인 (도미 조건 4)
        cat_grds = [p for p in analyzer.guard_proposals if p.get("type") == "CATEGORY_RECURRENCE"]
        assert len(cat_grds) >= 1
        assert all(p["id"].startswith("CAT-GRD-") for p in cat_grds)

        print("[PASS] test_category_recurrence_detected")
    finally:
        os.unlink(path)


# ── Test 2: RC-2 1건 → Category Recurrence 미감지 ─────────────────────────────
def test_category_recurrence_not_detected():
    """
    도미 조건 5 / Test 2
    RC-2 category가 1건뿐이면 recurring_categories에 포함되지 않아야 한다.
    """
    records = [
        {
            "timestamp": "2026-06-01T00:00:00Z",
            "session": "S286",
            "error_id": "INC-S286-001",
            "category": "RC-2",
            "description": "PowerShell 따옴표 충돌",
            "root_cause": "기존 제약 B-4 미참조",
            "beo_burden": "yes",
            "resolution": "파일 배포 방식으로 전환",
        },
    ]
    path = _make_jsonl(records)
    try:
        analyzer = IncidentAnalyzer(path)
        analyzer.run()

        recurring_cats = analyzer.recurring["recurring_categories"]
        assert "RC-2" not in recurring_cats, (
            "RC-2 1건만 있으면 recurring_categories에 포함되지 않아야 함"
        )

        # category_details에는 존재해야 함 (전체 통계 대상)
        cat_details = analyzer.recurring["category_details"]
        assert "RC-2" in cat_details
        assert cat_details["RC-2"]["count"] == 1

        print("[PASS] test_category_recurrence_not_detected")
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_category_recurrence_detected()
    test_category_recurrence_not_detected()
    print("\n[ALL PASS] Phase 1.5 단위 테스트 2개 통과")

import pytest
import json
import os
from pathlib import Path
from tools.governance.clinical_framework import (
    AIBAClinicalFramework,
    ClinicalAxis,
    ClinicalFrameworkError,
    DiagnosticAlgorithm,
    ExperienceCoordinate,
    ImpactScope,
    ReversibilityGrade,
    ReversibilityMatrix,
)


# TC-01: ClinicalAxis Enum 7축 정합성
def test_clinical_axis_seven_values():
    values = {a.value for a in ClinicalAxis}
    expected = {"MEMORY", "REASONING", "COMMUNICATION", "GOVERNANCE", "EXECUTION", "EVOLUTION", "SCREENING"}
    assert values == expected


# TC-02: ReversibilityGrade Enum 3등급 정합성
def test_reversibility_grade_three_values():
    values = {r.value for r in ReversibilityGrade}
    assert values == {"FULLY_REVERSIBLE", "PARTIALLY_REVERSIBLE", "IRREVERSIBLE"}


# TC-03: ImpactScope Enum 3등급 정합성
def test_impact_scope_three_values():
    values = {s.value for s in ImpactScope}
    assert values == {"LOCAL", "SYSTEM", "GOVERNANCE"}


# TC-04: ExperienceCoordinate 6필드 생성 및 타입
def test_experience_coordinate_creation():
    coord = ExperienceCoordinate(
        axis=ClinicalAxis.EXECUTION,
        session="S326",
        symptom="write_script failed repeatedly",
        root_cause="SA audit limit exceeded",
        resolution="Deferred to next session",
        learning="Minimize write_script calls per session",
    )
    assert coord.axis == ClinicalAxis.EXECUTION
    assert coord.session == "S326"
    assert isinstance(coord.symptom, str)
    assert isinstance(coord.root_cause, str)
    assert isinstance(coord.resolution, str)
    assert isinstance(coord.learning, str)


# TC-05: ExperienceCoordinate validate() - 빈 필드 거부
def test_experience_coordinate_validate_empty_field():
    coord = ExperienceCoordinate(
        axis=ClinicalAxis.GOVERNANCE,
        session="S326",
        symptom="",
        root_cause="EAG bypassed",
        resolution="Rollback",
        learning="Always require EAG",
    )
    with pytest.raises(ClinicalFrameworkError, match="symptom"):
        coord.validate()


# TC-06: ReversibilityMatrix 9개 셀 완전성
def test_reversibility_matrix_all_nine_cells():
    matrix = ReversibilityMatrix.get_full_matrix()
    assert len(matrix) == 9
    for key, val in matrix.items():
        assert isinstance(key, str)
        assert isinstance(val, str)
        assert len(val) > 0


# TC-07: ReversibilityMatrix classify - 자율실행 케이스
def test_reversibility_matrix_auto_execute():
    result = ReversibilityMatrix.classify(
        ReversibilityGrade.FULLY_REVERSIBLE, ImpactScope.LOCAL
    )
    assert "EAG" in result or "자율" in result


# TC-08: ReversibilityMatrix classify - VETO 케이스
def test_reversibility_matrix_veto_case():
    result = ReversibilityMatrix.classify(
        ReversibilityGrade.IRREVERSIBLE, ImpactScope.GOVERNANCE
    )
    assert "VETO" in result or "Sovereign" in result


# TC-09: DiagnosticAlgorithm observe() - 정상
def test_diagnostic_observe_normal():
    obs = DiagnosticAlgorithm.observe("write_script exec_scoped failure")
    assert "raw" in obs
    assert "normalized" in obs
    assert "observed_at" in obs
    assert obs["normalized"] == obs["raw"].strip().lower()


# TC-10: DiagnosticAlgorithm identify_axis() - EXECUTION 키워드 매칭
def test_diagnostic_identify_axis_execution():
    obs = DiagnosticAlgorithm.observe("run_script pytest commit failed")
    axis = DiagnosticAlgorithm.identify_axis(obs)
    assert axis == ClinicalAxis.EXECUTION


# TC-11: DiagnosticAlgorithm identify_axis() - GOVERNANCE 키워드 매칭
def test_diagnostic_identify_axis_governance():
    obs = DiagnosticAlgorithm.observe("EAG approval gate freeze violation")
    axis = DiagnosticAlgorithm.identify_axis(obs)
    assert axis == ClinicalAxis.GOVERNANCE


# TC-12: DiagnosticAlgorithm differential_diagnosis() - 후보 반환
def test_diagnostic_differential_diagnosis_returns_candidates():
    candidates = DiagnosticAlgorithm.differential_diagnosis(
        ClinicalAxis.EXECUTION, "parameter error"
    )
    assert isinstance(candidates, list)
    assert len(candidates) > 0
    for c in candidates:
        assert "candidate" in c
        assert "confidence" in c
        assert 0.0 <= c["confidence"] <= 1.0


# TC-13: DiagnosticAlgorithm pinpoint() - ExperienceCoordinate 반환
def test_diagnostic_pinpoint_returns_coordinate():
    candidates = [{"candidate": "SA audit limit", "confidence": 0.9}]
    coord = DiagnosticAlgorithm.pinpoint(
        axis=ClinicalAxis.EXECUTION,
        candidates=candidates,
        session="S326",
        symptom="write_script failed",
        resolution="Deferred",
        learning="Minimize calls",
    )
    assert isinstance(coord, ExperienceCoordinate)
    assert coord.axis == ClinicalAxis.EXECUTION
    assert coord.root_cause == "SA audit limit"


# TC-14: AIBAClinicalFramework record_experience + get_recent_experiences (tmp log)
def test_framework_record_and_retrieve(tmp_path, monkeypatch):
    import tools.governance.clinical_framework as cf_mod
    tmp_log = tmp_path / "clinical_experience.jsonl"
    monkeypatch.setattr(cf_mod, "LOG_PATH", tmp_log)
    fw = AIBAClinicalFramework()
    coord = ExperienceCoordinate(
        axis=ClinicalAxis.MEMORY,
        session="S326",
        symptom="context_hash mismatch",
        root_cause="SSOT stale",
        resolution="Reload SSOT",
        learning="Always verify hash before proceeding",
    )
    entry = fw.record_experience(coord)
    assert entry["schema"] == "clinical_experience_v1"
    assert entry["axis"] == "MEMORY"
    recent = fw.get_recent_experiences(1)
    assert len(recent) == 1
    assert recent[0]["axis"] == "MEMORY"


# TC-15: get_experience_patterns escalation_required 감지
def test_framework_escalation_detection(tmp_path, monkeypatch):
    import tools.governance.clinical_framework as cf_mod
    tmp_log = tmp_path / "clinical_experience.jsonl"
    monkeypatch.setattr(cf_mod, "LOG_PATH", tmp_log)
    fw = AIBAClinicalFramework()
    for _ in range(3):
        coord = ExperienceCoordinate(
            axis=ClinicalAxis.EXECUTION,
            session="S326",
            symptom="write_script repeated failure",
            root_cause="SA limit",
            resolution="Deferred",
            learning="Minimize calls",
        )
        fw.record_experience(coord)
    result = fw.get_experience_patterns(axis=ClinicalAxis.EXECUTION)
    assert result["escalation_required"] is True
    assert result["total"] == 3


# TC-16: get_axis_summary 7축 모두 포함
def test_framework_axis_summary_keys(tmp_path, monkeypatch):
    import tools.governance.clinical_framework as cf_mod
    tmp_log = tmp_path / "clinical_experience.jsonl"
    monkeypatch.setattr(cf_mod, "LOG_PATH", tmp_log)
    fw = AIBAClinicalFramework()
    summary = fw.get_axis_summary()
    assert summary["total"] == 0
    for axis in ClinicalAxis:
        assert axis.value in summary["axis_counts"]

import pytest
from tools.eps_v1_4.classifier import classify_statement


# ── 기존 테스트 ────────────────────────────────────────────────
def test_assertion_plain():
    assert classify_statement("완료되었습니다").label == "A"


def test_exploration_with_possibility():
    assert classify_statement("완료되었을 가능성이 있습니다").label == "E"


def test_proposed_with_next_action():
    r = classify_statement("다음 단계로 수정 제안합니다\nNext Action: 패키지 작성")
    assert r.label == "P"


def test_proposed_without_next_action():
    # classify는 P, enforce에서 차단
    r = classify_statement("다음 단계로 수정 제안합니다")
    assert r.label == "P"


def test_auto_assertion_sasil():
    assert classify_statement("사실상 완료 상태입니다").label == "A"


def test_exploration_geoui():
    assert classify_statement("거의 그런 것 같습니다").label == "E"


def test_assertion_iimi_pass():
    # "이미 검증 PASS입니다" — assertion pattern "검증 PASS" 매칭 → A
    assert classify_statement("이미 검증 PASS입니다").label == "A"


def test_exploration_iimi_ganeungseong():
    assert classify_statement("이미 가능성이 보입니다").label == "E"


# ── failure path ───────────────────────────────────────────────
def test_empty_string_fallback_to_exploration():
    """빈 문자열 — 어떤 패턴도 미매칭 → E 폴백"""
    r = classify_statement("")
    assert r.label == "E"
    assert r.reason == "default exploration fallback"


def test_whitespace_only_fallback_to_exploration():
    """공백만 있는 입력 — strip 후 빈 문자열 → E 폴백"""
    r = classify_statement("   ")
    assert r.label == "E"


def test_matched_pattern_set_on_explicit_assertion():
    """명시적 assertion — matched_pattern 값 존재 확인"""
    r = classify_statement("완료되었습니다")
    assert r.matched_pattern is not None


def test_matched_pattern_none_on_fallback():
    """폴백 분기 — matched_pattern은 None"""
    r = classify_statement("")
    assert r.matched_pattern is None

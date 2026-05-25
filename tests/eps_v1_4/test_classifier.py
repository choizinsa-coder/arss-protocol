import pytest
from tools.eps_v1_4.classifier import classify_statement

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

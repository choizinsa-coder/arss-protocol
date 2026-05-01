import pytest
from tools.eps_v1_4.patterns import has_next_action

def test_valid_next_action():
    assert has_next_action("수정하겠습니다.\nNext Action: 패키지 작성") is True

def test_no_colon_accepted():
    assert has_next_action("수정하겠습니다.\nNext Action 패키지 작성") is True

def test_case_insensitive():
    assert has_next_action("수정하겠습니다.\nnext action: 패키지 작성") is True

def test_empty_body_rejected():
    assert has_next_action("수정하겠습니다.\nNext Action: ") is False

def test_placeholder_rejected():
    assert has_next_action("수정하겠습니다.\nNext Action: TBD") is False

def test_punctuation_only_rejected():
    assert has_next_action("수정하겠습니다.\nNext Action: ...") is False

import pytest
from unittest.mock import patch
from tools.eps_v1_4.wrapper import wrapper_execute

def test_segmenter_exception_blocked():
    with patch("tools.eps_v1_4.wrapper.bind_proposed_blocks", side_effect=Exception("segmenter error")):
        r = wrapper_execute({"raw_output": "테스트", "context": {}})
    assert r["status"] == "BLOCKED"
    assert r["formatted_output"] is None

def test_classifier_exception_blocked():
    with patch("tools.eps_v1_4.wrapper.enforce_statement", side_effect=Exception("classifier error")):
        r = wrapper_execute({"raw_output": "테스트", "context": {}})
    assert r["status"] == "BLOCKED"
    assert r["formatted_output"] is None

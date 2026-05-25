import pytest
from tools.eps_v1_4.wrapper import safe_emit_wrapper_result

def test_pass_emits_string():
    r = {"status": "PASS", "formatted_output": "[E] 결과입니다."}
    assert safe_emit_wrapper_result(r) == "[E] 결과입니다."

def test_blocked_emits_none():
    r = {"status": "BLOCKED", "formatted_output": None}
    assert safe_emit_wrapper_result(r) is None

def test_invalid_status_emits_none():
    r = {"status": "INVALID", "formatted_output": "something"}
    assert safe_emit_wrapper_result(r) is None

def test_pass_null_output_emits_none():
    r = {"status": "PASS", "formatted_output": None}
    assert safe_emit_wrapper_result(r) is None

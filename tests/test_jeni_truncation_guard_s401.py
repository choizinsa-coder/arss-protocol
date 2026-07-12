"""EAG-S401-JENI-TRUNCATION-GUARD-IMPL-001

PINS the defect that nearly produced a FALSE measurement.

RAW (S401, live): candidate GLM-5.2 spent its ENTIRE output budget (8192 tokens,
exactly AIBA_LLM_MAX_TOKENS) on reasoning and returned finish_reason="length"
with EMPTY content. The S399 adapter never read finish_reason, so it returned
ok=True / text="". The verification loop accepted "" as the FINAL VERDICT and
the regression scorer recorded FAIL.

A model that was CUT OFF must never be scored as a model that MISSED a defect.
Same class as RC-E (EAG-S378, domi runtime) - the hole simply also existed here.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JENI_PATH = os.path.join(ROOT, "tools/jeni_runtime/aiba_jeni_runtime.py")


def _load():
    spec = importlib.util.spec_from_file_location("_s401_trunc", JENI_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules.pop("_s401_trunc", None)
    return mod


def _resp(content=None, finish_reason="stop", tool_calls=None):
    msg = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}}


def test_length_truncation_is_not_a_verdict():
    """THE bug: finish_reason=length + empty content was ok=True/text=""."""
    m = _load()
    out = m._parse_openai_response(_resp(content="", finish_reason="length"))
    assert out["ok"] is False
    assert "MAX_TOKENS_TRUNCATED" in out["error"]


def test_length_truncation_flagged_even_with_partial_text():
    """A verdict cut off mid-sentence is still not a verdict."""
    m = _load()
    out = m._parse_openai_response(
        _resp(content="TRUST_READY = TRU", finish_reason="length"))
    assert out["ok"] is False
    assert "MAX_TOKENS_TRUNCATED" in out["error"]


def test_empty_response_with_no_tool_calls_fails():
    m = _load()
    out = m._parse_openai_response(_resp(content=None, finish_reason="stop"))
    assert out["ok"] is False
    assert "EMPTY_RESPONSE" in out["error"]


def test_normal_response_still_succeeds_and_keeps_the_contract():
    """The S399 return contract must survive: parts + usage must still be there,
    or _run_verification_loop raises KeyError on call_result["parts"]."""
    m = _load()
    out = m._parse_openai_response(_resp(content="[JENI VERIFICATION] ok",
                                         finish_reason="stop"))
    assert out["ok"] is True
    assert out["error"] is None
    assert out["text"] == "[JENI VERIFICATION] ok"
    for key in ("text", "function_calls", "parts", "usage", "error"):
        assert key in out
    assert out["parts"] == [{"text": "[JENI VERIFICATION] ok"}]
    assert out["usage"]["promptTokenCount"] == 10


def test_tool_call_response_still_succeeds_in_gemini_shape():
    """tool_calls must still be converted to {id,name,args}; the loop reads
    fc["name"] / fc["args"] and would break on the raw OpenAI shape."""
    m = _load()
    out = m._parse_openai_response(_resp(
        content=None, finish_reason="tool_calls",
        tool_calls=[{"id": "call_1", "type": "function",
                     "function": {"name": "read_file",
                                  "arguments": '{"path": "/x"}'}}]))
    assert out["ok"] is True
    assert len(out["function_calls"]) == 1
    fc = out["function_calls"][0]
    assert fc["name"] == "read_file"
    assert fc["args"] == {"path": "/x"}
    assert fc["id"] == "call_1"


def test_no_choices_still_fails():
    m = _load()
    out = m._parse_openai_response({"choices": []})
    assert out["ok"] is False
    assert out["error"] == "NO_CHOICES"

"""
tests/test_jeni_vendor_abstraction_s399.py
EAG-S399-JENI-VENDOR-ABSTRACTION-001
Vendor abstraction layer coverage. Env unset in CI -> _IS_GEMINI True.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.jeni_runtime.aiba_jeni_runtime as rt  # noqa: E402


def test_env_fallback_defaults_to_gemini():
    assert rt._IS_GEMINI is True
    assert rt.LLM_MODEL == rt.GEMINI_MODEL
    assert rt.LLM_MODEL_ESCALATE == rt.GEMINI_MODEL_ESCALATE
    assert rt.LLM_API_KEY == rt.GEMINI_API_KEY


def test_parse_openai_response_mapping():
    raw = {"choices": [{"message": {"content": "hello", "tool_calls": [
        {"id": "call_1", "type": "function",
         "function": {"name": "read_file",
                      "arguments": json.dumps({"path": "/x"})}}]},
        "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5}}
    r = rt._parse_openai_response(raw)
    assert r["ok"] is True
    assert r["text"] == "hello"
    assert r["function_calls"][0]["id"] == "call_1"
    assert r["function_calls"][0]["name"] == "read_file"
    assert r["function_calls"][0]["args"]["path"] == "/x"
    assert r["usage"]["promptTokenCount"] == 10
    assert r["usage"]["candidatesTokenCount"] == 5


def test_parse_openai_response_no_choices():
    r = rt._parse_openai_response({})
    assert r["ok"] is False
    assert r["error"] == "NO_CHOICES"


def test_parse_openai_response_bad_arguments_json():
    raw = {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "call_2", "type": "function",
         "function": {"name": "list_dir", "arguments": "NOT_JSON"}}]},
        "finish_reason": "tool_calls"}]}
    r = rt._parse_openai_response(raw)
    assert r["ok"] is True
    assert r["function_calls"][0]["args"] == {}


def test_contents_to_messages_tool_call_id_threading():
    contents = [
        {"role": "user", "parts": [{"text": "q"}]},
        {"role": "model", "parts": [{"functionCall": {
            "id": "call_9", "name": "read_file", "args": {"path": "/x"}}}]},
        {"role": "user", "parts": [{"functionResponse": {
            "id": "call_9", "name": "read_file",
            "response": {"result": "data"}}}]},
    ]
    msgs = rt._gemini_contents_to_openai_messages(contents)
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "q"}
    assert msgs[2]["role"] == "assistant"
    assert msgs[2]["tool_calls"][0]["id"] == "call_9"
    assert msgs[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert msgs[3]["role"] == "tool"
    assert msgs[3]["tool_call_id"] == "call_9"
    assert msgs[3]["content"] == "data"


def test_function_response_message_id_optional():
    m = rt._build_function_response_message("read_file", "ok", None)
    assert "id" not in m["parts"][0]["functionResponse"]
    m2 = rt._build_function_response_message("read_file", "ok", None, "call_2")
    assert m2["parts"][0]["functionResponse"]["id"] == "call_2"


def test_openai_tools_wrap():
    tools = rt._build_openai_tools()
    assert all(t["type"] == "function" for t in tools)
    assert {t["function"]["name"] for t in tools} == set(rt.ALLOWED_TOOLS)

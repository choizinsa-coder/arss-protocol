"""
tests/test_jeni_runtime_ivloop.py
PT-S193-JENI-PERSIST-001 (v4.0.0)
EAG-1: 비오(Joshua) S193 승인

v4.0.0 Persistent Autonomous Agent + Function Calling 커버리지.
이전 버전(v2/v3) 테스트는 아키텍처 전면 변경으로 v4 기준 재작성.

Coverage:
  - _build_function_declarations: read 5종 선언
  - _extract_function_calls / _extract_text_from_parts: 응답 파싱
  - _is_path_allowed / _is_sandbox_write_allowed: 경로 검증
  - _execute_function_call: 허용/거부
  - _make_tool_audit_entry / _make_audit_bundle: audit 구조
  - Memory: _build_memory_preamble / _load_recent_findings (pruning)
  - _make_fail_closed_result: FAIL 구조
  - _run_verification_loop: Function Calling 루프 시나리오
"""

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.jeni_runtime.aiba_jeni_runtime as _runtime  # noqa: E402

from tools.jeni_runtime.aiba_jeni_runtime import (  # noqa: E402
    ALLOWED_TOOLS,
    MAX_TOOL_ROUNDS,
    _build_function_declarations,
    _build_function_response_message,
    _build_initial_message,
    _build_memory_preamble,
    _execute_function_call,
    _extract_function_calls,
    _extract_text_from_parts,
    _is_path_allowed,
    _is_sandbox_write_allowed,
    _make_audit_bundle,
    _make_fail_closed_result,
    _make_tool_audit_entry,
    _run_verification_loop,
)

# ── Function Declarations ──────────────────────────────────────────────────────


def test_function_declarations_count():
    decls = _build_function_declarations()
    assert len(decls) == 5


def test_function_declarations_names():
    names = {d["name"] for d in _build_function_declarations()}
    assert names == {"read_file", "list_dir", "grep_scoped", "read_log",
                     "get_runtime_snapshot"}


def test_function_declarations_no_write():
    names = {d["name"] for d in _build_function_declarations()}
    assert "write_file" not in names


def test_function_declarations_have_parameters():
    for d in _build_function_declarations():
        assert "parameters" in d
        assert d["parameters"]["type"] == "object"


# ── 응답 파싱 ─────────────────────────────────────────────────────────────────


def test_extract_function_calls_single():
    parts = [{"functionCall": {"name": "read_file", "args": {"path": "/x"}}}]
    calls = _extract_function_calls(parts)
    assert len(calls) == 1
    assert calls[0]["name"] == "read_file"
    assert calls[0]["args"]["path"] == "/x"


def test_extract_function_calls_none():
    parts = [{"text": "TRUST_READY = PASS"}]
    assert _extract_function_calls(parts) == []


def test_extract_text_from_parts():
    parts = [{"text": "안녕"}, {"text": "하세요"}]
    assert _extract_text_from_parts(parts) == "안녕하세요"


def test_extract_text_ignores_function_call():
    parts = [{"functionCall": {"name": "x", "args": {}}}, {"text": "결과"}]
    assert _extract_text_from_parts(parts) == "결과"


# ── 경로 검증 ─────────────────────────────────────────────────────────────────


def test_is_path_allowed_arss_subpath():
    assert _is_path_allowed("/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json") is True


def test_is_path_allowed_etc_denied():
    assert _is_path_allowed("/etc/passwd") is False


def test_is_path_allowed_empty():
    assert _is_path_allowed("") is True


def test_is_path_allowed_traversal():
    assert _is_path_allowed("/opt/arss/engine/arss-protocol/../../etc/passwd") is False


def test_is_sandbox_write_allowed_jeni():
    assert _is_sandbox_write_allowed(
        "/opt/arss/engine/arss-protocol/tools/sandbox/jeni/active/state/runtime_state.json") is True


def test_is_sandbox_write_denied_operational():
    assert _is_sandbox_write_allowed(
        "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json") is False


def test_is_sandbox_write_denied_other_sandbox():
    assert _is_sandbox_write_allowed(
        "/opt/arss/engine/arss-protocol/tools/sandbox/domi/x.txt") is False


def test_is_sandbox_write_empty_denied():
    assert _is_sandbox_write_allowed("") is False


# ── _execute_function_call ────────────────────────────────────────────────────


def test_execute_function_call_not_allowed():
    result, err = _execute_function_call("write_file", {"path": "/x"})
    assert err is not None
    assert "TOOL_NOT_ALLOWED" in err


def test_execute_function_call_path_denied():
    result, err = _execute_function_call("read_file", {"path": "/etc/passwd"})
    assert err is not None
    assert "PATH_NOT_ALLOWED" in err


# ── Audit ─────────────────────────────────────────────────────────────────────


def test_make_tool_audit_entry_structure():
    e = _make_tool_audit_entry(1, "read_file", "ALLOW", 100, "/opt/arss/x")
    assert e["round"] == 1
    assert e["tool"] == "read_file"
    assert e["status"] == "ALLOW"
    assert e["path"] == "/opt/arss/x"


def test_make_tool_audit_entry_no_path():
    e = _make_tool_audit_entry(1, "get_runtime_snapshot", "ALLOW", 50)
    assert "path" not in e


def test_make_audit_bundle_dedup():
    trail = [
        {"round": 1, "tool": "read_file", "status": "ALLOW", "duration_ms": 1},
        {"round": 2, "tool": "read_file", "status": "ALLOW", "duration_ms": 1},
        {"round": 3, "tool": "grep_scoped", "status": "ALLOW", "duration_ms": 1},
    ]
    b = _make_audit_bundle(3, trail)
    assert b["tool_rounds"] == 3
    assert b["tools_used"] == ["read_file", "grep_scoped"]


# ── Memory ────────────────────────────────────────────────────────────────────


def test_build_memory_preamble_empty():
    assert _build_memory_preamble({"runtime_state": {}, "recent_findings": [],
                                   "recent_audits": [], "recent_conversation": []}) == ""


def test_build_memory_preamble_with_state():
    mem = {"runtime_state": {"last_session": "S192"}, "recent_findings": [],
           "recent_audits": [], "recent_conversation": []}
    pre = _build_memory_preamble(mem)
    assert "S192" in pre
    assert "runtime_state" in pre


def test_build_memory_preamble_conversation():
    mem = {"runtime_state": {}, "recent_findings": [], "recent_audits": [],
           "recent_conversation": [{"role": "jeni", "content": "이전 검증 결과"}]}
    pre = _build_memory_preamble(mem)
    assert "이전 검증 결과" in pre


def test_load_recent_findings_pruning(monkeypatch, tmp_path):
    """제니 제언 1: RESOLVED/CLOSED 제외 검증."""
    findings_dir = tmp_path / "findings"
    findings_dir.mkdir()
    (findings_dir / "F-001.json").write_text(
        json.dumps({"finding_id": "F-001", "status": "OPEN", "summary": "open issue"}))
    (findings_dir / "F-002.json").write_text(
        json.dumps({"finding_id": "F-002", "status": "RESOLVED", "summary": "fixed"}))
    (findings_dir / "F-003.json").write_text(
        json.dumps({"finding_id": "F-003", "status": "CLOSED", "summary": "closed"}))

    monkeypatch.setattr(_runtime, "MEM_FINDINGS_DIR", str(findings_dir))
    findings = _runtime._load_recent_findings()
    ids = {f["finding_id"] for f in findings}
    assert "F-001" in ids
    assert "F-002" not in ids  # RESOLVED 제외
    assert "F-003" not in ids  # CLOSED 제외


# ── Fail-Closed ───────────────────────────────────────────────────────────────


def test_fail_closed_ok_false():
    r = _make_fail_closed_result("R", "d", 0)
    assert r["ok"] is False


def test_fail_closed_no_pass():
    r = _make_fail_closed_result("R", "d", 0)
    assert "TRUST_READY = PASS" not in r["text"]


def test_fail_closed_stop_signal():
    r = _make_fail_closed_result("R", "d", 0)
    assert "STOP_SIGNAL = ON" in r["text"]


# ── Message 조립 ──────────────────────────────────────────────────────────────


def test_build_initial_message_with_memory():
    msg = _build_initial_message("질문", "배경", "메모리내용")
    text = msg["parts"][0]["text"]
    assert "메모리내용" in text
    assert "배경" in text
    assert "질문" in text


def test_build_function_response_message_success():
    msg = _build_function_response_message("read_file", "파일내용", None)
    fr = msg["parts"][0]["functionResponse"]
    assert fr["name"] == "read_file"
    assert fr["response"]["result"] == "파일내용"


def test_build_function_response_message_error():
    msg = _build_function_response_message("read_file", "", "PATH_NOT_ALLOWED")
    fr = msg["parts"][0]["functionResponse"]
    assert fr["response"]["error"] == "PATH_NOT_ALLOWED"


# ── _run_verification_loop (Function Calling) ─────────────────────────────────


def _patch_gemini(monkeypatch, responses):
    call_count = {"n": 0}

    def _mock(contents):
        n = call_count["n"]
        call_count["n"] += 1
        if n < len(responses):
            return responses[n]
        return {"ok": False, "text": "", "function_calls": [], "parts": [],
                "error": "MOCK_EXHAUSTED"}

    monkeypatch.setattr(_runtime, "_call_gemini", _mock)


def _patch_persist_noop(monkeypatch):
    monkeypatch.setattr(_runtime, "_persist_results", lambda *a, **k: None)


def _patch_memory_empty(monkeypatch):
    monkeypatch.setattr(_runtime, "_load_memory_context", lambda: {
        "runtime_state": {}, "recent_findings": [], "recent_audits": [],
        "recent_conversation": []})


# FC-01: 즉시 PASS (function_call 없음)
def test_loop_pass_no_function_call(monkeypatch):
    _patch_memory_empty(monkeypatch)
    _patch_persist_noop(monkeypatch)
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "TRUST_READY = PASS", "function_calls": [],
         "parts": [{"text": "TRUST_READY = PASS"}], "error": None},
    ])
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is True
    assert result["rounds_used"] == 0


# FC-02: function_call → 결과 주입 → PASS
def test_loop_function_call_then_pass(monkeypatch):
    _patch_memory_empty(monkeypatch)
    _patch_persist_noop(monkeypatch)
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "", "function_calls": [{"name": "get_runtime_snapshot",
         "args": {}}], "parts": [{"functionCall": {"name": "get_runtime_snapshot",
         "args": {}}}], "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "function_calls": [],
         "parts": [{"text": "TRUST_READY = PASS"}], "error": None},
    ])
    monkeypatch.setattr(_runtime, "_execute_function_call",
                        lambda n, a: ('{"status":"ALLOW"}', None))
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is True
    assert result["rounds_used"] == 1
    assert "get_runtime_snapshot" in result["audit"]["tools_used"]


# FC-03: Gemini 오류 → FAIL
def test_loop_gemini_error(monkeypatch):
    _patch_memory_empty(monkeypatch)
    _patch_persist_noop(monkeypatch)
    _patch_gemini(monkeypatch, [
        {"ok": False, "text": "", "function_calls": [], "parts": [],
         "error": "HTTP_500"},
    ])
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is False
    assert result["error"] == "VALIDATION_PARSE_FAILURE"


# FC-04: 매 라운드 function_call → MAX_ROUNDS_EXCEEDED
def test_loop_max_rounds(monkeypatch):
    _patch_memory_empty(monkeypatch)
    _patch_persist_noop(monkeypatch)
    fc_resp = {"ok": True, "text": "", "function_calls": [{"name": "read_file",
               "args": {"path": "/opt/arss/engine/arss-protocol/x"}}],
               "parts": [{"functionCall": {"name": "read_file",
               "args": {"path": "/opt/arss/engine/arss-protocol/x"}}}], "error": None}
    _patch_gemini(monkeypatch, [fc_resp] * (MAX_TOOL_ROUNDS + 3))
    monkeypatch.setattr(_runtime, "_execute_function_call", lambda n, a: ("data", None))
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is False
    assert result["error"] == "MAX_ROUNDS_EXCEEDED"


# FC-05: timeout preempt
def test_loop_timeout_preempt(monkeypatch):
    _patch_memory_empty(monkeypatch)
    _patch_persist_noop(monkeypatch)
    original_time = time.time
    call_n = {"n": 0}

    def _fake_time():
        call_n["n"] += 1
        if call_n["n"] <= 1:
            return original_time()
        return original_time() + 115

    monkeypatch.setattr(_runtime.time, "time", _fake_time)
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "TRUST_READY = PASS", "function_calls": [],
         "parts": [{"text": "x"}], "error": None},
    ])
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is False
    assert result["error"] == "TIMEOUT_BUDGET_EXCEEDED"


# FC-06: persist 실패 시 검증 계속 (문제 3)
def test_loop_persist_failure_continues(monkeypatch):
    _patch_memory_empty(monkeypatch)
    monkeypatch.setattr(_runtime, "_persist_results",
                        lambda *a, **k: "PERSISTENCE_FAILED: conversation")
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "TRUST_READY = PASS", "function_calls": [],
         "parts": [{"text": "TRUST_READY = PASS"}], "error": None},
    ])
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is True  # 검증은 PASS 유지
    assert result["persistence"] == "PERSISTENCE_FAILED: conversation"


# FC-07: memory injection 호출 검증
def test_loop_memory_injected(monkeypatch):
    captured = {"preamble_seen": False}

    def _mock_memory():
        return {"runtime_state": {"last_session": "S192"}, "recent_findings": [],
                "recent_audits": [], "recent_conversation": []}

    monkeypatch.setattr(_runtime, "_load_memory_context", _mock_memory)
    _patch_persist_noop(monkeypatch)

    def _mock_gemini(contents):
        first_text = contents[0]["parts"][0]["text"]
        if "S192" in first_text:
            captured["preamble_seen"] = True
        return {"ok": True, "text": "TRUST_READY = PASS", "function_calls": [],
                "parts": [{"text": "TRUST_READY = PASS"}], "error": None}

    monkeypatch.setattr(_runtime, "_call_gemini", _mock_gemini)
    result = _run_verification_loop("질문", "", "S193")
    assert result["ok"] is True
    assert captured["preamble_seen"] is True  # 메모리가 프롬프트에 주입됨


import urllib.error
from unittest.mock import MagicMock

def test_execute_gemini_503_retry_success(monkeypatch):
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(url="", code=503, msg="SU", hdrs={}, fp=None)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        import json as _json
        mock_resp.read.return_value = _json.dumps({"candidates":[{"content":{"parts":[{"text":"PASS"}]},"finishReason":"STOP"}]}).encode()
        return mock_resp
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is True
    assert call_count["n"] == 2

def test_execute_gemini_503_retry_also_fails(monkeypatch):
    def mock_urlopen(req, timeout):
        raise urllib.error.HTTPError(url="", code=503, msg="SU", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "after_503_retry" in result["error"]

def test_execute_gemini_non503_no_retry(monkeypatch):
    """400 등 503/429 외 오류코드는 재시도 없이 즉시 FAIL_CLOSED (v4.2.0 현행화)."""
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        raise urllib.error.HTTPError(url="", code=400, msg="BAD_REQUEST", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "HTTP_400" in result["error"]
    assert call_count["n"] == 1  # 재시도 없음


def test_execute_gemini_429_retry_then_fail(monkeypatch):
    """v4.2.0: 429 발생 시 1회 재시도, 재시도도 429면 FAIL_CLOSED (after_429_retry)."""
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        raise urllib.error.HTTPError(url="", code=429, msg="TMR", hdrs={}, fp=None)
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is False
    assert "HTTP_429" in result["error"]
    assert "after_429_retry" in result["error"]
    assert call_count["n"] == 2  # 최초 1회 + 재시도 1회


def test_execute_gemini_429_retry_success(monkeypatch):
    """v4.2.0: 429 발생 후 재시도 성공 케이스."""
    import json as _json
    call_count = {"n": 0}
    def mock_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(url="", code=429, msg="TMR", hdrs={}, fp=None)
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = _json.dumps({
            "candidates": [{"content": {"parts": [{"text": "PASS"}]}, "finishReason": "STOP"}]
        }).encode()
        return mock_resp
    monkeypatch.setattr(_runtime.urllib.request, "urlopen", mock_urlopen)
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    result = _runtime._execute_gemini_request(MagicMock())
    assert result["ok"] is True
    assert call_count["n"] == 2  # 최초 1회(429) + 재시도 1회(성공)

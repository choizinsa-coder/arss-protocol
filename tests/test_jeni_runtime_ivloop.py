"""
tests/test_jeni_runtime_ivloop.py
PT-S191-JENI-IVLOOP-001 (v2.0.0 기존 28 assertions 유지)
PT-S193-JENI-TOOLLOOP-001 (v3.0.0 신규 assertions)
EAG-1: 비오(Joshua) S191 / S193 승인

Coverage:
  [v2.0.0 유지]
  - _detect_trigger: positive / negative / edge cases
  - _make_fail_closed_result: 구조 / PASS 미생성 보장
  - _build_initial_message: context 유/무
  - _build_observation_message: round 번호 주입
  - _jeni_read_canonical_source: path traversal 차단 / missing field
  - _run_verification_loop: 6개 시나리오 (L-01~L-06)

  [v3.0.0 신규]
  - _parse_tool_request: 정상/비정상/누락 케이스
  - _is_path_allowed: whitelist 허용/거부
  - _make_tool_audit_entry: 구조 검증
  - _make_audit_bundle: tools_used 집계
  - _build_tool_result_message: round/tool/result 주입
  - _build_tool_denied_message: 거부 사유 주입
  - _run_verification_loop v3: tool request 경로
      TL-01 tool request → ALLOW → PASS
      TL-02 tool request → DENY → 계속 진행
      TL-03 tool request → MAX_TOOL_ROUNDS 초과
      TL-04 timeout preempt 차단
      TL-05 audit trail 기록 검증
      TL-06 write_file 요청 거부
      TL-07 whitelist 외 경로 거부
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.jeni_runtime.aiba_jeni_runtime as _runtime  # noqa: E402

from tools.jeni_runtime.aiba_jeni_runtime import (  # noqa: E402
    MAX_TOOL_ROUNDS,
    _build_initial_message,
    _build_observation_message,
    _build_tool_denied_message,
    _build_tool_result_message,
    _detect_trigger,
    _is_path_allowed,
    _jeni_read_canonical_source,
    _make_audit_bundle,
    _make_fail_closed_result,
    _make_tool_audit_entry,
    _parse_tool_request,
    _run_verification_loop,
)

# ═══════════════════════════════════════════════════════════════════════════════
# v2.0.0 기존 assertions (28개 유지)
# ═══════════════════════════════════════════════════════════════════════════════

# ── _detect_trigger ────────────────────────────────────────────────────────────


def test_detect_trigger_trigger_a():
    assert _detect_trigger("판정: TRIGGER-A 모순 발견") is True


def test_detect_trigger_trigger_e():
    assert _detect_trigger("TRIGGER-E 검증 불충분") is True


def test_detect_trigger_stop():
    assert _detect_trigger("[STOP] 독립 검증 필요") is True


def test_detect_trigger_revalidation():
    assert _detect_trigger("REVALIDATION_REQUIRED = YES") is True


def test_detect_trigger_pass_no_trigger():
    assert _detect_trigger("TRUST_READY = PASS") is False


def test_detect_trigger_empty_string():
    assert _detect_trigger("") is False


def test_detect_trigger_case_insensitive():
    assert _detect_trigger("trigger-b detected in design") is True


def test_detect_trigger_jeni_stop_lowercase():
    assert _detect_trigger("제니 [stop] 독립 검증") is True


# ── _make_fail_closed_result ────────────────────────────────────────────────────


def test_fail_closed_ok_is_false():
    r = _make_fail_closed_result("REASON", "detail", 0)
    assert r["ok"] is False


def test_fail_closed_text_contains_trust_ready_fail():
    r = _make_fail_closed_result("R", "d", 1)
    assert "TRUST_READY = FAIL" in r["text"]


def test_fail_closed_text_contains_stop_signal():
    r = _make_fail_closed_result("R", "d", 1)
    assert "STOP_SIGNAL = ON" in r["text"]


def test_fail_closed_no_pass_in_text():
    """우발적 PASS 생성 금지 검증."""
    r = _make_fail_closed_result("R", "d", 0)
    assert "TRUST_READY = PASS" not in r["text"]


def test_fail_closed_rounds_used_propagated():
    r = _make_fail_closed_result("R", "d", 2)
    assert r["rounds_used"] == 2


def test_fail_closed_reason_in_text():
    r = _make_fail_closed_result("MAX_ROUNDS_EXCEEDED", "detail", 2)
    assert "MAX_ROUNDS_EXCEEDED" in r["text"]


# ── _build_initial_message ──────────────────────────────────────────────────────


def test_build_initial_message_with_context():
    msg = _build_initial_message("질문", "배경 정보")
    assert msg["role"] == "user"
    text = msg["parts"][0]["text"]
    assert "배경 정보" in text
    assert "질문" in text


def test_build_initial_message_without_context():
    msg = _build_initial_message("질문만", "")
    assert msg["parts"][0]["text"] == "질문만"


def test_build_initial_message_role_user():
    msg = _build_initial_message("p", "c")
    assert msg["role"] == "user"


# ── _build_observation_message ──────────────────────────────────────────────────


def test_build_observation_message_contains_round_number():
    msg = _build_observation_message(1, "obs_data")
    assert "Round 1" in msg["parts"][0]["text"]


def test_build_observation_message_contains_obs_context():
    msg = _build_observation_message(2, "VPS_DATA_HERE")
    assert "VPS_DATA_HERE" in msg["parts"][0]["text"]


def test_build_observation_message_role_user():
    msg = _build_observation_message(1, "d")
    assert msg["role"] == "user"


# ── _jeni_read_canonical_source ──────────────────────────────────────────────────


def test_canonical_source_missing_field():
    data, err = _jeni_read_canonical_source({})
    assert err == "POINTER_MISSING_CANONICAL_SOURCE"
    assert data == {}


def test_canonical_source_path_traversal_blocked():
    """../../../etc/passwd traversal 시도 시 VPS_BASE 내 파일만 접근."""
    pointer = {"canonical_source": "../../../etc/passwd"}
    data, err = _jeni_read_canonical_source(pointer)
    assert err is not None
    assert data == {}
    assert "/etc/passwd" not in (err or "")


# ── _run_verification_loop v2.0.0 시나리오 ────────────────────────────────────


def _patch_gemini(monkeypatch, responses: list[dict]) -> None:
    """Gemini 호출 순서대로 응답 mock."""
    call_count = {"n": 0}

    def _mock_call(contents):
        n = call_count["n"]
        call_count["n"] += 1
        if n < len(responses):
            return responses[n]
        return {"ok": False, "text": "", "error": "MOCK_EXHAUSTED"}

    monkeypatch.setattr(_runtime, "_call_gemini_multi", _mock_call)


def _patch_observation(monkeypatch, result: tuple) -> None:
    """_build_observation_context 결과 고정."""
    monkeypatch.setattr(_runtime, "_build_observation_context", lambda: result)


# L-01: PASS (TRIGGER 없음, Round 0)
def test_loop_pass_no_trigger(monkeypatch):
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    result = _run_verification_loop("질문", "")
    assert result["ok"] is True
    assert result["rounds_used"] == 0


# L-02: FAIL — Gemini 오류 (VALIDATION_PARSE_FAILURE)
def test_loop_fail_gemini_error(monkeypatch):
    _patch_gemini(monkeypatch, [
        {"ok": False, "text": "", "error": "HTTP_500"},
    ])
    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "VALIDATION_PARSE_FAILURE"


# L-03: TRIGGER at Round 0 → 관측 성공 → PASS at Round 1
def test_loop_trigger_then_pass(monkeypatch):
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "[STOP] 독립 검증 필요", "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    _patch_observation(monkeypatch, ("관측 데이터", None))
    result = _run_verification_loop("질문", "")
    assert result["ok"] is True
    assert result["rounds_used"] == 1


# L-04: TRIGGER at every round → MAX_ROUNDS_EXCEEDED
def test_loop_trigger_max_rounds_exceeded(monkeypatch):
    trigger_resp = {"ok": True, "text": "TRIGGER-E 검증 불충분", "error": None}
    _patch_gemini(monkeypatch, [trigger_resp] * (MAX_TOOL_ROUNDS + 3))
    _patch_observation(monkeypatch, ("obs", None))
    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "MAX_ROUNDS_EXCEEDED"


# L-05: TRIGGER at Round 0 → 관측 실패 → INDEPENDENT_OBSERVATION_UNAVAILABLE
def test_loop_observation_unavailable(monkeypatch):
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "[STOP]", "error": None},
    ])
    _patch_observation(monkeypatch, ("", "FILE_NOT_FOUND: /opt/arss/..."))
    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "INDEPENDENT_OBSERVATION_UNAVAILABLE"


# L-06: Accumulative Injection — V-3 Trust Chain 연속성 검증
def test_loop_accumulative_injection(monkeypatch):
    """
    Round 1 Gemini 호출 시 contents에:
      [user(초기)] + [model(Round 0 응답)] + [user(관측 데이터)]
    가 포함되어야 함.
    """
    captured: list[list[dict]] = []
    call_n = {"n": 0}

    def _mock_call(contents):
        captured.append([dict(m) for m in contents])
        call_n["n"] += 1
        if call_n["n"] == 1:
            return {"ok": True, "text": "TRIGGER-A 모순 발견 [STOP]", "error": None}
        return {"ok": True, "text": "TRUST_READY = PASS", "error": None}

    monkeypatch.setattr(_runtime, "_call_gemini_multi", _mock_call)
    _patch_observation(monkeypatch, ("obs_data_injected", None))

    result = _run_verification_loop("질문", "")
    assert result["ok"] is True

    assert len(captured) == 2
    round_1_contents = captured[1]
    assert len(round_1_contents) >= 3

    model_msgs = [m for m in round_1_contents if m["role"] == "model"]
    assert len(model_msgs) >= 1
    assert any("TRIGGER-A" in m["parts"][0]["text"] for m in model_msgs)

    user_msgs = [m for m in round_1_contents if m["role"] == "user"]
    assert any("obs_data_injected" in m["parts"][0]["text"] for m in user_msgs)


# ═══════════════════════════════════════════════════════════════════════════════
# v3.0.0 신규 assertions
# ═══════════════════════════════════════════════════════════════════════════════

# ── _parse_tool_request ────────────────────────────────────────────────────────


def test_parse_tool_request_read_file():
    text = (
        "검증이 필요합니다.\n"
        "[JENI_TOOL_REQUEST]\n"
        "tool=read_file\n"
        "path=/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json\n"
        "[/JENI_TOOL_REQUEST]\n"
        "위 파일을 확인해야 합니다."
    )
    result = _parse_tool_request(text)
    assert result is not None
    assert result["tool"] == "read_file"
    assert result["path"] == "/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"


def test_parse_tool_request_grep_scoped():
    text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=grep_scoped\n"
        "path=/opt/arss/engine/arss-protocol/tests\n"
        "pattern=CONTAINMENT\n"
        "[/JENI_TOOL_REQUEST]"
    )
    result = _parse_tool_request(text)
    assert result is not None
    assert result["tool"] == "grep_scoped"
    assert result["pattern"] == "CONTAINMENT"


def test_parse_tool_request_no_block_returns_none():
    result = _parse_tool_request("TRUST_READY = PASS")
    assert result is None


def test_parse_tool_request_missing_end_tag_returns_none():
    text = "[JENI_TOOL_REQUEST]\ntool=read_file\npath=/opt/arss/x\n"
    result = _parse_tool_request(text)
    assert result is None


def test_parse_tool_request_no_tool_field_returns_none():
    text = "[JENI_TOOL_REQUEST]\npath=/opt/arss/x\n[/JENI_TOOL_REQUEST]"
    result = _parse_tool_request(text)
    assert result is None


def test_parse_tool_request_get_runtime_snapshot():
    text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=get_runtime_snapshot\n"
        "[/JENI_TOOL_REQUEST]"
    )
    result = _parse_tool_request(text)
    assert result is not None
    assert result["tool"] == "get_runtime_snapshot"


# ── _is_path_allowed ──────────────────────────────────────────────────────────


def test_is_path_allowed_arss_root_subpath():
    assert _is_path_allowed("/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json") is True


def test_is_path_allowed_arss_root_itself():
    assert _is_path_allowed("/opt/arss/engine/arss-protocol") is True


def test_is_path_allowed_etc_denied():
    assert _is_path_allowed("/etc/passwd") is False


def test_is_path_allowed_root_denied():
    assert _is_path_allowed("/root/.ssh/id_rsa") is False


def test_is_path_allowed_empty_path_allowed():
    """get_runtime_snapshot 등 path 없는 도구 — 빈 문자열 허용."""
    assert _is_path_allowed("") is True


def test_is_path_allowed_traversal_denied():
    assert _is_path_allowed("/opt/arss/engine/arss-protocol/../../etc/passwd") is False


# ── _make_tool_audit_entry ────────────────────────────────────────────────────


def test_make_tool_audit_entry_structure():
    entry = _make_tool_audit_entry(1, "read_file", "ALLOW", 183, "/opt/arss/x")
    assert entry["round"] == 1
    assert entry["tool"] == "read_file"
    assert entry["status"] == "ALLOW"
    assert entry["duration_ms"] == 183
    assert entry["path"] == "/opt/arss/x"


def test_make_tool_audit_entry_no_path():
    entry = _make_tool_audit_entry(2, "get_runtime_snapshot", "ALLOW", 50)
    assert "path" not in entry


def test_make_tool_audit_entry_deny():
    entry = _make_tool_audit_entry(1, "write_file", "DENY", 5)
    assert entry["status"] == "DENY"


# ── _make_audit_bundle ────────────────────────────────────────────────────────


def test_make_audit_bundle_tools_used_dedup():
    trail = [
        {"round": 1, "tool": "read_file", "status": "ALLOW", "duration_ms": 100},
        {"round": 2, "tool": "read_file", "status": "ALLOW", "duration_ms": 90},
        {"round": 3, "tool": "grep_scoped", "status": "ALLOW", "duration_ms": 80},
    ]
    bundle = _make_audit_bundle(3, trail)
    assert bundle["tool_rounds"] == 3
    assert bundle["tools_used"] == ["read_file", "grep_scoped"]
    assert len(bundle["trail"]) == 3


def test_make_audit_bundle_empty_trail():
    bundle = _make_audit_bundle(0, [])
    assert bundle["tool_rounds"] == 0
    assert bundle["tools_used"] == []


# ── _build_tool_result_message ────────────────────────────────────────────────


def test_build_tool_result_message_structure():
    msg = _build_tool_result_message(1, "read_file", "FILE_CONTENT_HERE")
    assert msg["role"] == "user"
    text = msg["parts"][0]["text"]
    assert "Round 1" in text
    assert "read_file" in text
    assert "FILE_CONTENT_HERE" in text


# ── _build_tool_denied_message ────────────────────────────────────────────────


def test_build_tool_denied_message_structure():
    msg = _build_tool_denied_message(2, "write_file", "TOOL_NOT_ALLOWED")
    assert msg["role"] == "user"
    text = msg["parts"][0]["text"]
    assert "write_file" in text
    assert "TOOL_NOT_ALLOWED" in text


# ── _run_verification_loop v3.0.0 시나리오 ────────────────────────────────────


def _patch_execute_tool(monkeypatch, result: tuple) -> None:
    """_execute_tool_request 결과 고정."""
    monkeypatch.setattr(_runtime, "_execute_tool_request", lambda params: result)


# TL-01: tool request → ALLOW → PASS
def test_toolloop_tool_request_allow_then_pass(monkeypatch):
    """
    Round 0: [JENI_TOOL_REQUEST] read_file 포함
    Round 1: TRUST_READY = PASS
    """
    tool_request_text = (
        "독립 검증이 필요합니다.\n"
        "[JENI_TOOL_REQUEST]\n"
        "tool=read_file\n"
        "path=/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": tool_request_text, "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    _patch_execute_tool(monkeypatch, ("FILE_CONTENT", None))

    result = _run_verification_loop("질문", "")
    assert result["ok"] is True
    assert result["rounds_used"] == 1


# TL-02: tool request → DENY → 계속 진행 후 PASS
def test_toolloop_tool_request_deny_continues(monkeypatch):
    """
    tool call 거부 시 denied message 주입 후 Gemini 재호출 → PASS 가능.
    """
    tool_request_text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=read_file\n"
        "path=/opt/arss/engine/arss-protocol/x\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": tool_request_text, "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    _patch_execute_tool(monkeypatch, ("", "PATH_NOT_ALLOWED: denied"))

    result = _run_verification_loop("질문", "")
    assert result["ok"] is True


# TL-03: tool request → MAX_TOOL_ROUNDS 초과
def test_toolloop_max_rounds_exceeded(monkeypatch):
    """매 라운드 tool request → MAX_TOOL_ROUNDS 초과 → FAIL_CLOSED."""
    tool_request_text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=read_file\n"
        "path=/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": tool_request_text, "error": None},
    ] * (MAX_TOOL_ROUNDS + 3))
    _patch_execute_tool(monkeypatch, ("data", None))

    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "MAX_ROUNDS_EXCEEDED"


# TL-04: timeout preempt 차단
def test_toolloop_timeout_preempt(monkeypatch):
    """loop_start를 과거로 조작하여 TIMEOUT_BUDGET_EXCEEDED 발동."""
    import tools.jeni_runtime.aiba_jeni_runtime as rt

    original_time = time.time
    call_n = {"n": 0}

    def _fake_time():
        call_n["n"] += 1
        # 첫 호출(loop_start 기록)은 0, 이후는 115초 경과로 처리
        if call_n["n"] <= 1:
            return original_time()
        return original_time() + 115  # TIMEOUT_PREEMPT_SECONDS(110) 초과

    monkeypatch.setattr(rt.time, "time", _fake_time)
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])

    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "TIMEOUT_BUDGET_EXCEEDED"


# TL-05: audit trail 기록 검증
def test_toolloop_audit_trail_recorded(monkeypatch):
    """tool 호출 성공 시 audit trail에 기록되는지 검증."""
    tool_request_text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=get_runtime_snapshot\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": tool_request_text, "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    _patch_execute_tool(monkeypatch, ('{"status": "ALLOW"}', None))

    result = _run_verification_loop("질문", "")
    assert result["ok"] is True
    audit = result.get("audit", {})
    assert audit.get("tool_rounds") == 1
    assert "get_runtime_snapshot" in audit.get("tools_used", [])
    trail = audit.get("trail", [])
    assert len(trail) == 1
    assert trail[0]["status"] == "ALLOW"


# TL-06: write_file 요청 거부
def test_toolloop_write_file_denied(monkeypatch):
    """
    Gemini가 write_file 요청 시 TOOL_NOT_ALLOWED로 거부되어야 함.
    거부 후 Gemini 재호출 → PASS 가능.
    """
    write_request_text = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=write_file\n"
        "path=/opt/arss/engine/arss-protocol/tools/sandbox/jeni/test.txt\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": write_request_text, "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])
    # _execute_tool_request를 실제 실행 (write_file → TOOL_NOT_ALLOWED 반환)
    # monkeypatch 없이 실제 함수 사용

    result = _run_verification_loop("질문", "")
    # write_file 거부 후 denied message 주입 → PASS
    assert result["ok"] is True
    audit = result.get("audit", {})
    trail = audit.get("trail", [])
    assert len(trail) == 1
    assert trail[0]["status"] == "DENY"


# TL-07: whitelist 외 경로 거부
def test_toolloop_path_outside_whitelist_denied(monkeypatch):
    """
    /etc/passwd 경로 요청 시 PATH_NOT_ALLOWED로 거부.
    거부 후 Gemini 재호출 → PASS 가능.
    """
    bad_path_request = (
        "[JENI_TOOL_REQUEST]\n"
        "tool=read_file\n"
        "path=/etc/passwd\n"
        "[/JENI_TOOL_REQUEST]"
    )
    _patch_gemini(monkeypatch, [
        {"ok": True, "text": bad_path_request, "error": None},
        {"ok": True, "text": "TRUST_READY = PASS", "error": None},
    ])

    result = _run_verification_loop("질문", "")
    assert result["ok"] is True
    audit = result.get("audit", {})
    trail = audit.get("trail", [])
    assert len(trail) == 1
    assert trail[0]["status"] == "DENY"

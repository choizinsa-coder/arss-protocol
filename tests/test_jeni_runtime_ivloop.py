"""
tests/test_jeni_runtime_ivloop.py
PT-S191-JENI-IVLOOP-001 — Independent Verification Loop 단위 테스트
EAG-1: 비오(Joshua) S191 승인

Coverage:
  - _detect_trigger: positive / negative / edge cases
  - _make_fail_closed_result: 구조 / PASS 미생성 보장
  - _build_initial_message: context 유/무
  - _build_observation_message: round 번호 주입
  - _jeni_read_canonical_source: path traversal 차단 / missing field
  - _run_verification_loop: 6개 시나리오
      L-01 PASS (TRIGGER 없음)
      L-02 FAIL (Gemini 오류)
      L-03 TRIGGER → 관측 성공 → PASS (Round 1)
      L-04 TRIGGER → max_rounds 초과 → FAIL
      L-05 TRIGGER → 관측 실패 → FAIL
      L-06 Accumulative Injection 검증 (V-3)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tools.jeni_runtime.aiba_jeni_runtime as _runtime  # noqa: E402

from tools.jeni_runtime.aiba_jeni_runtime import (  # noqa: E402
    MAX_REVIEW_ROUNDS,
    _build_initial_message,
    _build_observation_message,
    _detect_trigger,
    _jeni_read_canonical_source,
    _make_fail_closed_result,
    _run_verification_loop,
)

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
    """../../../etc/passwd 등 traversal 시도 시 VPS_BASE 내 파일만 접근."""
    pointer = {"canonical_source": "../../../etc/passwd"}
    data, err = _jeni_read_canonical_source(pointer)
    # basename 추출 후 VPS_BASE/passwd 경로 → 해당 파일 없으므로 FILE_NOT_FOUND
    assert err is not None
    assert data == {}
    # 실제 /etc/passwd 경로로 접근하지 않았음을 확인 (error msg에 etc 없음)
    assert "/etc/passwd" not in (err or "")


# ── _run_verification_loop (mock) ─────────────────────────────────────────────────


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
    _patch_gemini(monkeypatch, [trigger_resp] * (MAX_REVIEW_ROUNDS + 3))
    _patch_observation(monkeypatch, ("obs", None))
    result = _run_verification_loop("질문", "")
    assert result["ok"] is False
    assert result["error"] == "MAX_ROUNDS_EXCEEDED"
    assert result["rounds_used"] == MAX_REVIEW_ROUNDS


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

    # 2회 호출되었는지 확인
    assert len(captured) == 2

    round_1_contents = captured[1]
    # Round 1 입력: user(초기) + model(Round 0 응답) + user(관측 데이터) = 3개
    assert len(round_1_contents) >= 3

    # model 역할 메시지에 Round 0 TRIGGER 응답이 포함되어야 함 (누적 주입)
    model_msgs = [m for m in round_1_contents if m["role"] == "model"]
    assert len(model_msgs) >= 1
    assert any("TRIGGER-A" in m["parts"][0]["text"] for m in model_msgs)

    # 관측 데이터가 마지막 user 메시지에 포함되어야 함
    user_msgs = [m for m in round_1_contents if m["role"] == "user"]
    assert any("obs_data_injected" in m["parts"][0]["text"] for m in user_msgs)

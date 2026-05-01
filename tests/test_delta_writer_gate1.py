"""
tests/test_delta_writer_gate1.py
================================
PT-S69-001 — delta_writer.py _gate_1_mutation_gate 수정 검증
도미 설계 TC-1 ~ TC-8
EAG-1/2 승인: 비오(Joshua) S69
"""

import pytest
from unittest.mock import patch
from tools.auto_loader.mutation_gate import MutationRequest, MutationResult
from tools.delta_context import delta_writer


# TC-1: evaluate import 기준 정상 로딩
def test_tc1_evaluate_import():
    import tools.delta_context.delta_writer as dw
    assert hasattr(dw, "_mg_evaluate"), "evaluate import 누락"
    assert hasattr(dw, "MutationRequest"), "MutationRequest import 누락"


# TC-2: check import 잔존 시 FAIL
def test_tc2_check_not_imported():
    import tools.delta_context.delta_writer as dw
    assert not hasattr(dw, "mutation_gate_check"), "check import 잔존 — 제거 필요"


# TC-3: allowed == true → gate PASS
def test_tc3_gate_pass():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    mock_result = MutationResult(allowed=True, reason="allowed", latency_ms=0)
    with patch("tools.delta_context.delta_writer._mg_evaluate", return_value=mock_result):
        result = _gate_1_mutation_gate({"target_key": "agent_focus"})
    assert result["pass"] is True


# TC-4: allowed == false → gate FAIL
def test_tc4_gate_fail():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    mock_result = MutationResult(allowed=False, reason="mutation forbidden", latency_ms=0)
    with patch("tools.delta_context.delta_writer._mg_evaluate", return_value=mock_result):
        result = _gate_1_mutation_gate({"target_key": "agent_focus"})
    assert result["pass"] is False
    assert result["gate"] == "G1"
    assert "mutation forbidden" in result["reason"]


# TC-5: MutationRequest 필수 필드 누락 → FAIL
def test_tc5_missing_required_fields():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    with patch("tools.delta_context.delta_writer._mg_evaluate", side_effect=TypeError("missing field")):
        result = _gate_1_mutation_gate({})
    assert result["pass"] is False
    assert result["gate"] == "G1"


# TC-6: evaluate 예외 발생 → FAIL
def test_tc6_evaluate_exception():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    with patch("tools.delta_context.delta_writer._mg_evaluate", side_effect=Exception("unexpected")):
        result = _gate_1_mutation_gate({"target_key": "agent_focus"})
    assert result["pass"] is False
    assert result["gate"] == "G1"


# TC-7: SESSION_CONTEXT mutation target → FAIL
def test_tc7_session_context_mutation_target():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    mock_result = MutationResult(allowed=False, reason="SESSION_CONTEXT mutation forbidden", latency_ms=0)
    with patch("tools.delta_context.delta_writer._mg_evaluate", return_value=mock_result):
        result = _gate_1_mutation_gate({"target_key": "session_context"})
    assert result["pass"] is False
    assert "forbidden" in result["reason"]


# TC-8: chain mutation signal → FAIL
def test_tc8_chain_mutation_signal():
    from tools.delta_context.delta_writer import _gate_1_mutation_gate
    mock_result = MutationResult(allowed=False, reason="chain mutation signal detected", latency_ms=0)
    with patch("tools.delta_context.delta_writer._mg_evaluate", return_value=mock_result):
        result = _gate_1_mutation_gate({"target_key": "chain_tip"})
    assert result["pass"] is False
    assert "chain" in result["reason"]

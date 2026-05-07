"""
tests/test_shadow_pipeline_p2_integrity.py
==========================================
PT-S72-001 — run_shadow_pipeline generated_at 주입 E2E 계약 테스트
TC-1~TC-9
EAG-1 APPROVED by 비오(Joshua) — S72
"""
import pytest
from unittest.mock import patch, MagicMock
from tools.delta_context.shadow_pipeline import run_shadow_pipeline, _runtime_observed_at

VALID_GENERATED_AT = "2026-05-02T10:00:00.000+09:00"

VALID_DELTA_REQUEST = {
    "domain": "test_domain",
    "sequence_number": 1,
    "event_type": "test_event",
    "target_key": "test_key",
    "new_value": "test_value",
    "cross_ref": "",
    "prev_delta_id": "",
    "prev_content_hash": "",
}


# TC-1: generated_at 미전달(빈 문자열) → PRECONDITION_GATE fail-closed
def _make_open_mock():
    import json as _json
    from unittest.mock import mock_open as _mock_open
    _tx_json = _json.dumps({"id": "TX-S72", "session": 72, "status": "PENDING"})
    _index_json = _json.dumps({"transactions": []})
    _original_open = open
    def _patched_open(file, mode="r", *args, **kwargs):
        if "TX-S72" in str(file):
            if "r" in mode:
                return _mock_open(read_data=_tx_json)()
            else:
                return _mock_open()()
        if "INDEX.json" in str(file):
            if "r" in mode:
                return _mock_open(read_data=_index_json)()
            else:
                return _mock_open()()
        return _original_open(file, mode, *args, **kwargs)
    return _patched_open


def _make_open_mock():
    import json as _json
    from unittest.mock import mock_open as _mock_open
    _tx_json = _json.dumps({"id": "TX-S72", "session": 72, "status": "PENDING"})
    _index_json = _json.dumps({"transactions": []})
    _original_open = open
    def _patched_open(file, mode="r", *args, **kwargs):
        if "TX-S72" in str(file):
            if "r" in mode:
                return _mock_open(read_data=_tx_json)()
            else:
                return _mock_open()()
        if "INDEX.json" in str(file):
            if "r" in mode:
                return _mock_open(read_data=_index_json)()
            else:
                return _mock_open()()
        return _original_open(file, mode, *args, **kwargs)
    return _patched_open


def test_tc1_generated_at_empty_fail_closed():
    result = run_shadow_pipeline(
        session_number=72,
        delta_requests=[VALID_DELTA_REQUEST],
        generated_at="",
    )
    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["stage"] == "PRECONDITION_GATE"


# TC-2: generated_at None 전달 → PRECONDITION_GATE fail-closed
def test_tc2_generated_at_none_fail_closed():
    result = run_shadow_pipeline(
        session_number=72,
        delta_requests=[VALID_DELTA_REQUEST],
        generated_at=None,
    )
    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["stage"] == "PRECONDITION_GATE"


# TC-3: generated_at malformed → PRECONDITION_GATE fail-closed
def test_tc3_generated_at_malformed_fail_closed():
    result = run_shadow_pipeline(
        session_number=72,
        delta_requests=[VALID_DELTA_REQUEST],
        generated_at="not-a-timestamp",
    )
    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["stage"] == "PRECONDITION_GATE"


# TC-4: valid generated_at 주입 시 PRECONDITION_GATE 통과 — Stage 0 진입 확인
def test_tc4_valid_generated_at_passes_precondition():
    with patch("tools.delta_context.shadow_pipeline.write_delta") as mock_wd:
        mock_wd.return_value = {"success": False, "reason": "test_stop"}
        result = run_shadow_pipeline(
            session_number=72,
            delta_requests=[VALID_DELTA_REQUEST],
            generated_at=VALID_GENERATED_AT,
        )
    # PRECONDITION_GATE를 통과하여 DELTA_WRITE 단계에서 실패해야 함
    assert result["stage"] != "PRECONDITION_GATE"


# TC-5: candidate_payload에 generated_at 존재 확인
def test_tc5_candidate_payload_has_generated_at():
    captured = {}


    def mock_ssot_payload_provider(**kwargs):
        return {
            "session_number": kwargs.get("session_number"),
            "written_deltas": kwargs.get("written_deltas"),
            "generated_at": kwargs.get("generated_at"),
            "source": "mock_ssot_payload_provider",
        }
    def mock_validate(ctx):
        captured["ctx"] = ctx
        return {
            "phase2_valid": True,
            "preconditions": {"passed": True, "failed_conditions": []},
            "contract": {"contract": "PASS"},
        }

    with patch("tools.delta_context.shadow_pipeline.write_delta") as mock_wd, \
         patch("tools.delta_context.shadow_pipeline.update_index") as mock_ui, \
         patch("tools.delta_context.shadow_pipeline.mutate_create_transaction") as mock_tx, \
         patch("tools.delta_context.shadow_pipeline.create_commit") as mock_cc, \
         patch("tools.delta_context.shadow_pipeline.verify_commit_exists") as mock_vc, \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("tools.delta_context.shadow_pipeline.classify_stage0", return_value={
             "state": "NOT_STARTED",
             "gate": "ALLOW_NEW_EXECUTION",
             "reason": "TEST_STAGE0_BYPASS",
             "metadata": {"test_only": True}
         }), \
         patch("tools.delta_context.shadow_pipeline.run_with_collapse_gate", side_effect=mock_validate), \
         patch("tools.delta_context.shadow_pipeline.record_divergence"), \
         patch("tools.delta_context.shadow_pipeline.get_divergence_summary", return_value={}), \
         patch("tools.delta_context.shadow_pipeline.record_session"), \
         patch("os.path.isdir", return_value=False):

        mock_wd.return_value = {
            "success": True,
            "delta": {"target_key": "test_key", "new_value": "test_value"},
            "path": "/fake/path",
        }
        mock_ui.return_value = {"success": True}
        mock_tx.return_value = {"success": True, "tx_id": "TX-S72", "transaction_hash": "hash"}
        mock_cc.return_value = {"success": True, "commit_id": "COMMIT-S72"}
        mock_vc.return_value = {"exists": True, "hard_stop": False}

        run_shadow_pipeline(
            session_number=72,
            delta_requests=[VALID_DELTA_REQUEST],
            generated_at=VALID_GENERATED_AT,
            ssot_payload_provider=mock_ssot_payload_provider,
        )

    assert "candidate_payload" in captured["ctx"]
    assert captured["ctx"]["candidate_payload"].get("generated_at") == VALID_GENERATED_AT


# TC-6: ssot_payload에 generated_at 존재 확인
def test_tc6_ssot_payload_has_generated_at():
    captured = {}


    def mock_ssot_payload_provider(**kwargs):
        return {
            "session_number": kwargs.get("session_number"),
            "written_deltas": kwargs.get("written_deltas"),
            "generated_at": kwargs.get("generated_at"),
            "source": "mock_ssot_payload_provider",
        }
    def mock_validate(ctx):
        captured["ctx"] = ctx
        return {
            "phase2_valid": True,
            "preconditions": {"passed": True, "failed_conditions": []},
            "contract": {"contract": "PASS"},
        }

    with patch("tools.delta_context.shadow_pipeline.write_delta") as mock_wd, \
         patch("tools.delta_context.shadow_pipeline.update_index") as mock_ui, \
         patch("tools.delta_context.shadow_pipeline.mutate_create_transaction") as mock_tx, \
         patch("tools.delta_context.shadow_pipeline.create_commit") as mock_cc, \
         patch("tools.delta_context.shadow_pipeline.verify_commit_exists") as mock_vc, \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("tools.delta_context.shadow_pipeline.classify_stage0", return_value={
             "state": "NOT_STARTED",
             "gate": "ALLOW_NEW_EXECUTION",
             "reason": "TEST_STAGE0_BYPASS",
             "metadata": {"test_only": True}
         }), \
         patch("tools.delta_context.shadow_pipeline.run_with_collapse_gate", side_effect=mock_validate), \
         patch("tools.delta_context.shadow_pipeline.record_divergence"), \
         patch("tools.delta_context.shadow_pipeline.get_divergence_summary", return_value={}), \
         patch("tools.delta_context.shadow_pipeline.record_session"), \
         patch("os.path.isdir", return_value=False):

        mock_wd.return_value = {
            "success": True,
            "delta": {"target_key": "test_key", "new_value": "test_value"},
            "path": "/fake/path",
        }
        mock_ui.return_value = {"success": True}
        mock_tx.return_value = {"success": True, "tx_id": "TX-S72", "transaction_hash": "hash"}
        mock_cc.return_value = {"success": True, "commit_id": "COMMIT-S72"}
        mock_vc.return_value = {"exists": True, "hard_stop": False}

        run_shadow_pipeline(
            session_number=72,
            delta_requests=[VALID_DELTA_REQUEST],
            generated_at=VALID_GENERATED_AT,
            ssot_payload_provider=mock_ssot_payload_provider,
        )

    assert "ssot_payload" in captured["ctx"]
    assert captured["ctx"]["ssot_payload"].get("generated_at") == VALID_GENERATED_AT


# TC-7: candidate_payload.generated_at == ssot_payload.generated_at
def test_tc7_candidate_ssot_generated_at_identical():
    captured = {}


    def mock_ssot_payload_provider(**kwargs):
        return {
            "session_number": kwargs.get("session_number"),
            "written_deltas": kwargs.get("written_deltas"),
            "generated_at": kwargs.get("generated_at"),
            "source": "mock_ssot_payload_provider",
        }
    def mock_validate(ctx):
        captured["ctx"] = ctx
        return {
            "phase2_valid": True,
            "preconditions": {"passed": True, "failed_conditions": []},
            "contract": {"contract": "PASS"},
        }

    with patch("tools.delta_context.shadow_pipeline.write_delta") as mock_wd, \
         patch("tools.delta_context.shadow_pipeline.update_index") as mock_ui, \
         patch("tools.delta_context.shadow_pipeline.mutate_create_transaction") as mock_tx, \
         patch("tools.delta_context.shadow_pipeline.create_commit") as mock_cc, \
         patch("tools.delta_context.shadow_pipeline.verify_commit_exists") as mock_vc, \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("builtins.open", side_effect=_make_open_mock()), \
         patch("tools.delta_context.shadow_pipeline.classify_stage0", return_value={
             "state": "NOT_STARTED",
             "gate": "ALLOW_NEW_EXECUTION",
             "reason": "TEST_STAGE0_BYPASS",
             "metadata": {"test_only": True}
         }), \
         patch("tools.delta_context.shadow_pipeline.run_with_collapse_gate", side_effect=mock_validate), \
         patch("tools.delta_context.shadow_pipeline.record_divergence"), \
         patch("tools.delta_context.shadow_pipeline.get_divergence_summary", return_value={}), \
         patch("tools.delta_context.shadow_pipeline.record_session"), \
         patch("os.path.isdir", return_value=False):

        mock_wd.return_value = {
            "success": True,
            "delta": {"target_key": "test_key", "new_value": "test_value"},
            "path": "/fake/path",
        }
        mock_ui.return_value = {"success": True}
        mock_tx.return_value = {"success": True, "tx_id": "TX-S72", "transaction_hash": "hash"}
        mock_cc.return_value = {"success": True, "commit_id": "COMMIT-S72"}
        mock_vc.return_value = {"exists": True, "hard_stop": False}

        run_shadow_pipeline(
            session_number=72,
            delta_requests=[VALID_DELTA_REQUEST],
            generated_at=VALID_GENERATED_AT,
            ssot_payload_provider=mock_ssot_payload_provider,
        )

    c_ts = captured["ctx"]["candidate_payload"].get("generated_at")
    s_ts = captured["ctx"]["ssot_payload"].get("generated_at")
    assert c_ts == s_ts


# TC-8: timestamp diff == 0 → TIMESTAMP_WINDOW 통과
def test_tc8_timestamp_diff_zero_window_pass():
    from tools.delta_context.phase2_validator import check_timestamp_window
    result = check_timestamp_window(VALID_GENERATED_AT, VALID_GENERATED_AT)
    assert result["within_window"] is True
    assert result["diff_seconds"] == 0.0


# TC-9: _runtime_observed_at이 generated_at source로 사용되지 않음 확인
def test_tc9_runtime_observed_at_not_used_as_generated_at_source():
    with patch("tools.delta_context.shadow_pipeline._runtime_observed_at") as mock_rat, \
         patch("os.path.isdir", return_value=False):
        mock_rat.return_value = "2026-01-01T00:00:00.000+09:00"

        result = run_shadow_pipeline(
            session_number=72,
            delta_requests=[VALID_DELTA_REQUEST],
            generated_at=VALID_GENERATED_AT,
        )

    # _runtime_observed_at이 호출되지 않아야 함
    mock_rat.assert_not_called()

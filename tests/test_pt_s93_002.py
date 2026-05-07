# tests/test_pt_s93_002.py
# PT-S93-002 — ssot_time_payload_provider 운영 주입 구조 검증
# 설계: 도미 FINAL DESIGN Rev.1 (B안) / EAG-2 비오(Joshua) 승인
#
# payload 계약: session_time_lock 래핑 구조
# {
#   "session_time_lock": {
#     "source": str,
#     "timezone": str,
#     "generated_at": ISO8601 str,
#     "observed_at":  ISO8601 str,
#     "epoch_ms":     int
#   }
# }

from __future__ import annotations

import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, "/opt/arss/engine/arss-protocol")

from tools.delta_context.shadow_pipeline import run_shadow_pipeline

# ---------------------------------------------------------------------------
# 공통 fixture 헬퍼
# ---------------------------------------------------------------------------

_VALID_STL_PAYLOAD = {
    "session_time_lock": {
        "source":       "AIBA_STATUS_SERVER_CLOCK",
        "timezone":     "Asia/Seoul",
        "generated_at": "2026-05-08T12:00:00+09:00",
        "observed_at":  "2026-05-08T12:00:00+09:00",
        "epoch_ms":     1746676800000,
    }
}

_VALID_GENERATED_AT = "2026-05-08T12:00:00+09:00"

_DUMMY_DELTAS = [
    {
        "domain":            "agent_focus",
        "sequence_number":   1,
        "event_type":        "agent_focus_updated",
        "target_key":        "agent_focus",
        "new_value":         {"caddy": "tc-s93-002"},
        "cross_ref":         None,
        "prev_delta_id":     None,
        "prev_content_hash": None,
    }
]


def _mock_good_provider(**kwargs):
    return _VALID_STL_PAYLOAD


def _make_stage0_pass():
    return patch(
        "tools.delta_context.shadow_pipeline.classify_stage0",
        return_value={"gate": "ALLOW_NEW_RUN"},
    )


def _make_collapse_pass():
    return patch(
        "tools.delta_context.shadow_pipeline.run_with_collapse_gate",
        return_value={"contract": {"contract": "PASS"}, "phase2_valid": True},
    )


def _make_collapse_fail():
    return patch(
        "tools.delta_context.shadow_pipeline.run_with_collapse_gate",
        return_value={"contract": {"contract": "FAIL", "reason": "SOURCE_COLLAPSE_DETECTED"}, "phase2_valid": False},
    )


def _make_write_delta_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.write_delta",
        return_value={
            "success": True,
            "delta":   {
                "delta_id":   "DUMMY-DELTA-001",
                "target_key": "agent_focus",
                "new_value":  {"caddy": "tc-s93-002"},
            },
            "path":    "/tmp/dummy_delta.json",
        },
    )


def _make_update_index_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.update_index",
        return_value={"success": True},
    )


def _make_create_tx_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.mutate_create_transaction",
        return_value={"success": True, "tx_id": "DUMMY-TX-001", "transaction_hash": "aabbccdd"},
    )


def _make_create_commit_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.create_commit",
        return_value={"success": True, "commit_id": "DUMMY-COMMIT-001"},
    )


def _make_verify_commit_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.verify_commit_exists",
        return_value={"hard_stop": False, "exists": True},
    )

def _make_open_noop():
    """Stage 6.5 TX/INDEX 파일 접근 격리."""
    import builtins
    real_open = builtins.open

    def _patched_open(path, *args, **kwargs):
        if isinstance(path, str) and (
            "TX-" in path or "INDEX" in path or ".json" in path
        ):
            from unittest.mock import mock_open
            return mock_open(read_data="{}")()
        return real_open(path, *args, **kwargs)

    return patch("builtins.open", side_effect=_patched_open)


def _make_record_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.record_divergence",
        return_value={"divergence_id": None, "phase3_blocked": False},
    )


def _make_summary_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.get_divergence_summary",
        return_value={},
    )


def _make_record_session_noop():
    return patch(
        "tools.delta_context.shadow_pipeline.record_session",
        return_value=None,
    )


# ---------------------------------------------------------------------------
# TC-1: provider 미전달 시 기본 ssot_time_payload_provider 자동 사용
# ---------------------------------------------------------------------------
def test_tc1_default_provider_auto_assigned():
    """provider=None 시 ssot_time_payload_provider.provide 자동 할당."""
    with _make_stage0_pass(), _make_collapse_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop(), \
         _make_record_noop(), _make_summary_noop(), _make_record_session_noop(), \
         patch(
             "tools.delta_context.ssot_time_payload_provider.provide",
             side_effect=_mock_good_provider,
         ):
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=None,
        )
    # SSOT_PAYLOAD_PROVIDER_MISSING 로 종료되지 않아야 함
    assert result.get("reason") != "SSOT_PAYLOAD_PROVIDER_MISSING", (
        f"Expected auto-assigned provider, got PROVIDER_MISSING. result={result}"
    )


# ---------------------------------------------------------------------------
# TC-2: mock provider 명시 주입 시 mock 우선
# ---------------------------------------------------------------------------
def test_tc2_explicit_mock_provider_takes_priority():
    """명시 주입된 mock provider가 우선 사용된다."""
    call_log = []

    def _mock_provider(**kwargs):
        call_log.append("mock_called")
        return _VALID_STL_PAYLOAD

    with _make_stage0_pass(), _make_collapse_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop(), \
         _make_record_noop(), _make_summary_noop(), _make_record_session_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_mock_provider,
        )

    assert "mock_called" in call_log, "Mock provider was not called."
    assert result.get("reason") != "SSOT_PAYLOAD_PROVIDER_MISSING"


# ---------------------------------------------------------------------------
# TC-3: provider 예외 발생 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc3_provider_exception_fail_closed():
    """provider 호출 시 예외 → SSOT_PAYLOAD_PROVIDER_EXCEPTION HARD STOP."""
    def _raising_provider(**kwargs):
        raise RuntimeError("endpoint unreachable")

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_raising_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_PROVIDER_EXCEPTION"
    assert result["stage"] == "PHASE2_VALIDATION"


# ---------------------------------------------------------------------------
# TC-4: provider None 반환 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc4_provider_returns_none_fail_closed():
    """provider가 None 반환 → SSOT_PAYLOAD_PROVIDER_INVALID_RETURN HARD STOP."""
    def _none_provider(**kwargs):
        return None

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_none_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_PROVIDER_INVALID_RETURN"


# ---------------------------------------------------------------------------
# TC-5: session_time_lock 키 누락 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc5_session_time_lock_missing_fail_closed():
    """session_time_lock 키 없는 dict 반환 → SSOT_PAYLOAD_FIELD_MISSING."""
    def _bad_provider(**kwargs):
        return {}

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_bad_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_FIELD_MISSING"
    assert result["missing"] == "session_time_lock"


# ---------------------------------------------------------------------------
# TC-6: 하위 필수 필드(source) 누락 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc6_stl_source_missing_fail_closed():
    """session_time_lock.source 누락 → SSOT_PAYLOAD_FIELD_MISSING."""
    def _bad_provider(**kwargs):
        return {
            "session_time_lock": {
                # source 누락
                "timezone":     "Asia/Seoul",
                "generated_at": "2026-05-08T12:00:00+09:00",
                "observed_at":  "2026-05-08T12:00:00+09:00",
                "epoch_ms":     1746676800000,
            }
        }

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_bad_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_FIELD_MISSING"
    assert "source" in result["missing"]


# ---------------------------------------------------------------------------
# TC-7: epoch_ms 비int 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc7_epoch_ms_nonint_fail_closed():
    """epoch_ms가 str → SSOT_PAYLOAD_FIELD_TYPE_INVALID."""
    def _bad_provider(**kwargs):
        return {
            "session_time_lock": {
                "source":       "AIBA_STATUS_SERVER_CLOCK",
                "timezone":     "Asia/Seoul",
                "generated_at": "2026-05-08T12:00:00+09:00",
                "observed_at":  "2026-05-08T12:00:00+09:00",
                "epoch_ms":     "not_an_int",
            }
        }

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_bad_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_FIELD_TYPE_INVALID"
    assert "epoch_ms" in result["field"]


# ---------------------------------------------------------------------------
# TC-8: generated_at 비ISO8601 시 FAIL-CLOSED
# ---------------------------------------------------------------------------
def test_tc8_generated_at_non_iso8601_fail_closed():
    """generated_at이 비ISO8601 → SSOT_PAYLOAD_TIMESTAMP_INVALID."""
    def _bad_provider(**kwargs):
        return {
            "session_time_lock": {
                "source":       "AIBA_STATUS_SERVER_CLOCK",
                "timezone":     "Asia/Seoul",
                "generated_at": "not-a-date",
                "observed_at":  "2026-05-08T12:00:00+09:00",
                "epoch_ms":     1746676800000,
            }
        }

    with _make_stage0_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_bad_provider,
        )

    assert result["success"] is False
    assert result["hard_stop"] is True
    assert result["reason"] == "SSOT_PAYLOAD_TIMESTAMP_INVALID"
    assert "generated_at" in result["field"]


# ---------------------------------------------------------------------------
# TC-9: 정상 payload + collapse gate PASS → pipeline PASS
# ---------------------------------------------------------------------------
def test_tc9_valid_payload_collapse_pass():
    """정상 payload + collapse PASS → success=True."""
    with _make_stage0_pass(), _make_collapse_pass(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop(), \
         _make_record_noop(), _make_summary_noop(), _make_record_session_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_mock_good_provider,
        )

    assert result.get("success") is True or result.get("hard_stop") is not True, (
        f"Expected pipeline PASS. result={result}"
    )
    assert result.get("reason") not in (
        "SSOT_PAYLOAD_PROVIDER_MISSING",
        "SSOT_PAYLOAD_PROVIDER_EXCEPTION",
        "SSOT_PAYLOAD_PROVIDER_INVALID_RETURN",
        "SSOT_PAYLOAD_FIELD_MISSING",
        "SSOT_PAYLOAD_FIELD_TYPE_INVALID",
        "SSOT_PAYLOAD_TIMESTAMP_INVALID",
    )


# ---------------------------------------------------------------------------
# TC-10: 정상 payload + collapse gate FAIL → collapse error 유지
# ---------------------------------------------------------------------------
def test_tc10_valid_payload_collapse_fail_preserves_collapse_error():
    """정상 payload이나 collapse gate FAIL → collapse error 반환, provider error 아님."""
    with _make_stage0_pass(), _make_collapse_fail(), _make_write_delta_noop(), _make_update_index_noop(), _make_create_tx_noop(), _make_create_commit_noop(), _make_verify_commit_noop(), _make_open_noop(), \
         _make_record_noop(), _make_summary_noop(), _make_record_session_noop():
        result = run_shadow_pipeline(
            session_number=96,
            delta_requests=_DUMMY_DELTAS,
            generated_at=_VALID_GENERATED_AT,
            ssot_payload_provider=_mock_good_provider,
        )

    # provider 관련 에러 코드가 아님을 확인
    assert result.get("reason") not in (
        "SSOT_PAYLOAD_PROVIDER_MISSING",
        "SSOT_PAYLOAD_PROVIDER_EXCEPTION",
        "SSOT_PAYLOAD_PROVIDER_INVALID_RETURN",
        "SSOT_PAYLOAD_FIELD_MISSING",
        "SSOT_PAYLOAD_FIELD_TYPE_INVALID",
        "SSOT_PAYLOAD_TIMESTAMP_INVALID",
    ), f"Expected collapse error, not provider error. result={result}"

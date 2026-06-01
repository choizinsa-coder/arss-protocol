# RULE-8 ASSERTION — S181 Batch-12B
# Module: mcp_write_server
# Task: P4-C4 Phase-beta Batch-12B
#
# NOTE: WS-3/WS-4 제외
# BUG-S181-WS-RECOVERY-ENUM-MISMATCH:
#   handle_receipt_finalize 내 state.__class__.RECOVERY_MODE 참조 불일치
#   (실제 enum 멤버: RECOVERY) → AttributeError 발생
#   → 별도 Bugfix Track으로 분리 (도미 설계 / 제니 검토 / 비오 EAG 선행 필요)
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import pytest
from unittest.mock import patch


def test_ws_write_file_missing_target_path_returns_error():
    """WS-1: handle_write_file target_path 없음(None) → ok=False."""
    from tools.mcp.mcp_write_server import handle_write_file
    result = handle_write_file(
        approval_id="some-id",
        target_path=None,
        content="content",
    )
    assert result["ok"] is False


def test_ws_write_file_tier1_missing_approval_id_returns_error():
    """WS-2: TIER1 경로 + approval_id 없음 → ok=False (CONTRACT-04).
    route_request mock: TIER1 분류 강제 (Write Server 실행 없음).
    """
    from tools.mcp.mcp_write_server import handle_write_file
    from tools.mcp_write.tier_router import TierClassification

    with patch("tools.mcp.mcp_write_server.route_request",
               return_value=TierClassification.TIER1):
        result = handle_write_file(
            approval_id="",
            target_path="/opt/arss/engine/arss-protocol/tools/sandbox/test.md",
            content="content",
        )
    assert result["ok"] is False
    assert "CONTRACT-04" in result.get("error", "") or "approval_id" in result.get("error", "")


def test_ws_set_state_invalid_state_string_returns_400():
    """WS-5: handle_set_state — 유효하지 않은 WritePlaneState 문자열 → (400, ok=False)."""
    from tools.mcp.mcp_write_server import handle_set_state
    status, body = handle_set_state("INVALID_STATE_XYZ")
    assert status == 400
    assert body["ok"] is False

# RULE-8 ASSERTION — S181 Batch-12A
# Module: mcp_audit_broker
# Task: P4-C4 Phase-beta Batch-12A
import sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")

import json
import os
import tempfile
import time
import pytest
from unittest.mock import patch


def test_ab_read_audit_log_missing_file_returns_empty():
    """AB-1: 존재하지 않는 파일 경로 → [] 반환."""
    from tools.mcp.mcp_audit_broker import read_audit_log
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = os.path.join(tmpdir, "no_such_log.json")
        result = read_audit_log(log_path=missing)
    assert result == []


def test_ab_read_audit_log_skips_invalid_json_lines():
    """AB-2: 잘못된 JSON 라인 포함 → 유효 레코드만 반환."""
    from tools.mcp.mcp_audit_broker import read_audit_log
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log",
                                     delete=False) as f:
        f.write('{"decision": "ALLOW", "agent_id": "caddy"}\n')
        f.write('INVALID_LINE_NOT_JSON\n')
        f.write('{"decision": "DENY", "agent_id": "domi"}\n')
        tmp_path = f.name
    try:
        result = read_audit_log(log_path=tmp_path)
        assert len(result) == 2
        assert result[0]["decision"] == "ALLOW"
        assert result[1]["decision"] == "DENY"
    finally:
        os.unlink(tmp_path)


def test_ab_write_deny_audit_preserves_deny_contract():
    """AB-3: write_deny_audit → decision=DENY / retrieval_class=CLASS-D 계약 보존."""
    from tools.mcp.mcp_audit_broker import write_deny_audit
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.log")
        record = write_deny_audit(
            agent_id="test_agent",
            requested_shard="test_shard",
            reason="UNIT_TEST",
            log_path=log_path,
        )
    assert record["decision"] == "DENY"
    assert record["retrieval_class"] == "CLASS-D"
    assert record["returned_scope"] == "NONE"


def test_ab_write_audit_raises_on_makedirs_failure():
    """AB-4: os.makedirs OSError → write_audit가 OSError re-raise.
    root 권한 환경에서 임의 경로 생성을 막기 위해 makedirs patch.
    HC-T-05 side effect 차단: _trigger_hct05 mock.
    """
    from tools.mcp.mcp_audit_broker import write_audit
    with patch("tools.mcp.mcp_audit_broker.os.makedirs",
               side_effect=OSError("mocked makedirs failure")):
        with patch("tools.mcp.mcp_audit_broker._trigger_hct05"):
            with pytest.raises(OSError):
                write_audit(
                    agent_id="caddy",
                    requested_shard="test_shard",
                    returned_scope="NONE",
                    decision="DENY",
                    reason="UNIT_TEST",
                    log_path="/any/path/audit.log",
                )


def test_ab_audit_broker_submit_event_timeout_raises():
    """AB-5: AuditBroker submit_event — ledger blocking → AuditPersistenceError.
    blocking ledger mock으로 실제 1초 대기 없이 timeout 유발.
    """
    from tools.mcp.mcp_audit_broker import AuditBroker, AuditPersistenceError

    class _BlockingLedger:
        """write()가 영구 blocking하는 mock ledger."""
        def write(self, entry):
            time.sleep(10)

    broker = AuditBroker(ledger=_BlockingLedger())
    with pytest.raises(AuditPersistenceError):
        broker.submit_event(
            tool_name="test_tool",
            layer="TEST",
            result_summary="unit_test",
            phase="BATCH_12A",
        )

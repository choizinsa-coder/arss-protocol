"""
test_audit_isolation_guard.py - WP-3 (S373)
EAG: EAG-S373-TEST-ISOLATION-FIX-IMPL-001
Verifies audit broker production-log isolation (conftest autouse fixture).
"""

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "mcp"
))

import mcp_audit_broker as broker_mod  # noqa: E402
import mcp_server_poc as poc  # noqa: E402

_PROD_AUDIT_LOG_PATH = "/opt/arss/engine/arss-protocol/tools/mcp/audit_trail.log"


def test_isolation_deny_goes_to_tmp_only():
    poc._throttle_guard = None
    with pytest.raises(PermissionError):
        poc._dispatch("mystery_tool_isolation_probe")
    poc._throttle_guard = None
    assert broker_mod.AUDIT_LOG_PATH != _PROD_AUDIT_LOG_PATH
    assert broker_mod.AUDIT_LOG_PATH.endswith("test_audit_trail.log")
    time.sleep(0.2)
    tmp_log = broker_mod.AUDIT_LOG_PATH
    assert os.path.exists(tmp_log)
    content = open(tmp_log, encoding="utf-8").read()
    assert "mystery_tool_isolation_probe" in content
    assert "TOOL_DENY" in content


def test_isolation_production_log_size_unchanged():
    before = os.path.getsize(_PROD_AUDIT_LOG_PATH) if os.path.exists(_PROD_AUDIT_LOG_PATH) else 0
    poc._throttle_guard = None
    with pytest.raises(PermissionError):
        poc._dispatch("mystery_tool_size_probe")
    poc._throttle_guard = None
    time.sleep(0.2)
    after = os.path.getsize(_PROD_AUDIT_LOG_PATH) if os.path.exists(_PROD_AUDIT_LOG_PATH) else 0
    assert before == after


def test_isolation_constructor_guard_blocks_production():
    triggered = False
    try:
        broker_mod._AppendOnlyLedger(_PROD_AUDIT_LOG_PATH)
    except BaseException as e:
        triggered = True
        assert "AUDIT Isolation" in str(e)
    assert triggered


def test_isolation_injected_ledger_preserved():
    class _CaptureLedger:
        def __init__(self):
            self.entries = []
        def write(self, entry):
            self.entries.append(entry)
    ledger = _CaptureLedger()
    broker = broker_mod.AuditBroker(ledger=ledger)
    broker.submit_event("ping", "L0", "ok", "PHASE-B")
    time.sleep(0.2)
    assert any(e.get("tool_name") == "ping" for e in ledger.entries)


def test_isolation_per_test_tmp_unique():
    poc._throttle_guard = None
    with pytest.raises(PermissionError):
        poc._dispatch("mystery_tool_pertest_probe")
    poc._throttle_guard = None
    time.sleep(0.2)
    tmp_log = broker_mod.AUDIT_LOG_PATH
    assert os.path.exists(tmp_log)
    content = open(tmp_log, encoding="utf-8").read()
    assert "mystery_tool_isolation_probe" not in content
    assert "mystery_tool_pertest_probe" in content

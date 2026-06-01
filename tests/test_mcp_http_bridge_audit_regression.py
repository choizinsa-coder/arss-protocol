"""
test_mcp_http_bridge_audit_regression.py
AIBA S183 - MCP Bridge Audit Signature Regression 회귀 테스트 (RT-1 ~ RT-5)
BRIEFING-DOMI-S183-001 / EAG-2-PACKAGE-S183-001

배경:
  기존 test_mcp_http_bridge_v2.py 는 write_audit / write_deny_audit 를 permissive MagicMock
  으로 patch 하여 호출부-정본 시그니처 불일치를 검출하지 못했다(회귀 은폐).
  본 모듈은 create_autospec 로 정본 시그니처를 강제하여 동일 회귀를 구조적으로 차단한다.

정본 시그니처(mcp_audit_broker.py):
  write_deny_audit(agent_id, requested_shard, reason, nonce=None, log_path=None)
  write_audit(agent_id, requested_shard, returned_scope, decision, reason,
              source_hash=None, load_state="UNKNOWN", retrieval_class="UNKNOWN",
              nonce=None, log_path=None)
"""

import os
import sys
import unittest
from unittest.mock import patch, create_autospec

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools', 'mcp'))

import mcp_http_bridge as bridge
from mcp_audit_broker import write_audit as real_write_audit
from mcp_audit_broker import write_deny_audit as real_write_deny_audit


def _gov_ctx(containment):
    return {
        "actor_id": bridge.INTERNAL_ACTOR_ID,
        "bridge_state": "ACTIVE",
        "containment_active": containment,
    }


class RT1_DenyCallerMatchesBrokerSignature(unittest.TestCase):
    """RT-1: _audit_deny 호출이 write_deny_audit 정본 시그니처와 정합 (TypeError 미발생)."""

    def test_rt1(self):
        spec = create_autospec(real_write_deny_audit)
        with patch("mcp_http_bridge.write_deny_audit", spec):
            bridge._audit_deny(_gov_ctx(True), "RT1_REASON")
        spec.assert_called_once()
        kwargs = spec.call_args.kwargs
        self.assertEqual(set(kwargs), {"agent_id", "requested_shard", "reason"})
        self.assertEqual(kwargs["agent_id"], bridge.INTERNAL_ACTOR_ID)


class RT2_AllowCallerMatchesBrokerSignature(unittest.TestCase):
    """RT-2: _audit_allow 호출이 write_audit 정본 시그니처와 정합 (TypeError 미발생)."""

    def test_rt2(self):
        spec = create_autospec(real_write_audit)
        with patch("mcp_http_bridge.write_audit", spec):
            bridge._audit_allow(_gov_ctx(False), "RT2_SCOPE", "RT2_REASON")
        spec.assert_called_once()


class RT3_ContainmentDenyReturnsJsonRpcError(unittest.TestCase):
    """RT-3: containment_active=True + request -> JSON-RPC error 반환, 예외/크래시 미발생."""

    def test_rt3(self):
        spec = create_autospec(real_write_deny_audit)
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        with patch("mcp_http_bridge.write_deny_audit", spec):
            resp = bridge._handle_jsonrpc(body, _gov_ctx(True))
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], bridge.CONTAINMENT_ERROR_CODE)


class RT4_AuthlessModelUnchanged(unittest.TestCase):
    """RT-4: S133 authless 모델 불변 - actor_id 고정 주입 + allowlist 유지 + initialize 정상."""

    def test_rt4_internal_actor(self):
        self.assertEqual(bridge.INTERNAL_ACTOR_ID, "claude_ai_remote_connector")

    def test_rt4_allowlist(self):
        self.assertIn("ping", bridge.ALLOWED_TOOLS)
        self.assertIn("get_load_state", bridge.ALLOWED_TOOLS)

    def test_rt4_initialize(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        with patch("mcp_http_bridge.write_audit"), \
             patch("mcp_http_bridge.write_deny_audit"):
            resp = bridge._handle_jsonrpc(body, _gov_ctx(False))
        self.assertEqual(resp["id"], 1)
        self.assertIn("result", resp)
        self.assertEqual(
            resp["result"]["serverInfo"]["name"], "ARSS Protocol MCP Bridge"
        )


class RT5_AuditFailureNotTransportFailure(unittest.TestCase):
    """RT-5: write_deny_audit 예외 시에도 denial 응답이 정상 반환 (감사 실패 != 전송 실패)."""

    def test_rt5(self):
        body = {"jsonrpc": "2.0", "id": 7, "method": "initialize", "params": {}}
        with patch("mcp_http_bridge.write_deny_audit",
                   side_effect=Exception("forced audit failure")):
            resp = bridge._handle_jsonrpc(body, _gov_ctx(True))
        self.assertIsNotNone(resp)
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], bridge.CONTAINMENT_ERROR_CODE)


if __name__ == "__main__":
    unittest.main()

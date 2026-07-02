"""
test_orchestration_rev2.py
오케스트레이션 Rev.2 B/C항목 검증

설계 근거: S197 EAG-1 비오(Joshua) 승인
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# sys.path 주입 (importlib 모드 대응)
_ARSS_ROOT = os.path.realpath(
    os.path.join(os.path.dirname(__file__), "..")
)
if _ARSS_ROOT not in sys.path:
    sys.path.insert(0, _ARSS_ROOT)

# ── B-2: change_control_tier 구조 검증 ────────────────────────────────────────

class TestChangeControlTierStructure(unittest.TestCase):
    """B-2: caddy_operational_rules.json change_control_tier 서브필드 검증"""

    def _load_rules(self):
        rules_path = os.path.join(
            _ARSS_ROOT, "context/agents/caddy_operational_rules.json"
        )
        with open(rules_path, encoding="utf-8") as f:
            return json.load(f)

    def test_b2_change_control_tier_exists(self):
        """B-2-1: change_control_tier 필드가 body에 존재한다"""
        rules = self._load_rules()
        self.assertIn("change_control_tier", rules["body"])

    def test_b2_current_scope_is_tight(self):
        """B-2-2: 기본 current_scope는 tight이다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        self.assertEqual(tier["current_scope"], "tight")

    def test_b2_scope_definitions_all_present(self):
        """B-2-3: scope_definitions에 tight/normal/broad 모두 정의되어 있다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        defs = tier["scope_definitions"]
        self.assertIn("tight", defs)
        self.assertIn("normal", defs)
        self.assertIn("broad", defs)

    def test_b2_max_retry_broad_is_5(self):
        """B-2-4: max_retry_broad는 5이다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        self.assertEqual(tier["max_retry_broad"], 5)

    def test_b2_allowed_auto_fix_types(self):
        """B-2-5: allowed_auto_fix_types에 assert_value_change가 포함된다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        self.assertIn("assert_value_change", tier["allowed_auto_fix_types"])

    def test_b2_forbidden_auto_fix_types(self):
        """B-2-6: forbidden_auto_fix_types에 logic_change 등 4종이 포함된다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        forbidden = tier["forbidden_auto_fix_types"]
        for expected in ["logic_change", "new_file", "import_change", "function_change"]:
            self.assertIn(expected, forbidden)

    def test_b2_classifier_module_path(self):
        """B-2-7: classifier_module 경로가 올바르다"""
        rules = self._load_rules()
        tier = rules["body"]["change_control_tier"]
        self.assertEqual(
            tier["classifier_module"],
            "tools/exec_runtime/change_classifier.py"
        )

    def test_b2_item_count_updated(self):
        """B-2-8: summary.item_count가 13으로 업데이트되었다"""
        rules = self._load_rules()
        self.assertEqual(rules["summary"]["item_count"], 13)

    def test_b2_last_updated_session(self):
        """B-2-9: last_updated_session이 197이다"""
        rules = self._load_rules()
        self.assertEqual(rules["shard_meta"]["last_updated_session"], 197)

    def test_b2_canonical_key_ceiling_not_violated(self):
        """B-2-10: change_control_tier는 최상위 키 추가가 아닌 서브필드 확장이다"""
        # caddy_operational_rules 자체는 SESSION_CONTEXT 최상위 키이며
        # change_control_tier는 그 body 내부 서브필드 — ceiling 영향 없음
        rules = self._load_rules()
        # body 내부 항목으로 존재해야 함 (최상위 아님)
        self.assertIn("change_control_tier", rules["body"])
        # 최상위 key 목록에는 body/summary/shard_meta만 존재
        top_keys = set(rules.keys())
        self.assertNotIn("change_control_tier", top_keys)


# ── C-5: exec_runtime session_audit_id 검증 ──────────────────────────────────

class TestExecRuntimeSessionAuditId(unittest.TestCase):
    """C-5: aiba_exec_runtime.py v1.1.0 session_audit_id 지원 검증"""

    def setUp(self):
        sys.path.insert(0, os.path.join(_ARSS_ROOT, "tools/exec_runtime"))

    def test_c5_version_is_1_1_0(self):
        """C-5-1: exec_runtime 버전이 1.1.0이다"""
        import importlib
        import aiba_exec_runtime as er
        importlib.reload(er)
        self.assertEqual(er.EXEC_RUNTIME_VERSION, "1.5.0")

    def test_c5_write_audit_accepts_session_audit_id(self):
        """C-5-2: _write_audit가 session_audit_id 파라미터를 수용한다"""
        import aiba_exec_runtime as er
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name
        try:
            with patch.object(er, "AUDIT_LOG_PATH", log_path):
                result = er._write_audit(
                    audit_id="test-audit-001",
                    stage="PRE",
                    command="pytest",
                    actor_id="caddy",
                    approval_id="eag-001",
                    detail="test",
                    session_audit_id="SA-test-abc",
                )
            self.assertTrue(result)
            with open(log_path, encoding="utf-8") as f:
                entry = json.loads(f.read().strip())
            self.assertEqual(entry["session_audit_id"], "SA-test-abc")
        finally:
            os.unlink(log_path)

    def test_c5_write_audit_without_session_audit_id(self):
        """C-5-3: session_audit_id 없으면 audit entry에 해당 필드 미포함 (backward compatible)"""
        import aiba_exec_runtime as er
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name
        try:
            with patch.object(er, "AUDIT_LOG_PATH", log_path):
                result = er._write_audit(
                    audit_id="test-audit-002",
                    stage="PRE",
                    command="git_status",
                    actor_id="caddy",
                    approval_id="eag-001",
                    detail="test",
                )
            self.assertTrue(result)
            with open(log_path, encoding="utf-8") as f:
                entry = json.loads(f.read().strip())
            self.assertNotIn("session_audit_id", entry)
        finally:
            os.unlink(log_path)

    def test_c5_write_audit_session_audit_id_none_excluded(self):
        """C-5-4: session_audit_id=None이면 audit entry에서 제외된다"""
        import aiba_exec_runtime as er
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as f:
            log_path = f.name
        try:
            with patch.object(er, "AUDIT_LOG_PATH", log_path):
                er._write_audit(
                    audit_id="test-audit-003",
                    stage="POST_OK",
                    command="pytest",
                    actor_id="caddy",
                    approval_id="eag-001",
                    detail="test",
                    session_audit_id=None,
                )
            with open(log_path, encoding="utf-8") as f:
                entry = json.loads(f.read().strip())
            self.assertNotIn("session_audit_id", entry)
        finally:
            os.unlink(log_path)



    def test_c5_allowed_services_contains_exec_runtime(self):
        """S203 EAG-1: exec_runtime ALLOWED_SERVICES에 aiba-exec-runtime 포함 검증"""
        import importlib
        import aiba_exec_runtime as er
        importlib.reload(er)
        self.assertIn("aiba-exec-runtime", er.ALLOWED_SERVICES)
        self.assertEqual(len(er.ALLOWED_SERVICES), 4)

# ── C-5: bridge session_audit_id 발행 검증 ────────────────────────────────────

class TestBridgeSessionAuditIdIssuing(unittest.TestCase):
    """C-5: bridge _handle_exec_scoped session_audit_id 발행 검증"""

    def setUp(self):
        sys.path.insert(0, os.path.join(_ARSS_ROOT, "tools/mcp"))

    def _mock_exec_response(self, ok=True, exit_code=0):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "ok": ok,
            "command": "pytest",
            "stdout": "passed",
            "stderr": "",
            "exit_code": exit_code,
            "audit_id": "child-audit-001",
            "approval_id": "eag-001",
        }).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    def test_c5_bridge_version_is_2_5_0(self):
        """C-5-5: bridge 버전이 2.5.0이다"""
        import importlib
        import mcp_http_bridge as bridge
        importlib.reload(bridge)
        self.assertEqual(bridge.BRIDGE_VERSION, "2.9.0")

    def test_c5_exec_scoped_generates_session_audit_id(self):
        """C-5-6: exec_scoped 호출 시 session_audit_id가 발행된다"""
        import mcp_http_bridge as bridge
        arguments = {
            "actor_id": "caddy",
            "approval_id": "eag-001",
            "command": "pytest",
            "params": {"path": "/opt/arss/engine/arss-protocol/tests"},
        }
        with patch("urllib.request.urlopen", return_value=self._mock_exec_response()):
            result = bridge._handle_exec_scoped(arguments)
        self.assertFalse(result.get("isError", True))
        content_text = result["content"][0]["text"]
        parsed = json.loads(content_text)
        self.assertIn("session_audit_id", parsed)
        self.assertTrue(parsed["session_audit_id"].startswith("SA-"))

    def test_c5_exec_scoped_uses_provided_session_audit_id(self):
        """C-5-7: 외부 session_audit_id 제공 시 해당 값을 사용한다"""
        import mcp_http_bridge as bridge
        provided_id = "SA-test-provided-123"
        arguments = {
            "actor_id": "caddy",
            "approval_id": "eag-001",
            "command": "git_status",
            "params": {},
            "session_audit_id": provided_id,
        }
        with patch("urllib.request.urlopen", return_value=self._mock_exec_response()):
            result = bridge._handle_exec_scoped(arguments)
        content_text = result["content"][0]["text"]
        parsed = json.loads(content_text)
        self.assertEqual(parsed["session_audit_id"], provided_id)

    def test_c5_exec_scoped_forwards_session_audit_id_to_runtime(self):
        """C-5-8: exec_scoped가 session_audit_id를 exec_runtime에 전달한다"""
        import mcp_http_bridge as bridge
        import urllib.request as ur
        captured_body = {}

        def mock_urlopen(req, timeout=None):
            captured_body["data"] = json.loads(req.data.decode())
            return self._mock_exec_response()

        arguments = {
            "actor_id": "caddy",
            "approval_id": "eag-001",
            "command": "git_diff",
            "params": {},
        }
        with patch.object(ur, "urlopen", mock_urlopen):
            bridge._handle_exec_scoped(arguments)

        self.assertIn("session_audit_id", captured_body["data"])
        self.assertTrue(captured_body["data"]["session_audit_id"].startswith("SA-"))

    def test_c5_exec_fail_still_returns_session_audit_id(self):
        """C-5-9: exec 실패 시에도 session_audit_id가 응답에 포함된다"""
        import mcp_http_bridge as bridge
        arguments = {
            "actor_id": "caddy",
            "approval_id": "eag-001",
            "command": "pytest",
            "params": {"path": "/opt/arss/engine/arss-protocol/tests"},
        }
        with patch("urllib.request.urlopen", return_value=self._mock_exec_response(ok=False, exit_code=1)):
            result = bridge._handle_exec_scoped(arguments)
        self.assertTrue(result.get("isError", False))
        content_text = result["content"][0]["text"]
        parsed = json.loads(content_text)
        self.assertIn("session_audit_id", parsed)

    def test_c5_exec_actor_deny_no_session_audit_id(self):
        """C-5-10: actor DENY 시 session_audit_id 없이 즉시 거부된다"""
        import mcp_http_bridge as bridge
        arguments = {
            "actor_id": "domi",  # caddy만 허용
            "approval_id": "eag-001",
            "command": "pytest",
            "params": {},
        }
        result = bridge._handle_exec_scoped(arguments)
        self.assertTrue(result.get("isError", False))
        self.assertIn("DENY", result["content"][0]["text"])

    def test_c5_approval_id_required(self):
        """C-5-11: approval_id 없으면 DENY된다"""
        import mcp_http_bridge as bridge
        arguments = {
            "actor_id": "caddy",
            "approval_id": "",
            "command": "pytest",
            "params": {},
        }
        result = bridge._handle_exec_scoped(arguments)
        self.assertTrue(result.get("isError", False))
        self.assertIn("approval_id", result["content"][0]["text"])

    def test_c5_invalid_command_deny(self):
        """C-5-12: whitelist 외 command는 DENY된다"""
        import mcp_http_bridge as bridge
        arguments = {
            "actor_id": "caddy",
            "approval_id": "eag-001",
            "command": "rm_rf",  # 금지 명령
            "params": {},
        }
        result = bridge._handle_exec_scoped(arguments)
        self.assertTrue(result.get("isError", False))
        self.assertIn("whitelist", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()

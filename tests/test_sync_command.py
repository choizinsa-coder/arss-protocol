"""
tests/test_sync_command.py
/sync MCP 명령어 단위 테스트 — EAG-S205-SYNC-001
"""
import sys
import os
import json
import pytest
from unittest.mock import patch, mock_open

sys.path.insert(0, '/opt/arss/engine/arss-protocol')
sys.path.insert(0, '/opt/arss/engine/arss-protocol/tools/mcp')
os.environ.setdefault("AIBA_READ_HMAC_SECRET", "test-secret-sync-s205")

import mcp_http_bridge as bridge

CANONICAL_HASH = "4985f527688a4b36cf58c17584980028b24edcc174f68c6ebdea68f84d68b2ab"
CANONICAL_TIP  = "7256634"
MOCK_POINTER   = json.dumps({
    "last_session": 204,
    "chain_tip": CANONICAL_TIP,
    "context_hash": CANONICAL_HASH,
    "updated_at": "2026-06-08T01:00:00.000000+09:00",
    "schema_version": "1.0",
})


class TestHandleSync:

    def _call(self, actor_id, context_hash, pointer_json=None):
        data = pointer_json if pointer_json is not None else MOCK_POINTER
        with patch("builtins.open", mock_open(read_data=data)):
            return bridge._handle_sync({"actor_id": actor_id, "context_hash": context_hash})

    def test_sync_ok(self):
        """TC-01: SYNC_OK — 일치하는 hash"""
        result = self._call("caddy", CANONICAL_HASH)
        assert not result["isError"]
        p = json.loads(result["content"][0]["text"])
        assert p["status"] == "SYNC_OK"
        assert p["match"] is True
        assert p["canonical_context_hash"] == CANONICAL_HASH
        assert p["canonical_chain_tip"] == CANONICAL_TIP

    def test_sync_mismatch(self):
        """TC-02: SYNC_MISMATCH — 불일치 hash"""
        result = self._call("caddy", "a" * 64)
        assert not result["isError"]
        p = json.loads(result["content"][0]["text"])
        assert p["status"] == "SYNC_MISMATCH"
        assert p["match"] is False
        assert p["canonical_context_hash"] == CANONICAL_HASH

    def test_deny_unknown_actor(self):
        """TC-03: 미허용 actor"""
        result = self._call("intruder", CANONICAL_HASH)
        assert result["isError"]
        assert "DENY" in result["content"][0]["text"]

    def test_deny_hash_too_short(self):
        """TC-04: context_hash 너무 짧음"""
        result = self._call("caddy", "abc123")
        assert result["isError"]
        assert "DENY" in result["content"][0]["text"]

    def test_deny_hash_non_hex(self):
        """TC-05: context_hash 비 16진수"""
        result = self._call("caddy", "g" * 64)
        assert result["isError"]
        assert "DENY" in result["content"][0]["text"]

    def test_deny_empty_hash(self):
        """TC-06: context_hash 빈 문자열"""
        with patch("builtins.open", mock_open(read_data=MOCK_POINTER)):
            result = bridge._handle_sync({"actor_id": "caddy", "context_hash": ""})
        assert result["isError"]
        assert "DENY" in result["content"][0]["text"]

    def test_fail_closed_pointer_not_found(self):
        """TC-07: POINTER.json 미존재 (Fail-Closed)"""
        with patch("builtins.open", side_effect=FileNotFoundError("not found")):
            result = bridge._handle_sync({"actor_id": "caddy", "context_hash": CANONICAL_HASH})
        assert result["isError"]
        assert "FAIL_CLOSED" in result["content"][0]["text"]

    def test_all_actors_allowed(self):
        """TC-08: caddy/domi/jeni 모두 허용"""
        for actor in ("caddy", "domi", "jeni"):
            result = self._call(actor, CANONICAL_HASH)
            assert not result["isError"], f"actor '{actor}' should be allowed"

    def test_sync_in_allowed_tools(self):
        """TC-09: sync가 ALLOWED_TOOLS에 포함됨"""
        assert "sync" in bridge.ALLOWED_TOOLS

    def test_sync_tools_constant(self):
        """TC-10: SYNC_TOOLS 상수 확인"""
        assert "sync" in bridge.SYNC_TOOLS

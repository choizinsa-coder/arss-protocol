"""
PT-S61-001 — Test Suite
Tests: mutation_gate / field_contract / auto_loader._apply / activation_runner
EAG-2 APPROVED by 비오(Joshua)
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from typing import Optional


# ── mutation_gate ──────────────────────────────────────────────────────────────

from tools.auto_loader.mutation_gate import evaluate, MutationRequest, MutationResult

class TestMutationGate:

    def _req(self, target="auto_loader.load_result", operation="load_result_only", payload=None):
        return MutationRequest(target=target, operation=operation, payload=payload or {})

    # 허용 케이스
    def test_allowed_target_and_operation(self):
        result = evaluate(self._req())
        assert result.allowed is True
        assert result.reason == "allowed"

    def test_all_allowed_targets(self):
        targets = [
            "session_context.read",
            "auto_loader.load_result",
            "validation_runner.execute",
            "mutation_gate.evaluate",
        ]
        for t in targets:
            result = evaluate(self._req(target=t))
            assert result.allowed is True, f"target={t} should be allowed"

    # 차단 케이스 — forbidden operation
    @pytest.mark.parametrize("op", ["write", "mutate", "overwrite", "bypass_gate", "direct_mutation"])
    def test_forbidden_operations(self, op):
        result = evaluate(self._req(operation=op))
        assert result.allowed is False
        assert result.reason == "forbidden operation"

    # 차단 케이스 — target not allowed
    def test_target_not_allowed(self):
        result = evaluate(self._req(target="unknown.target"))
        assert result.allowed is False
        assert result.reason == "target not allowed"

    # 차단 케이스 — undefined target
    def test_undefined_target_empty_string(self):
        result = evaluate(self._req(target=""))
        assert result.allowed is False
        assert result.reason == "undefined target or operation"

    # 차단 케이스 — undefined operation
    def test_undefined_operation_empty_string(self):
        result = evaluate(self._req(operation=""))
        assert result.allowed is False
        assert result.reason == "undefined target or operation"

    # timeout
    def test_timeout_returns_deny(self):
        import tools.auto_loader.mutation_gate as mg
        original_run = None

        def slow_run():
            time.sleep(1)

        req = self._req()
        with patch("threading.Thread") as mock_thread_cls:
            mock_thread = MagicMock()
            mock_thread.is_alive.return_value = True
            mock_thread_cls.return_value = mock_thread
            result = evaluate(req)
        assert result.allowed is False
        assert result.reason == "timeout occurred"
        assert result.latency_ms == 50

    # latency_ms 타입
    def test_latency_ms_is_int(self):
        result = evaluate(self._req())
        assert isinstance(result.latency_ms, int)


# ── field_contract ─────────────────────────────────────────────────────────────

from tools.auto_loader.field_contract import (
    SourceType, LoadScope, VerificationMethod, Verdict,
    LoadTarget, SourceAdapterContract,
)

class TestFieldContract:

    def test_source_type_values(self):
        assert SourceType.VPS_FILE == "VPS_FILE"
        assert SourceType.GDRIVE_FILE == "GDRIVE_FILE"
        assert SourceType.GITHUB_RAW == "GITHUB_RAW"
        assert SourceType.HTTP_ENDPOINT == "HTTP_ENDPOINT"

    def test_load_scope_values(self):
        assert LoadScope.FULL == "FULL"
        assert LoadScope.PARTIAL == "PARTIAL"
        assert LoadScope.METADATA_ONLY == "METADATA_ONLY"

    def test_verification_method_values(self):
        assert VerificationMethod.HASH_SHA256 == "HASH_SHA256"
        assert VerificationMethod.HTTP_STATUS == "HTTP_STATUS"
        assert VerificationMethod.FILE_EXISTENCE == "FILE_EXISTENCE"

    def test_verdict_9_kinds(self):
        expected = {
            "PASS", "FAIL", "DENY", "TIMEOUT", "EXCEPTION",
            "UNDEFINED_TARGET", "FORBIDDEN_OPERATION", "SOURCE_INVALID", "PARTIAL",
        }
        actual = {v.value for v in Verdict}
        assert actual == expected

    def test_load_target_frozen(self):
        lt = LoadTarget(
            id="test",
            source_type=SourceType.VPS_FILE,
            source_ref="/opt/test.json",
            load_scope=LoadScope.FULL,
            required=True,
            fail_closed=True,
        )
        with pytest.raises((AttributeError, TypeError)):
            lt.id = "modified"

    def test_source_adapter_contract_frozen(self):
        sac = SourceAdapterContract(
            adapter_id="test_adapter",
            source_type=SourceType.VPS_FILE,
            read_only=True,
            verification_method=VerificationMethod.HASH_SHA256,
        )
        with pytest.raises((AttributeError, TypeError)):
            sac.read_only = False


# ── auto_loader._apply ─────────────────────────────────────────────────────────

from tools.auto_loader.auto_loader import AutoLoader
from tools.auto_loader.load_result import make_load_result
import tools.auto_loader.mutation_gate as mg

class TestAutoLoaderApply:

    def _make_result(self, apply_allowed=True, failure_reason=None):
        r = make_load_result(
            target_id="test",
            source_resolved=True,
            loaded=True,
            content_hash="abc123",
            failure_reason=failure_reason,
        )
        object.__setattr__(r, "apply_allowed", apply_allowed)
        return r

    def test_apply_blocked_when_mutation_denied(self):
        loader = AutoLoader()
        result = self._make_result(apply_allowed=True)
        deny_result = MutationResult(allowed=False, reason="forbidden operation", latency_ms=0)
        with patch.object(mg, "evaluate", return_value=deny_result):
            # _apply 호출 — 예외 없이 반환되어야 함
            loader._apply(result)

    def test_apply_blocked_when_apply_allowed_false(self):
        loader = AutoLoader()
        result = self._make_result(apply_allowed=False)
        allow_result = MutationResult(allowed=True, reason="allowed", latency_ms=0)
        with patch.object(mg, "evaluate", return_value=allow_result):
            loader._apply(result)

    def test_apply_passes_when_both_allowed(self):
        loader = AutoLoader()
        result = self._make_result(apply_allowed=True)
        allow_result = MutationResult(allowed=True, reason="allowed", latency_ms=0)
        with patch.object(mg, "evaluate", return_value=allow_result):
            loader._apply(result)  # 예외 없이 통과


# ── activation_runner ──────────────────────────────────────────────────────────

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from tools.auto_loader.activation_runner import ActivationRunner, ActivationRuntimeConfig
from tools.auto_loader.field_contract import LoadTarget, SourceType, LoadScope

KST = timezone(timedelta(hours=9))

def _make_token(
    approval_id="APR-TEST-001",
    approved_by="비오(Joshua)",
    scope="PT-S61-001",
    target_task_id="PT-S61-001",
    session_count=62,
    expires_offset_hours=1,
):
    now = datetime.now(tz=KST)
    expires_at = now + timedelta(hours=expires_offset_hours)
    return {
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approved_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "scope": scope,
        "target_task_id": target_task_id,
        "session_count": session_count,
    }

def _write_token(token: dict) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(token, f)
    f.close()
    return f.name

def _make_config(
    task_id="PT-S61-001",
    output_mode="load_result_only",
    apply_to_session_context=False,
):
    return ActivationRuntimeConfig(
        task_id=task_id,
        output_mode=output_mode,
        apply_to_session_context=apply_to_session_context,
    )

def _make_load_target(source_ref="/opt/arss/engine/arss-protocol/SESSION_CONTEXT.json"):
    return LoadTarget(
        id="session_context",
        source_type=SourceType.VPS_FILE,
        source_ref=source_ref,
        load_scope=LoadScope.FULL,
        required=True,
        fail_closed=True,
    )

class TestActivationRunner:

    # token 없음
    def test_missing_token_path(self):
        runner = ActivationRunner()
        result = runner.run(
            token_path="/nonexistent/token.json",
            runtime_config=_make_config(),
            load_target=_make_load_target(),
        )
        assert result.loaded is False
        assert "approval_token" in result.failure_reason

    # token 만료
    def test_expired_token(self):
        token = _make_token(expires_offset_hours=-1)
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "expired" in result.failure_reason
        finally:
            os.unlink(path)

    # scope 불일치
    def test_token_scope_mismatch(self):
        token = _make_token(scope="PT-OTHER-999")
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "scope" in result.failure_reason
        finally:
            os.unlink(path)

    # target_task_id 불일치
    def test_token_target_task_id_mismatch(self):
        token = _make_token(target_task_id="PT-OTHER-999")
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "target_task_id" in result.failure_reason
        finally:
            os.unlink(path)

    # config task_id 불일치
    def test_config_task_id_mismatch(self):
        token = _make_token()
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(task_id="PT-OTHER-999"),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "task_id" in result.failure_reason
        finally:
            os.unlink(path)

    # output_mode 불일치
    def test_config_output_mode_mismatch(self):
        token = _make_token()
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(output_mode="full_apply"),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "output_mode" in result.failure_reason
        finally:
            os.unlink(path)

    # apply_to_session_context=True 금지
    def test_apply_to_session_context_forbidden(self):
        token = _make_token()
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(apply_to_session_context=True),
                load_target=_make_load_target(),
            )
            assert result.loaded is False
            assert "apply_to_session_context" in result.failure_reason
        finally:
            os.unlink(path)

    # source_type != VPS_FILE
    def test_source_type_not_vps_file(self):
        token = _make_token()
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            lt = LoadTarget(
                id="test",
                source_type=SourceType.GDRIVE_FILE,
                source_ref="/opt/test.json",
                load_scope=LoadScope.FULL,
                required=True,
                fail_closed=True,
            )
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(),
                load_target=lt,
            )
            assert result.loaded is False
            assert "VPS_FILE" in result.failure_reason
        finally:
            os.unlink(path)

    # source_ref 상대경로 금지
    def test_source_ref_relative_path_forbidden(self):
        token = _make_token()
        path = _write_token(token)
        try:
            runner = ActivationRunner()
            result = runner.run(
                token_path=path,
                runtime_config=_make_config(),
                load_target=_make_load_target(source_ref="relative/path.json"),
            )
            assert result.loaded is False
            assert "absolute" in result.failure_reason
        finally:
            os.unlink(path)

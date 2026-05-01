"""
PT-S61-001 — AUTO-LOADER v1.1 Production Activation Runner
EAG-2 APPROVED by 비오(Joshua)
Design: PT-S61-001 + Patch v1.1 LOCKED
"""

import json
import os
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from typing import Optional

from tools.auto_loader.auto_loader import AutoLoader
from tools.auto_loader.field_contract import LoadTarget, SourceType, LoadScope, VerificationMethod
from tools.auto_loader.load_result import LoadResult, make_load_result

KST = timezone(timedelta(hours=9))


@dataclass
class ActivationRuntimeConfig:
    task_id: str
    output_mode: str
    apply_to_session_context: bool
    # shadow_mode 플래그 — 도미 설계 / 비오(Joshua) EAG 승인 S65
    shadow_mode: bool = False
    index_path: Optional[str] = None
    delta_root: Optional[str] = None


def _fail(reason: str) -> LoadResult:
    return make_load_result(
        target_id="",
        source_resolved=False,
        loaded=False,
        content_hash=None,
        failure_reason=reason,
    )


class ActivationRunner:

    def run(
        self,
        token_path: str,
        runtime_config: ActivationRuntimeConfig,
        load_target: LoadTarget,
    ) -> LoadResult:

        # STEP 0: approval_token 검증
        token_result = self._validate_token(token_path)
        if token_result is not None:
            return token_result

        # STEP 1: activation_runtime_config 검증
        config_result = self._validate_config(runtime_config)
        if config_result is not None:
            return config_result

        # STEP 2: source_type / source_ref 사전 검증
        if load_target.source_type != SourceType.VPS_FILE:
            return _fail("source_type != VPS_FILE")
        if not os.path.isabs(load_target.source_ref):
            return _fail("source_ref is not absolute path")

        # STEP 3: AUTO-LOADER 실행 (내부 order: resolve→load→hash→validate→apply)
        # shadow_mode/index_path/delta_root 명시 주입 — 도미 설계 S65
        loader = AutoLoader(
            index_path=runtime_config.index_path,
            delta_root=runtime_config.delta_root,
            shadow_mode=runtime_config.shadow_mode,
        )
        result = loader.run(load_target)

        # STEP 4: SESSION_CONTEXT 변경 금지 강제
        # output_mode=load_result_only → apply 결과만 반환, SSOT 무변경
        return result

    def _validate_token(self, token_path: str) -> Optional[LoadResult]:
        if not token_path or not os.path.isfile(token_path):
            return _fail("approval_token missing or unreadable")

        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = json.load(f)
        except Exception:
            return _fail("approval_token unreadable")

        required_fields = [
            "approval_id", "approved_by", "approved_at",
            "expires_at", "scope", "target_task_id",
        ]
        for field in required_fields:
            if field not in token:
                return _fail(f"approval_token missing field: {field}")

        if "session_id" not in token and "session_count" not in token:
            return _fail("approval_token missing session_id or session_count")

        # 만료 검증
        try:
            expires_at = datetime.fromisoformat(token["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=KST)
            now = datetime.now(tz=KST)
            if now > expires_at:
                return _fail("approval_token expired")
        except Exception:
            return _fail("approval_token expires_at parse failure")

        # scope / target_task_id 검증
        if "PT-S61-001" not in str(token.get("scope", "")):
            return _fail("approval_token scope does not include PT-S61-001")
        if token.get("target_task_id") != "PT-S61-001":
            return _fail("approval_token target_task_id mismatch")

        return None

    def _validate_config(self, config: ActivationRuntimeConfig) -> Optional[LoadResult]:
        if config.task_id != "PT-S61-001":
            return _fail("activation_runtime_config task_id mismatch")
        if config.output_mode != "load_result_only":
            return _fail("output_mode != load_result_only")
        if config.apply_to_session_context is True:
            return _fail("apply_to_session_context=true is forbidden")
        # shadow_mode=True 시 index_path / delta_root 필수 — 도미 설계 S65
        if config.shadow_mode is True:
            if not config.index_path:
                return _fail("shadow_mode=True이나 index_path 미설정")
            if not config.delta_root:
                return _fail("shadow_mode=True이나 delta_root 미설정")
        return None

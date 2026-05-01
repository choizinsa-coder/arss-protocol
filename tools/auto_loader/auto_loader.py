from typing import Dict, Optional, Union

from . import mutation_gate
from .field_contract import LoadTarget, SourceType
from .hash_engine import sha256_full_raw_content
from .index_validator import validate_index
from .load_result import LoadResult, make_load_result
from .mutation_gate import MutationRequest
from .source_adapter import SourceAdapter, default_adapters, resolve_adapter, valid_source_ref


class AutoLoader:
    def __init__(
        self,
        adapters: Optional[Dict[SourceType, SourceAdapter]] = None,
        index_path: Optional[str] = None,
        delta_root: Optional[str] = None,
        shadow_mode: bool = False,
    ):
        self.adapters = adapters if adapters is not None else default_adapters()
        self._index_path = index_path
        self._delta_root = delta_root
        self._shadow_mode = shadow_mode

    def run(self, load_target: Union[LoadTarget, None]) -> LoadResult:
        # ── INDEX_INTEGRITY_SHADOW_CHECK ─────────────────────────────────
        # 도미 설계 / 비오(Joshua) EAG 승인 — S65
        # BOOT 직후 DOMAIN_INDEX 무결성 검증 (READ-ONLY / FAIL-CLOSED)
        #
        # shadow_mode=True  + 경로 있음  → validate_index() 실행
        # shadow_mode=True  + 경로 없음  → FAIL (즉시 반환)
        # shadow_mode=False              → SKIP (기존 동작 유지)
        if self._shadow_mode:
            if not self._index_path or not self._delta_root:
                return make_load_result(
                    "",
                    False,
                    False,
                    None,
                    "INDEX_INTEGRITY_SHADOW_CHECK FAIL: "
                    "shadow_mode=True이나 index_path/delta_root 미설정",
                )
            _iv_result = validate_index(self._index_path, self._delta_root)
            if _iv_result.get("result") == "FAIL":
                return make_load_result(
                    "",
                    False,
                    False,
                    None,
                    f"INDEX_INTEGRITY_SHADOW_CHECK FAIL: {_iv_result.get('reason', 'unknown')}",
                )
        else:
            print(
                "[INDEX_INTEGRITY_SHADOW_CHECK] SKIP — shadow_mode=False"
            )
        # ─────────────────────────────────────────────────────────────────

        target_id, source_resolved, adapter, failure_reason = self._resolve(load_target)
        loaded = False
        content = b""
        content_hash = None

        if failure_reason is None and load_target is not None and adapter is not None:
            loaded, content, failure_reason = self._load(adapter, load_target.source_ref)

        if failure_reason is None and loaded:
            content_hash = self._hash(content)

        failure_reason = self._validate(load_target, source_resolved, loaded, content_hash, failure_reason)
        result = make_load_result(target_id, source_resolved, loaded, content_hash, failure_reason)
        self._apply(result)
        return result

    def _resolve(self, load_target: Optional[LoadTarget]):
        if load_target is None:
            return "", False, None, "LOAD_TARGET missing"
        if not isinstance(load_target, LoadTarget):
            return "", False, None, "LOAD_TARGET missing"
        if not valid_source_ref(load_target.source_type, load_target.source_ref):
            return load_target.id, False, None, "source_ref invalid format"
        adapter = resolve_adapter(self.adapters, load_target.source_type)
        if adapter is None:
            return load_target.id, False, None, "adapter missing or mismatched"
        return load_target.id, True, adapter, None

    def _load(self, adapter: SourceAdapter, source_ref: str):
        read_result = adapter.read(source_ref)
        if not read_result.loaded:
            return False, b"", read_result.failure_reason or "resolution failure"
        return True, read_result.content, None

    def _hash(self, content: bytes) -> str:
        return sha256_full_raw_content(content)

    def _validate(
        self,
        load_target: Optional[LoadTarget],
        source_resolved: bool,
        loaded: bool,
        content_hash: Optional[str],
        failure_reason: Optional[str],
    ) -> Optional[str]:
        if failure_reason:
            if not isinstance(load_target, LoadTarget):
                return failure_reason
            if failure_reason in {
                "LOAD_TARGET missing",
                "source_ref invalid format",
                "adapter missing or mismatched",
            }:
                return failure_reason
            if load_target.required is True and loaded is False:
                return f"{failure_reason}; required=True AND loaded=False"
            return failure_reason
        if load_target is None:
            return "LOAD_TARGET missing"
        if not source_resolved:
            return "resolution failure"
        if load_target.required is True and loaded is False:
            return "required=True AND loaded=False"
        if loaded is True and not content_hash:
            return "loaded=True AND hash missing"
        return None

    def _apply(self, result: LoadResult) -> None:
        mutation_result = mutation_gate.evaluate(
            MutationRequest(
                target="auto_loader.load_result",
                operation="load_result_only",
                payload={},
            )
        )
        if mutation_result.allowed is False:
            return
        if result.apply_allowed is not True:
            return


"""
mcp_read_server.py
PT-S134-VPS-OBS-001 Phase 1 READ ONLY OBSERVABILITY
Version: 1.1.0  (S214: EVIDENCE_CODE_ROOT 추가 — EAG-S214-OBS-001)

원칙:
- READ CHANNEL ONLY
- deny-by-default
- whitelist path sealing
- actor identity sealing (actor_id + connector identity + HMAC)
- purpose_category audit logging
- READ capability must not become operational steering capability
"""

import logging as _logging
import os
import re
import json
import hmac
import hashlib
import time
import uuid
from pathlib import Path
from typing import Optional

# ── Semantic Root 정의 ──────────────────────────────────────────────
CODE_ROOT           = Path("/opt/arss/engine/arss-protocol")
GOVERNANCE_ROOT     = Path("/opt/arss/engine/arss-protocol/tools/governance")
EVIDENCE_ROOT       = Path("/opt/arss/engine/arss-protocol/tests")
EVIDENCE_CODE_ROOT  = Path("/opt/arss/engine/arss-protocol/tools/evidence")  # S214 신규: jeni 독립 관측용
ARSS_HUB_ROOT       = Path("/opt/arss/engine/arss-protocol/ARSS_HUB")
LOG_ROOT            = Path("/opt/arss/engine/arss-protocol/tools/mcp")
METADATA_ROOT       = Path("/opt/arss/engine/arss-protocol")
SESSION_JOURNAL_ROOT = Path("/opt/arss/engine/arss-protocol/session_journal")  # S217 신규: Phase 1 Shared Memory

# ── 허용 Purpose Category ──────────────────────────────────────────
ALLOWED_PURPOSES = {
    "OBSERVATION",
    "EVIDENCE_INSPECTION",
    "AUDIT_INSPECTION",
    "CONSISTENCY_CHECK",
    "STALE_DETECTION",
}

FORBIDDEN_PURPOSES = {
    "EXECUTION_COORDINATION",
    "DEPLOYMENT_STEERING",
    "RUNTIME_CONTROL",
    "MUTATION_PREPARATION",
    "APPROVAL_SUBSTITUTION",
}

# ── 금지 경로 패턴 ─────────────────────────────────────────────────
FORBIDDEN_PATH_PATTERNS = [
    r"\.env",
    r"\.key$",
    r"\.pem$",
    r"\.cert$",
    r"token",
    r"secret",
    r"credential",
    r"oauth",
    r"private",
    r"id_rsa",
    r"id_ed25519",
    r"\.ssh",
    r"approval",
]

# ── 허용 서비스 목록 (S199 EAG-1: 3종 추가) ───────────────────────
ALLOWED_SERVICES = {
    "aiba-mcp-bridge",
    "nginx",
    "aiba-jeni-runtime",
    "aiba-domi-runtime",
    "aiba-exec-runtime",
}

# ── 에이전트별 허용 Semantic Root ──────────────────────────────────
AGENT_ROOT_ALLOWLIST = {
    "domi":  [CODE_ROOT, GOVERNANCE_ROOT, METADATA_ROOT, EVIDENCE_ROOT, SESSION_JOURNAL_ROOT],
    "jeni":  [EVIDENCE_ROOT, LOG_ROOT, METADATA_ROOT, GOVERNANCE_ROOT, ARSS_HUB_ROOT, EVIDENCE_CODE_ROOT, SESSION_JOURNAL_ROOT],
    "caddy": [CODE_ROOT, EVIDENCE_ROOT, LOG_ROOT, METADATA_ROOT, SESSION_JOURNAL_ROOT],
}

# ── 허용 Connector Identity ────────────────────────────────────────
ALLOWED_CONNECTOR_IDENTITIES = {
    "claude.ai-arss-protocol",
}

# ── Nonce Store (in-memory, TTL 15분) ─────────────────────────────
_nonce_store: dict[str, float] = {}
NONCE_TTL = 900  # 15분


def _purge_expired_nonces():
    now = time.time()
    expired = [k for k, v in _nonce_store.items() if now - v > NONCE_TTL]
    for k in expired:
        del _nonce_store[k]


# ── Deny Result ────────────────────────────────────────────────────
class DenyResult(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# ── 경로 안전성 검증 ───────────────────────────────────────────────
def _validate_path(path: Path, allowed_roots: list[Path], max_depth: int) -> Path:
    try:
        resolved = path.resolve()
    except Exception:
        raise DenyResult("PATH_RESOLVE_FAILED")

    # 허용 루트 내부 확인
    in_allowed = any(
        str(resolved).startswith(str(root))
        for root in allowed_roots
    )
    if not in_allowed:
        raise DenyResult("PATH_NOT_IN_WHITELIST")

    # depth 확인 (CODE_ROOT 기준 상대 depth)
    for root in allowed_roots:
        try:
            rel = resolved.relative_to(root)
            if len(rel.parts) > max_depth:
                raise DenyResult("PATH_DEPTH_EXCEEDED")
            break
        except ValueError as _rule6_e:
            _logging.debug("RULE6 mcp_read_server: %s", _rule6_e)
            continue

    # 금지 패턴 확인
    path_str = str(resolved).lower()
    for pattern in FORBIDDEN_PATH_PATTERNS:
        if re.search(pattern, path_str):
            raise DenyResult(f"FORBIDDEN_PATH_PATTERN: {pattern}")

    return resolved


# ── Identity 검증 ──────────────────────────────────────────────────
def _validate_identity(
    actor_id: str,
    connector_identity: str,
    hmac_value: str,
    nonce: str,
    timestamp: float,
    payload: str,
    hmac_secret: str,
) -> None:

    # actor_id 확인
    if actor_id not in AGENT_ROOT_ALLOWLIST:
        raise DenyResult("UNKNOWN_ACTOR")

    # connector identity 확인
    if connector_identity not in ALLOWED_CONNECTOR_IDENTITIES:
        raise DenyResult("UNKNOWN_CLIENT")

    # timestamp freshness (±5분)
    now = time.time()
    if abs(now - timestamp) > 300:
        raise DenyResult("STALE_TIMESTAMP")

    # nonce 재사용 확인
    _purge_expired_nonces()
    if nonce in _nonce_store:
        raise DenyResult("NONCE_REPLAY")
    _nonce_store[nonce] = now

    # HMAC 검증
    expected = hmac.new(
        hmac_secret.encode(),
        f"{actor_id}:{connector_identity}:{nonce}:{timestamp}:{payload}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, hmac_value):
        raise DenyResult("AUTH_MISMATCH")


# ── Purpose 검증 ───────────────────────────────────────────────────
def _validate_purpose(purpose: str) -> None:
    if purpose in FORBIDDEN_PURPOSES:
        raise DenyResult(f"FORBIDDEN_PURPOSE: {purpose}")
    if purpose not in ALLOWED_PURPOSES:
        raise DenyResult("UNKNOWN_PURPOSE")


# ── Audit 기록 ────────────────────────────────────────────────────
def _audit(
    actor_id: str,
    connector_identity: str,
    tool: str,
    path: Optional[str],
    purpose: str,
    result: str,
    shard: str = "read",
    request_id: Optional[str] = None,
):
    try:
        from mcp_audit_broker import write_audit
        decision = "ALLOW" if result == "ALLOW" else "DENY"
        write_audit(
            agent_id=actor_id,
            requested_shard=shard,
            returned_scope=path or tool,
            decision=decision,
            reason=tool + ":" + purpose + ":" + result,
            source_hash=request_id or str(uuid.uuid4()),
            load_state="ACTIVE",
            retrieval_class="CLASS-B" if decision == "ALLOW" else "CLASS-D",
        )
    except Exception:
        # audit 실패 시 FAIL-CLOSED
        raise DenyResult("AUDIT_WRITE_FAILED")


# ── READ 도구 구현 ─────────────────────────────────────────────────

class ReadOnlyServer:
    """
    READ ONLY MCP 도구 서버.
    모든 도구는 identity + purpose + path whitelist 검증 후 실행.
    """

    def _base_check(self, actor_id, connector_identity, hmac_value,
                    nonce, timestamp, payload, hmac_secret, purpose):
        _validate_identity(
            actor_id, connector_identity, hmac_value,
            nonce, timestamp, payload, hmac_secret,
        )
        _validate_purpose(purpose)
        return AGENT_ROOT_ALLOWLIST[actor_id]

    def read_file(
        self,
        path: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """단일 파일 읽기. 디렉토리/와일드카드 금지. depth=1."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, path, hmac_secret, purpose,
            )
            target = _validate_path(Path(path), allowed_roots, max_depth=10)

            if not target.is_file():
                raise DenyResult("NOT_A_FILE")

            content = target.read_text(encoding="utf-8")
            _audit(actor_id, connector_identity, "read_file",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "content": content}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "read_file",
                   path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def list_dir(
        self,
        path: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """디렉토리 목록. recursive 금지. depth=1."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, path, hmac_secret, purpose,
            )
            target = _validate_path(Path(path), allowed_roots, max_depth=10)

            if not target.is_dir():
                raise DenyResult("NOT_A_DIRECTORY")

            entries = [e.name for e in target.iterdir()]
            _audit(actor_id, connector_identity, "list_dir",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "entries": entries}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "list_dir",
                   path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def grep_scoped(
        self,
        path: str,
        pattern: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
        max_results: int = 50,
    ) -> dict:
        """scope 내 텍스트 검색. 전체 루트 grep 금지. depth=2."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, f"{path}:{pattern}", hmac_secret, purpose,
            )
            # grep_scoped는 CODE_ROOT, GOVERNANCE_ROOT, METADATA_ROOT만
            grep_allowed = [
                r for r in allowed_roots
                if r in [CODE_ROOT, GOVERNANCE_ROOT, METADATA_ROOT]
            ]
            target = _validate_path(Path(path), grep_allowed, max_depth=2)

            results = []
            compiled = re.compile(pattern)
            for f in target.rglob("*.py") if target.is_dir() else [target]:
                try:
                    for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                        if compiled.search(line):
                            results.append({"file": str(f), "line": i, "text": line})
                            if len(results) >= max_results:
                                break
                except Exception as _rule6_e:
                    _logging.debug("RULE6 mcp_read_server: %s", _rule6_e)
                    continue
                if len(results) >= max_results:
                    break

            _audit(actor_id, connector_identity, "grep_scoped",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "matches": results}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "grep_scoped",
                   path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def read_log(
        self,
        path: str,
        tail_lines: int,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """로그 파일 tail 읽기. raw secret/env log 제외."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, path, hmac_secret, purpose,
            )
            log_allowed = [r for r in allowed_roots if r in [LOG_ROOT, EVIDENCE_ROOT]]
            target = _validate_path(Path(path), log_allowed, max_depth=10)

            if not target.is_file():
                raise DenyResult("NOT_A_FILE")

            lines = target.read_text(encoding="utf-8").splitlines()
            tail = lines[-min(tail_lines, 200):]  # 최대 200줄
            _audit(actor_id, connector_identity, "read_log",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "lines": tail}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "read_log",
                   path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def check_service_state(
        self,
        service_name: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """허용된 서비스 상태 확인. restart/stop/start 금지."""
        rid = str(uuid.uuid4())
        try:
            self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, service_name, hmac_secret, purpose,
            )
            if service_name not in ALLOWED_SERVICES:
                raise DenyResult("SERVICE_NOT_IN_ALLOWLIST")

            result = os.popen(
                f"systemctl is-active {service_name} 2>/dev/null"
            ).read().strip()
            _audit(actor_id, connector_identity, "check_service_state",
                   service_name, purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "service": service_name, "state": result}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "check_service_state",
                   service_name, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def read_pytest_result(
        self,
        artifact_path: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """pytest result artifact 읽기. pytest 실행 아님."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, artifact_path, hmac_secret, purpose,
            )
            ev_allowed = [r for r in allowed_roots if r == EVIDENCE_ROOT]
            target = _validate_path(Path(artifact_path), ev_allowed, max_depth=10)

            if not target.is_file():
                raise DenyResult("NOT_A_FILE")

            content = target.read_text(encoding="utf-8")
            _audit(actor_id, connector_identity, "read_pytest_result",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "content": content}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "read_pytest_result",
                   artifact_path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def read_audit_event(
        self,
        log_path: str,
        event_range: int,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """audit event 읽기. bulk dump 금지 (최대 100건)."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, log_path, hmac_secret, purpose,
            )
            audit_allowed = [r for r in allowed_roots if r in [LOG_ROOT, EVIDENCE_ROOT]]
            target = _validate_path(Path(log_path), audit_allowed, max_depth=10)

            if not target.is_file():
                raise DenyResult("NOT_A_FILE")

            count = min(event_range, 100)  # bulk dump 금지
            lines = target.read_text(encoding="utf-8").splitlines()
            events = lines[-count:]
            _audit(actor_id, connector_identity, "read_audit_event",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "events": events}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "read_audit_event",
                   log_path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def read_metadata(
        self,
        path: str,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """SESSION_CONTEXT / SESSION_BOOT / sync metadata 읽기."""
        rid = str(uuid.uuid4())
        try:
            allowed_roots = self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, path, hmac_secret, purpose,
            )
            meta_allowed = [r for r in allowed_roots if r == METADATA_ROOT]
            target = _validate_path(Path(path), meta_allowed, max_depth=2)

            if not target.is_file():
                raise DenyResult("NOT_A_FILE")

            # METADATA_ROOT는 SESSION_CONTEXT*, SESSION_BOOT*만 허용
            if not any(target.name.startswith(p)
                       for p in ["SESSION_CONTEXT", "SESSION_BOOT", "sync_"]):
                raise DenyResult("METADATA_FILE_NOT_ALLOWED")

            content = target.read_text(encoding="utf-8")
            _audit(actor_id, connector_identity, "read_metadata",
                   str(target), purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "path": str(target), "content": content}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "read_metadata",
                   path, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

    def get_runtime_snapshot(
        self,
        actor_id: str,
        connector_identity: str,
        hmac_value: str,
        nonce: str,
        timestamp: float,
        hmac_secret: str,
        purpose: str,
    ) -> dict:
        """사전 정의된 read-only snapshot projection. 생성/갱신 금지."""
        rid = str(uuid.uuid4())
        try:
            self._base_check(
                actor_id, connector_identity, hmac_value,
                nonce, timestamp, "runtime_snapshot", hmac_secret, purpose,
            )
            snapshot = {
                "snapshot_type": "READ_ONLY_PROJECTION",
                "generated_at": time.time(),
                "services": {},
                "metadata_files": [],
            }
            for svc in ALLOWED_SERVICES:
                state = os.popen(
                    f"systemctl is-active {svc} 2>/dev/null"
                ).read().strip()
                snapshot["services"][svc] = state

            for f in METADATA_ROOT.glob("SESSION_CONTEXT*.json"):
                snapshot["metadata_files"].append(f.name)

            _audit(actor_id, connector_identity, "get_runtime_snapshot",
                   None, purpose, "ALLOW", request_id=rid)
            return {"status": "ALLOW", "snapshot": snapshot}

        except DenyResult as e:
            _audit(actor_id, connector_identity, "get_runtime_snapshot",
                   None, purpose, f"DENY:{e.reason}", request_id=rid)
            return {"status": "DENY", "reason": e.reason}

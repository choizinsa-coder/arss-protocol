"""
mcp_write_gatekeeper.py — MCP Write Plane Gatekeeper v1.0.0
PT-S136-MCP-WRITE-GATEKEEPER

설계 기준: MCP Restricted Write Plane v0.4 (도미)
Fail-Closed: FC-T1 ~ FC-T4 전 구간 적용
Gatekeeper 역할: Verifier 전담 (Issuer 금지)
캐디는 토큰을 생성할 수 없음 — Gatekeeper 내부 전담
"""

import hashlib
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mcp_write_config import (
    APPROVALS_DIR,
    AUDIT_DIR,
    SNAPSHOTS_DIR,
    ALLOWED_SANDBOX_PATHS,
    FORBIDDEN_PATH_PREFIXES,
    ALLOWED_EXTENSIONS,
    FORBIDDEN_EXTENSIONS,
    TOKEN_TTL,
)
from mcp_approval_authority import compute_approval_hash

GATEKEEPER_VERSION = "1.0.0"


# ── Enums & Exceptions ────────────────────────────────────────────────

class WritePlaneState(Enum):
    NORMAL = "NORMAL"
    HOLD = "HOLD"
    LOCKED = "LOCKED"
    RECOVERY_MODE = "RECOVERY_MODE"


class FailClosedError(Exception):
    """FC-T1 ~ FC-T4 Fail-Closed 오류."""

    def __init__(self, tier: str, reason: str):
        self.tier = tier
        self.reason = reason
        super().__init__(f"FC-{tier}: {reason}")


# ── Gatekeeper ────────────────────────────────────────────────────────

class MCP_WriteGatekeeper:
    """
    MCP Write Plane Gatekeeper.
    모든 쓰기 요청의 단일 진입점.
    """

    def __init__(
        self,
        allowed_paths: list = None,
        forbidden_prefixes: list = None,
        approvals_dir: str = None,
        audit_dir: str = None,
        snapshots_dir: str = None,
    ):
        # 경로 (테스트 시 주입 가능)
        self._allowed_paths = allowed_paths or ALLOWED_SANDBOX_PATHS
        self._forbidden_prefixes = forbidden_prefixes or FORBIDDEN_PATH_PREFIXES
        self._approvals_dir = approvals_dir or APPROVALS_DIR
        self._audit_dir = audit_dir or AUDIT_DIR
        self._snapshots_dir = snapshots_dir or SNAPSHOTS_DIR

        # Write Plane 상태
        self._state = WritePlaneState.NORMAL
        self._state_lock = threading.Lock()

        # 토큰 저장소 (in-memory, single-use)
        self._token_store: dict = {}
        self._token_lock = threading.Lock()

        # 사용된 approval ID 집합
        self._used_approvals: set = set()

        # RECOVERY_MODE 1회 write 추적
        self._recovery_write_used = False

    # ── State ─────────────────────────────────────────────────────────

    def get_state(self) -> WritePlaneState:
        with self._state_lock:
            return self._state

    def _set_state(self, state: WritePlaneState) -> None:
        with self._state_lock:
            self._state = state

    def _assert_writable(self) -> None:
        state = self.get_state()
        if state == WritePlaneState.LOCKED:
            raise FailClosedError("T3", "Write Plane LOCKED — Beo mandatory review required")
        if state == WritePlaneState.HOLD:
            raise FailClosedError("T2", "Write Plane HOLD — audit failure, recovery required")
        if state == WritePlaneState.RECOVERY_MODE and self._recovery_write_used:
            raise FailClosedError(
                "T3", "RECOVERY_MODE: 1회 recovery write 소진. Beo recovery-close 승인 필요"
            )

    # ── Path & Extension Validation ───────────────────────────────────

    def _validate_path(self, target_path: str) -> bool:
        abs_path = os.path.abspath(target_path)
        # forbidden 우선 차단
        for forbidden in self._forbidden_prefixes:
            if abs_path.startswith(os.path.abspath(forbidden)):
                return False
        # allowed 확인
        for allowed in self._allowed_paths:
            if abs_path.startswith(os.path.abspath(allowed)):
                return True
        return False

    def _validate_extension(self, target_path: str) -> bool:
        _, ext = os.path.splitext(target_path)
        if ext in FORBIDDEN_EXTENSIONS:
            return False
        return ext in ALLOWED_EXTENSIONS

    # ── Approval Verification ─────────────────────────────────────────

    def _load_approval(self, approval_id: str) -> dict:
        """WRITE_APPROVAL_REGISTRY에서 approval artifact 로드."""
        approval_file = os.path.join(self._approvals_dir, f"{approval_id}.json")
        if not os.path.exists(approval_file):
            raise FailClosedError("T4", f"approval artifact not found: {approval_id}")
        with open(approval_file, encoding="utf-8") as f:
            return json.load(f)

    def _verify_approval(self, approval: dict, target_path: str, ext: str) -> None:
        """approval artifact 전항목 검증. 하나라도 실패 시 FC-T4."""
        # type 확인
        if approval.get("type") != "EAG_WRITE_APPROVAL":
            raise FailClosedError("T4", "approval type mismatch")

        # approved_by 확인
        if approval.get("approved_by") != "Beo":
            raise FailClosedError("T4", "approval not issued by Beo")

        # TTL 확인
        approved_at = datetime.fromisoformat(approval["approved_at"])
        elapsed = (datetime.now(timezone.utc) - approved_at).total_seconds()
        if elapsed > approval.get("ttl_seconds", TOKEN_TTL):
            raise FailClosedError("T4", f"approval expired (elapsed={elapsed:.0f}s)")

        # 재사용 확인
        approval_id = approval.get("approval_id", "")
        if approval_id in self._used_approvals:
            raise FailClosedError("T4", f"approval already used: {approval_id}")

        # scope 확인
        scope = approval.get("scope", {})
        if os.path.abspath(scope.get("target_path", "")) != os.path.abspath(target_path):
            raise FailClosedError("T4", "approval target_path mismatch")
        if scope.get("extension") != ext:
            raise FailClosedError("T4", "approval extension mismatch")
        if scope.get("operation") != "WRITE":
            raise FailClosedError("T4", "approval operation mismatch")

        # approval_hash 무결성
        stored_hash = approval.get("approval_hash")
        computed_hash = compute_approval_hash(approval)
        if computed_hash != stored_hash:
            raise FailClosedError("T4", "approval_hash integrity failure — possible tampering")

    # ── Token Management (Gatekeeper 내부 전담) ───────────────────────

    def _issue_token(self, approval_id: str, target_path: str, ext: str) -> str:
        """단일 사용 write token 발급. 캐디가 직접 호출 불가 — Gatekeeper 내부 전담."""
        token_id = f"WRITE-TOKEN-{uuid.uuid4().hex.upper()}"
        with self._token_lock:
            self._token_store[token_id] = {
                "token_id": token_id,
                "approval_id": approval_id,
                "target_path": os.path.abspath(target_path),
                "extension": ext,
                "issued_at": time.monotonic(),
                "ttl": TOKEN_TTL,
                "used": False,
            }
        return token_id

    def _consume_token(self, token_id: str, target_path: str) -> dict:
        """토큰 소비 (single-use 보장). 만료·재사용·경로불일치 시 FC-T4."""
        with self._token_lock:
            token = self._token_store.get(token_id)
            if not token:
                raise FailClosedError("T4", f"token not found: {token_id}")
            if token["used"]:
                raise FailClosedError("T4", f"token already used: {token_id}")
            elapsed = time.monotonic() - token["issued_at"]
            if elapsed > token["ttl"]:
                raise FailClosedError("T4", f"token expired: {token_id}")
            if os.path.abspath(token["target_path"]) != os.path.abspath(target_path):
                raise FailClosedError("T4", "token path mismatch — FC-T4 Scope Violation")
            token["used"] = True
            return token

    # ── Snapshot (WRITE_SNAPSHOT_REGISTRY) ────────────────────────────

    def _sha256_file(self, path: str) -> Optional[str]:
        """파일의 SHA-256 해시 계산. 파일 없으면 None."""
        if not os.path.exists(path):
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _seal_snapshot(self, target_path: str, approval_id: str, token_id: str) -> dict:
        """pre-write snapshot 생성 및 WRITE_SNAPSHOT_REGISTRY 저장."""
        hash_before = self._sha256_file(target_path)
        content_before: Optional[str] = None
        if os.path.exists(target_path):
            with open(target_path, "rb") as f:
                content_before = f.read().decode(errors="replace")

        snapshot_id = f"MCP-WRITE-SNAP-{uuid.uuid4().hex[:12].upper()}"
        snapshot = {
            "snapshot_id": snapshot_id,
            "target_path": os.path.abspath(target_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "hash_algorithm": "SHA-256",
            "hash_before": hash_before,
            "content_before": content_before,
            "approval_id": approval_id,
            "write_token_id": token_id,
        }

        os.makedirs(self._snapshots_dir, exist_ok=True)
        snap_file = os.path.join(self._snapshots_dir, f"{snapshot_id}.json")
        with open(snap_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        return snapshot

    # ── Audit (WRITE_AUDIT_REGISTRY, append-only) ─────────────────────

    def _append_audit(self, event: dict) -> None:
        """audit event append. 실패 시 FC-T2 (Write Plane HOLD)."""
        os.makedirs(self._audit_dir, exist_ok=True)
        audit_file = os.path.join(self._audit_dir, "mcp_write_audit.jsonl")
        event_str = json.dumps(event, ensure_ascii=False)
        try:
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(event_str + "\n")
        except Exception as exc:
            self._set_state(WritePlaneState.HOLD)
            raise FailClosedError("T2", f"audit append failed — Write Plane HOLD: {exc}")

    # ── Main Write Flow ───────────────────────────────────────────────

    def execute_write(
        self, approval_id: str, target_path: str, content: str
    ) -> dict:
        """
        MCP Write 실행 메인 플로우.
        VERIFY → PROOF → EXECUTE 순서 강제.
        하나라도 실패 시 Fail-Closed.
        """
        event_id = uuid.uuid4().hex
        _, ext = os.path.splitext(target_path)
        token_id: Optional[str] = None
        snapshot: Optional[dict] = None

        try:
            # 0. Write Plane 상태 확인
            self._assert_writable()

            # 1. 경로 whitelist 확인
            if not self._validate_path(target_path):
                raise FailClosedError("T4", f"path not in sandbox whitelist: {target_path}")

            # 2. 확장자 확인
            if not self._validate_extension(target_path):
                raise FailClosedError("T4", f"extension not allowed: {ext}")

            # 3. approval 로드 및 검증
            approval = self._load_approval(approval_id)
            self._verify_approval(approval, target_path, ext)

            # 4. token 발급 (Gatekeeper 내부 전담)
            token_id = self._issue_token(approval_id, target_path, ext)

            # 5. pre-write snapshot 봉인
            snapshot = self._seal_snapshot(target_path, approval_id, token_id)
            hash_before = snapshot["hash_before"]

            # 6. token 소비 (single-use 보장)
            self._consume_token(token_id, target_path)

            # 7. approval 사용 처리
            self._used_approvals.add(approval_id)

            # 8. 실제 write 실행
            try:
                parent_dir = os.path.dirname(target_path)
                if parent_dir:
                    os.makedirs(parent_dir, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as exc:
                raise FailClosedError("T1", f"write failed: {exc}")

            # 9. hash_after 검증
            hash_after = self._sha256_file(target_path)
            if hash_after is None:
                raise FailClosedError("T3", "hash_after is None — file missing after write")

            # RECOVERY_MODE 추적
            if self.get_state() == WritePlaneState.RECOVERY_MODE:
                self._recovery_write_used = True

            # 10. audit 봉인
            audit_event = {
                "event_id": event_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor": "caddy",
                "operation": "WRITE",
                "target_path": os.path.abspath(target_path),
                "extension": ext,
                "hash_before": hash_before,
                "hash_after": hash_after,
                "approval_ref": approval_id,
                "write_token_id": token_id,
                "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
                "result": "PASS",
                "failure_reason": None,
            }
            self._append_audit(audit_event)

            return {
                "result": "PASS",
                "event_id": event_id,
                "target_path": os.path.abspath(target_path),
                "hash_after": hash_after,
            }

        except FailClosedError as fc:
            self._handle_fail_closed(fc, event_id, approval_id, target_path, ext, token_id, snapshot)
            raise

    def _handle_fail_closed(
        self,
        fc: FailClosedError,
        event_id: str,
        approval_id: str,
        target_path: str,
        ext: str,
        token_id: Optional[str],
        snapshot: Optional[dict],
    ) -> None:
        """FC 발생 시 상태 전이 및 audit 기록."""
        if fc.tier == "T2":
            self._set_state(WritePlaneState.HOLD)
        elif fc.tier in ("T3", "T4"):
            self._set_state(WritePlaneState.LOCKED)

        audit_event = {
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "caddy",
            "operation": "WRITE",
            "target_path": os.path.abspath(target_path) if target_path else None,
            "extension": ext,
            "hash_before": None,
            "hash_after": None,
            "approval_ref": approval_id,
            "write_token_id": token_id,
            "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "result": "SECURITY_INCIDENT" if fc.tier == "T4" else "FAIL",
            "failure_reason": f"FC-{fc.tier}: {fc.reason}",
        }
        try:
            self._append_audit(audit_event)
        except FailClosedError:
            pass  # T2 HOLD은 이미 _append_audit 내부에서 처리됨

    # ── Recovery Controls (비오님 전용 호출) ──────────────────────────

    def beo_recovery_approve(self) -> None:
        """비오님 recovery 승인 후 호출. LOCKED/HOLD → RECOVERY_MODE."""
        with self._state_lock:
            if self._state not in (WritePlaneState.LOCKED, WritePlaneState.HOLD):
                raise ValueError(f"RECOVERY_MODE 진입 불가: 현재 상태={self._state.value}")
            self._state = WritePlaneState.RECOVERY_MODE
            self._recovery_write_used = False

    def beo_recovery_close(self) -> None:
        """비오님 recovery-close 승인 후 호출. RECOVERY_MODE → NORMAL."""
        with self._state_lock:
            if self._state != WritePlaneState.RECOVERY_MODE:
                raise ValueError(f"recovery-close 불가: 현재 상태={self._state.value}")
            self._state = WritePlaneState.NORMAL
            self._recovery_write_used = False


# ── Singleton ─────────────────────────────────────────────────────────

_gatekeeper_instance: Optional[MCP_WriteGatekeeper] = None
_gatekeeper_lock = threading.Lock()


def get_gatekeeper() -> MCP_WriteGatekeeper:
    global _gatekeeper_instance
    with _gatekeeper_lock:
        if _gatekeeper_instance is None:
            _gatekeeper_instance = MCP_WriteGatekeeper()
    return _gatekeeper_instance

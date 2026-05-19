"""
mcp_write_gatekeeper.py — MCP Write Plane Gatekeeper v1.2.0
PT-S136-MCP-WRITE-GATEKEEPER

v1.2.0 (S141): NORMAL → RECOVERY_MODE 조건부 전이 추가
  - beo_enter_recovery_mode(pending_count) 조건 확장
  - NORMAL + pending_count > 0 → RECOVERY_MODE (STALE_PENDING_RECEIPT_RECOVERY)
  - NORMAL + pending_count == 0 → DENY (FAIL_CLOSED)
  - 기존 LOCKED/HOLD → RECOVERY_MODE 경로 무변경
  - 도미 S141-002 설계 + 제니 TRUST_READY PASS(T-1~T-6) + EAG-2 비오(Joshua) 승인
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
    APPROVALS_DIR, AUDIT_DIR, SNAPSHOTS_DIR,
    RECEIPTS_DIR, BASELINES_DIR,
    ALLOWED_SANDBOX_PATHS, FORBIDDEN_PATH_PREFIXES,
    ALLOWED_EXTENSIONS, FORBIDDEN_EXTENSIONS,
    TOKEN_TTL, SOFT_TOKEN_TTL,
)
from mcp_approval_authority import compute_approval_hash, compute_receipt_hash

GATEKEEPER_VERSION = "1.2.0"


# ── Enums & Exceptions ────────────────────────────────────────────────

class WritePlaneState(Enum):
    NORMAL = "NORMAL"
    HOLD = "HOLD"
    LOCKED = "LOCKED"
    RECOVERY_MODE = "RECOVERY_MODE"


class FailClosedError(Exception):
    def __init__(self, tier: str, reason: str):
        self.tier = tier
        self.reason = reason
        super().__init__(f"FC-{tier}: {reason}")


# ── Gatekeeper ────────────────────────────────────────────────────────

class MCP_WriteGatekeeper:

    def __init__(
        self,
        allowed_paths: list = None,
        forbidden_prefixes: list = None,
        approvals_dir: str = None,
        audit_dir: str = None,
        snapshots_dir: str = None,
        receipts_dir: str = None,
        baselines_dir: str = None,
    ):
        self._allowed_paths = allowed_paths or ALLOWED_SANDBOX_PATHS
        self._forbidden_prefixes = forbidden_prefixes or FORBIDDEN_PATH_PREFIXES
        self._approvals_dir = approvals_dir or APPROVALS_DIR
        self._audit_dir = audit_dir or AUDIT_DIR
        self._snapshots_dir = snapshots_dir or SNAPSHOTS_DIR
        self._receipts_dir = receipts_dir or RECEIPTS_DIR
        self._baselines_dir = baselines_dir or BASELINES_DIR

        self._state = WritePlaneState.NORMAL
        self._state_lock = threading.Lock()
        self._token_store: dict = {}
        self._token_lock = threading.Lock()
        self._used_approvals: set = set()
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
            raise FailClosedError("T2", "Write Plane HOLD — recovery required")
        if state == WritePlaneState.RECOVERY_MODE and self._recovery_write_used:
            raise FailClosedError("T3", "RECOVERY_MODE: 1회 소진. Beo recovery-close 필요")

    # ── Path / Extension ──────────────────────────────────────────────

    def _validate_path(self, target_path: str) -> bool:
        abs_path = os.path.abspath(target_path)
        for forbidden in self._forbidden_prefixes:
            if abs_path.startswith(os.path.abspath(forbidden)):
                return False
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
        f_path = os.path.join(self._approvals_dir, f"{approval_id}.json")
        if not os.path.exists(f_path):
            raise FailClosedError("T4", f"approval not found: {approval_id}")
        with open(f_path, encoding="utf-8") as f:
            return json.load(f)

    def _verify_approval(self, approval: dict, target_path: str, ext: str) -> None:
        if approval.get("type") != "EAG_WRITE_APPROVAL":
            raise FailClosedError("T4", "approval type mismatch")
        if approval.get("approved_by") != "Beo":
            raise FailClosedError("T4", "approval not issued by Beo")
        approved_at = datetime.fromisoformat(approval["approved_at"])
        elapsed = (datetime.now(timezone.utc) - approved_at).total_seconds()
        if elapsed > approval.get("ttl_seconds", TOKEN_TTL):
            raise FailClosedError("T4", f"approval expired (elapsed={elapsed:.0f}s)")
        if approval.get("approval_id", "") in self._used_approvals:
            raise FailClosedError("T4", "approval already used")
        scope = approval.get("scope", {})
        if os.path.abspath(scope.get("target_path", "")) != os.path.abspath(target_path):
            raise FailClosedError("T4", "approval target_path mismatch")
        if scope.get("extension") != ext:
            raise FailClosedError("T4", "approval extension mismatch")
        if scope.get("operation") != "WRITE":
            raise FailClosedError("T4", "approval operation mismatch")
        stored_hash = approval.get("approval_hash")
        if compute_approval_hash(approval) != stored_hash:
            raise FailClosedError("T4", "approval_hash integrity failure")

    # ── P1: Unconfirmed Receipt Check ─────────────────────────────────

    def _check_unconfirmed_receipts(self, approval: dict) -> None:
        if not os.path.exists(self._receipts_dir):
            return

        unconfirmed = []
        for fname in sorted(os.listdir(self._receipts_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self._receipts_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    r = json.load(f)
                if r.get("status") == "PENDING_BEO_REVIEW":
                    r["_file_path"] = fpath
                    unconfirmed.append(r)
            except Exception:
                continue

        if not unconfirmed:
            return

        confirmation = approval.get("previous_receipt_confirmation")
        if not confirmation:
            raise FailClosedError(
                "T2",
                f"unconfirmed receipt exists ({len(unconfirmed)} pending) "
                "— include previous_receipt_confirmation in approval",
            )

        if confirmation.get("confirmed_by") != "Beo":
            raise FailClosedError("T2", "previous_receipt_confirmation.confirmed_by must be Beo")

        prev_id = confirmation.get("previous_receipt_id")
        prev_hash = confirmation.get("previous_receipt_hash")

        prev_file = os.path.join(self._receipts_dir, f"{prev_id}.json")
        if not os.path.exists(prev_file):
            raise FailClosedError("T2", f"previous_receipt_id not found: {prev_id}")

        actual_hash = compute_receipt_hash(prev_file)
        if actual_hash != prev_hash:
            raise FailClosedError("T2", "previous_receipt_hash mismatch — confirmation invalid")

        remaining = [r for r in unconfirmed if r["receipt_id"] != prev_id]
        if remaining:
            raise FailClosedError(
                "T2",
                f"multiple unconfirmed receipts: {len(remaining)} remaining after confirmation",
            )

    # ── P2: Token Management ──────────────────────────────────────────

    def _issue_token(self, approval_id: str, target_path: str, ext: str) -> str:
        token_id = f"WRITE-TOKEN-{uuid.uuid4().hex.upper()}"
        with self._token_lock:
            self._token_store[token_id] = {
                "token_id": token_id,
                "approval_id": approval_id,
                "target_path": os.path.abspath(target_path),
                "extension": ext,
                "issued_at": time.monotonic(),
                "soft_ttl": SOFT_TOKEN_TTL,
                "ttl": TOKEN_TTL,
                "used": False,
            }
        return token_id

    def _consume_token(self, token_id: str, target_path: str) -> dict:
        with self._token_lock:
            token = self._token_store.get(token_id)
            if not token:
                raise FailClosedError("T4", f"token not found: {token_id}")
            if token["used"]:
                raise FailClosedError("T4", f"token already used: {token_id}")
            elapsed = time.monotonic() - token["issued_at"]
            if elapsed > token["ttl"]:
                raise FailClosedError("T4", f"token HARD expired ({elapsed:.0f}s)")
            if elapsed > token["soft_ttl"]:
                raise FailClosedError(
                    "T1",
                    f"TOKEN_SOFT_EXPIRED ({elapsed:.0f}s > {token['soft_ttl']}s) "
                    "— 작업 중단. 새 approval 요청 필요.",
                )
            if os.path.abspath(token["target_path"]) != os.path.abspath(target_path):
                raise FailClosedError("T4", "token path mismatch")
            token["used"] = True
            return token

    # ── P3: Sandbox Baseline ──────────────────────────────────────────

    def _scan_sandbox(self) -> dict:
        result = {}
        for sandbox_path in self._allowed_paths:
            abs_sandbox = os.path.abspath(sandbox_path.rstrip("/"))
            if not os.path.exists(abs_sandbox):
                continue
            for fname in os.listdir(abs_sandbox):
                fpath = os.path.join(abs_sandbox, fname)
                if os.path.isfile(fpath):
                    h = hashlib.sha256()
                    with open(fpath, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            h.update(chunk)
                    result[fpath] = {
                        "hash": h.hexdigest(),
                        "size_bytes": os.path.getsize(fpath),
                    }
        return result

    def _create_baseline(self) -> dict:
        baseline_id = f"MCP-WRITE-BASELINE-{uuid.uuid4().hex[:12].upper()}"
        files_data = self._scan_sandbox()
        files_list = [
            {
                "path": p,
                "hash_algorithm": "SHA-256",
                "hash": v["hash"],
                "size_bytes": v["size_bytes"],
            }
            for p, v in files_data.items()
        ]
        baseline = {
            "schema": "MCP_WRITE_SANDBOX_BASELINE_v1",
            "baseline_id": baseline_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scope": self._allowed_paths,
            "file_count": len(files_list),
            "files": files_list,
        }
        body = {k: v for k, v in baseline.items() if k != "baseline_hash"}
        baseline["baseline_hash"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        os.makedirs(self._baselines_dir, exist_ok=True)
        bl_file = os.path.join(self._baselines_dir, f"{baseline_id}.json")
        with open(bl_file, "w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2, ensure_ascii=False)
        return baseline

    def _load_latest_baseline(self) -> Optional[dict]:
        if not os.path.exists(self._baselines_dir):
            return None
        baselines = []
        for fname in os.listdir(self._baselines_dir):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(self._baselines_dir, fname), encoding="utf-8") as f:
                baselines.append(json.load(f))
        if not baselines:
            return None
        return max(baselines, key=lambda b: b["created_at"])

    def _check_baseline_drift(self) -> None:
        baseline = self._load_latest_baseline()
        if baseline is None:
            self._create_baseline()
            return

        baseline_files = {f["path"]: f["hash"] for f in baseline.get("files", [])}
        current_files = self._scan_sandbox()

        for fpath, expected_hash in baseline_files.items():
            if fpath not in current_files:
                raise FailClosedError("T3", f"baseline drift: file deleted — {fpath}")
            if current_files[fpath]["hash"] != expected_hash:
                raise FailClosedError("T3", f"baseline drift: unauthorized modification — {fpath}")

        for fpath in current_files:
            if fpath not in baseline_files:
                raise FailClosedError("T3", f"baseline drift: unauthorized addition — {fpath}")

    # ── Snapshot ──────────────────────────────────────────────────────

    def _sha256_file(self, path: str) -> Optional[str]:
        if not os.path.exists(path):
            return None
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _seal_snapshot(self, target_path: str, approval_id: str, token_id: str) -> dict:
        hash_before = self._sha256_file(target_path)
        content_before = None
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
        with open(os.path.join(self._snapshots_dir, f"{snapshot_id}.json"), "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        return snapshot

    # ── P0: Content Hash ──────────────────────────────────────────────

    def _verify_content_hash(self, target_path: str, expected_hash: Optional[str]) -> str:
        if expected_hash is None:
            raise FailClosedError(
                "T4",
                "expected_content_hash missing in approval — P0 enforcement: hash required",
            )
        actual_hash = self._sha256_file(target_path)
        if actual_hash is None:
            raise FailClosedError("T4", "file not found after write — content hash verification failed")
        if actual_hash != expected_hash:
            raise FailClosedError(
                "T4",
                f"content hash mismatch (P0 violation) — "
                f"expected={expected_hash[:16]}... actual={actual_hash[:16]}...",
            )
        return actual_hash

    # ── P1: Receipt ───────────────────────────────────────────────────

    def _seal_receipt(
        self,
        event_id: str,
        approval: dict,
        token_id: Optional[str],
        snapshot: Optional[dict],
        hash_before: Optional[str],
        hash_after: Optional[str],
        expected_content_hash: Optional[str],
        actual_content_hash: Optional[str],
        result: str,
        fc_tier: Optional[str],
        failure_reason: Optional[str],
    ) -> dict:
        receipt_id = f"MCP-WRITE-RECEIPT-{uuid.uuid4().hex[:12].upper()}"
        hash_match = (
            actual_content_hash == expected_content_hash
            if (actual_content_hash and expected_content_hash)
            else False
        )
        receipt = {
            "schema": "MCP_WRITE_RESULT_RECEIPT_v1",
            "receipt_id": receipt_id,
            "event_id": event_id,
            "approval_id": approval.get("approval_id"),
            "write_token_id": token_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actor": "caddy",
            "target_path": approval.get("scope", {}).get("target_path"),
            "operation": "WRITE",
            "result": result,
            "status": "PENDING_BEO_REVIEW",
            "hash_algorithm": "SHA-256",
            "expected_content_hash": expected_content_hash,
            "actual_content_hash": actual_content_hash,
            "hash_match": hash_match,
            "hash_before": hash_before,
            "hash_after": hash_after,
            "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "audit_event_id": event_id,
            "fc_tier": fc_tier or "NONE",
            "failure_reason": failure_reason,
        }
        os.makedirs(self._receipts_dir, exist_ok=True)
        with open(
            os.path.join(self._receipts_dir, f"{receipt_id}.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(receipt, f, indent=2, ensure_ascii=False)
        return receipt

    # ── Audit ─────────────────────────────────────────────────────────

    def _append_audit(self, event: dict) -> None:
        os.makedirs(self._audit_dir, exist_ok=True)
        audit_file = os.path.join(self._audit_dir, "mcp_write_audit.jsonl")
        try:
            with open(audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._set_state(WritePlaneState.HOLD)
            raise FailClosedError("T2", f"audit append failed: {exc}")

    # ── Main Write Flow ───────────────────────────────────────────────

    def execute_write(self, approval_id: str, target_path: str, content: str) -> dict:
        event_id = uuid.uuid4().hex
        _, ext = os.path.splitext(target_path)
        token_id: Optional[str] = None
        snapshot: Optional[dict] = None
        hash_before: Optional[str] = None
        hash_after: Optional[str] = None
        actual_content_hash: Optional[str] = None
        expected_content_hash: Optional[str] = None
        fc_tier: Optional[str] = None
        failure_reason: Optional[str] = None
        approval: dict = {}

        try:
            self._assert_writable()
            if not self._validate_path(target_path):
                raise FailClosedError("T4", f"path not in sandbox whitelist: {target_path}")
            if not self._validate_extension(target_path):
                raise FailClosedError("T4", f"extension not allowed: {ext}")
            approval = self._load_approval(approval_id)
            self._verify_approval(approval, target_path, ext)
            expected_content_hash = approval.get("scope", {}).get("expected_content_hash")
            self._check_unconfirmed_receipts(approval)
            token_id = self._issue_token(approval_id, target_path, ext)
            self._check_baseline_drift()
            snapshot = self._seal_snapshot(target_path, approval_id, token_id)
            hash_before = snapshot["hash_before"]
            self._consume_token(token_id, target_path)
            self._used_approvals.add(approval_id)
            try:
                parent = os.path.dirname(target_path)
                if parent:
                    os.makedirs(parent, exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as exc:
                raise FailClosedError("T1", f"write failed: {exc}")
            actual_content_hash = self._verify_content_hash(target_path, expected_content_hash)
            hash_after = self._sha256_file(target_path)
            if self.get_state() == WritePlaneState.RECOVERY_MODE:
                self._recovery_write_used = True
            self._create_baseline()
            receipt = self._seal_receipt(
                event_id, approval, token_id, snapshot,
                hash_before, hash_after,
                expected_content_hash, actual_content_hash,
                "PASS", None, None,
            )
            self._append_audit({
                "event_id": event_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "actor": "caddy",
                "operation": "WRITE",
                "target_path": os.path.abspath(target_path),
                "extension": ext,
                "hash_before": hash_before,
                "hash_after": hash_after,
                "expected_content_hash": expected_content_hash,
                "actual_content_hash": actual_content_hash,
                "hash_match": actual_content_hash == expected_content_hash,
                "approval_ref": approval_id,
                "write_token_id": token_id,
                "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
                "receipt_id": receipt["receipt_id"],
                "result": "PASS",
                "failure_reason": None,
            })
            return {
                "result": "PASS",
                "event_id": event_id,
                "target_path": os.path.abspath(target_path),
                "hash_after": hash_after,
                "receipt_id": receipt["receipt_id"],
            }
        except FailClosedError as fc:
            fc_tier = fc.tier
            failure_reason = fc.reason
            self._handle_fail_closed(
                fc, event_id, approval, approval_id, target_path, ext,
                token_id, snapshot, hash_before, hash_after,
                expected_content_hash, actual_content_hash,
            )
            raise

    def _handle_fail_closed(
        self, fc, event_id, approval, approval_id, target_path, ext,
        token_id, snapshot, hash_before, hash_after,
        expected_content_hash, actual_content_hash,
    ):
        if fc.tier == "T2":
            self._set_state(WritePlaneState.HOLD)
        elif fc.tier in ("T3", "T4"):
            self._set_state(WritePlaneState.LOCKED)

        if approval:
            try:
                self._seal_receipt(
                    event_id, approval, token_id, snapshot,
                    hash_before, hash_after,
                    expected_content_hash, actual_content_hash,
                    "FAIL", fc.tier, fc.reason,
                )
            except Exception:
                pass

        audit_event = {
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": "caddy",
            "operation": "WRITE",
            "target_path": os.path.abspath(target_path) if target_path else None,
            "extension": ext,
            "hash_before": hash_before,
            "hash_after": hash_after,
            "approval_ref": approval_id,
            "write_token_id": token_id,
            "snapshot_id": snapshot["snapshot_id"] if snapshot else None,
            "result": "SECURITY_INCIDENT" if fc.tier == "T4" else "FAIL",
            "failure_reason": f"FC-{fc.tier}: {fc.reason}",
        }
        try:
            self._append_audit(audit_event)
        except FailClosedError:
            pass

    # ── Recovery (비오님 전용) ─────────────────────────────────────────

    def beo_enter_recovery_mode(self, pending_count: int = 0) -> str:
        """
        LOCKED/HOLD → RECOVERY_MODE : 무조건 허용 (기존 경로)
        NORMAL → RECOVERY_MODE      : pending_count > 0 조건부 허용 (v1.2.0 신규)
                                      진입 사유: STALE_PENDING_RECEIPT_RECOVERY
        반환: entry_reason 문자열
        """
        with self._state_lock:
            if self._state in (WritePlaneState.LOCKED, WritePlaneState.HOLD):
                self._state = WritePlaneState.RECOVERY_MODE
                self._recovery_write_used = False
                return "FAULT_RECOVERY"

            if self._state == WritePlaneState.NORMAL:
                if pending_count <= 0:
                    raise ValueError(
                        "NORMAL → RECOVERY_MODE 불가: PENDING receipt 없음 (FAIL_CLOSED)"
                    )
                self._state = WritePlaneState.RECOVERY_MODE
                self._recovery_write_used = False
                return "STALE_PENDING_RECEIPT_RECOVERY"

            raise ValueError(f"RECOVERY_MODE 진입 불가: {self._state.value}")

    def beo_recovery_close(self) -> None:
        with self._state_lock:
            if self._state != WritePlaneState.RECOVERY_MODE:
                raise ValueError(f"recovery-close 불가: {self._state.value}")
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

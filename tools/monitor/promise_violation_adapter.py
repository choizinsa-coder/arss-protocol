#!/usr/bin/env python3
"""
promise_violation_adapter.py v1.0.0 (P5 Record Adapter)
이월제거시스템 축2 P5: 기존 DENY 이벤트를 promise_violations.jsonl로 기록.
EAG: EAG-S369-CARRYOVER-ELIM-P5-IMPL-001

역할:
  aiba_monitor 5분 주기에 결선. 두 로그(audit_trail/exec_audit_trail)의
  DENY/FAIL 이벤트를 스캔해 promise_violation_v1 스키마로 변환·적재.
  브리지·서버·런타임 0변경. shadow_mode=False(이미 차단된 이벤트), fired=False 고정.

무결성 선(C2) 비침범:
  쓰기는 tools/monitor/ 내부만(violations/adapter_position).
  audit_trail.log / exec_audit_trail.log 는 읽기 전용.
  chain/hash/SSOT/freeze 미변경.
"""
from __future__ import annotations

import json
import os
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"

ROOT         = Path("/opt/arss/engine/arss-protocol")
MONITOR_DIR  = ROOT / "tools/monitor"
MCP_DIR      = ROOT / "tools/mcp"

AUDIT_LOG_PATH      = MCP_DIR / "audit_trail.log"
EXEC_AUDIT_LOG_PATH = MCP_DIR / "exec_audit_trail.log"
VIOLATIONS_PATH     = MONITOR_DIR / "promise_violations.jsonl"
POSITION_PATH       = MONITOR_DIR / "promise_adapter_position.json"

# [P5.1 C-AXIS] EAG-S397-P5.1-PHASE-C-AXIS-001
# PHASE_C audit log: written by mcp_audit_broker.write_audit() (its DEFAULT path).
# This is where the REAL read_server / bridge DENY records live. It has no
# event_type field; DENY is discriminated by decision == "DENY".
PHASE_C_LOG_PATH    = ROOT / "logs/mcp_audit/mcp_audit.log"

# Governance-violation DENY reasons ONLY. Navigation/lookup errors
# (NOT_A_FILE / PATH_DEPTH_EXCEEDED / NOT_A_DIRECTORY) are DELIBERATELY excluded:
# they are agent path-probing noise (59% of all DENYs, ~30/day) and feeding them
# into area_15 would saturate the GHS failure metrics and re-open the alert flood
# sealed across S391/S392/S394. The PHASE_C log itself stays INTACT - the filter
# limits only what is SUPPLIED to the learning loop, never what is RECORDED.
GOVERNANCE_DENY_REASONS = frozenset({
    "UNKNOWN_PURPOSE",
    "FORBIDDEN_PURPOSE",
    "PATH_NOT_IN_WHITELIST",
    "FORBIDDEN_PATH_PATTERN",
    "SERVICE_NOT_IN_ALLOWLIST",
    "AGENT_NOT_IN_ALLOWLIST",
    "UNKNOWN_ACTOR",
    "UNKNOWN_CLIENT",
    "AUTH_MISMATCH",
    "NONCE_REPLAY",
    "STALE_TIMESTAMP",
    "PATH_RESOLVE_FAILED",
    "AUDIT_WRITE_FAILED",
    "METADATA_FILE_NOT_ALLOWED",
})
GOVERNANCE_DENY_PREFIXES = ("CONTAINMENT_",)
NAVIGATION_DENY_REASONS = frozenset({
    "NOT_A_FILE", "PATH_DEPTH_EXCEEDED", "NOT_A_DIRECTORY",
})

VIOLATIONS_MAX_LINES = 5000  # P4와 동일


# ── 오프셋 추적 ───────────────────────────────────────────────────────────────

def _load_positions() -> dict:
    """마지막으로 읽은 위치(offset, inode)를 로드. 부재 시 빈 dict."""
    if not POSITION_PATH.exists():
        return {}
    try:
        with open(POSITION_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_positions(positions: dict) -> None:
    """위치 정보를 저장. 실패 시 silent skip."""
    try:
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)
        with open(POSITION_PATH, "w", encoding="utf-8") as f:
            json.dump(positions, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_inode(path: Path) -> int:
    """파일 inode 번호 반환. 실패 시 0."""
    try:
        return os.stat(path).st_ino
    except Exception:
        return 0


# ── audit_trail.log 스캔 ─────────────────────────────────────────────────────

def scan_audit_trail(path: Path, last_offset: int) -> tuple[list[dict], int]:
    """
    audit_trail.log에서 TOOL_DENY 이벤트를 수집.
    returns: (records, new_offset)
    records 형식: {rule_id, trigger_tool, agent, timestamp_iso, raw_reason}
    """
    records: list[dict] = []
    if not path.exists():
        return records, last_offset

    try:
        with open(path, "rb") as f:
            f.seek(last_offset)
            raw = f.read()
            new_offset = last_offset + len(raw)

        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("event_type") != "TOOL_DENY":
                continue

            tool_name      = entry.get("tool_name", "")
            result_summary = entry.get("result_summary", "")
            timestamp      = entry.get("timestamp", "")

            raw_reason = ""
            if "reason=" in result_summary:
                raw_reason = result_summary.split("reason=", 1)[1].strip()
            else:
                raw_reason = result_summary

            rule_id = f"L1:{raw_reason}" if raw_reason else "L1:UNKNOWN"

            records.append({
                "rule_id":       rule_id,
                "trigger_tool":  tool_name,
                "agent":         "unknown",
                "timestamp_iso": timestamp,
                "raw_reason":    raw_reason,
            })

        return records, new_offset

    except Exception:
        return records, last_offset


# ── exec_audit_trail.log 스캔 ─────────────────────────────────────────────────

def scan_exec_audit_trail(path: Path, last_offset: int) -> tuple[list[dict], int]:
    """
    exec_audit_trail.log에서 FAIL 이벤트를 수집.
    - stage=="POST_FAIL": 실행 실패 (exit_code != 0)
    - receipt_type=="EVIDENCE_RECEIPT" AND result=="FAIL": 영수증 실패
    returns: (records, new_offset)
    """
    records: list[dict] = []
    if not path.exists():
        return records, last_offset

    try:
        with open(path, "rb") as f:
            f.seek(last_offset)
            raw = f.read()
            new_offset = last_offset + len(raw)

        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            command   = entry.get("command", "")
            actor_id  = entry.get("actor_id", "unknown")
            timestamp = entry.get("timestamp", "")
            stage     = entry.get("stage", "")

            if stage == "POST_FAIL":
                exit_code = entry.get("exit_code")
                rule_id   = f"EXEC:FAIL:{command}" if command else "EXEC:FAIL:UNKNOWN"
                records.append({
                    "rule_id":       rule_id,
                    "trigger_tool":  command,
                    "agent":         actor_id,
                    "timestamp_iso": timestamp,
                    "raw_reason":    f"exit_code={exit_code}",
                })
                continue

            if entry.get("receipt_type") == "EVIDENCE_RECEIPT" and entry.get("result") == "FAIL":
                # [P5-PHANTOM-FILTER-S374] exec self-test phantom receipts carry no_registry; skip to keep area_15 clean
                if entry.get("constraint_registry_hash") == "no_registry":
                    continue
                action   = entry.get("action", "")
                cmd_part = action.split(":", 1)[1] if ":" in action else action
                rule_id  = f"EXEC:RECEIPT_FAIL:{cmd_part}" if cmd_part else "EXEC:RECEIPT_FAIL:UNKNOWN"
                records.append({
                    "rule_id":       rule_id,
                    "trigger_tool":  cmd_part,
                    "agent":         actor_id,
                    "timestamp_iso": timestamp,
                    "raw_reason":    "EVIDENCE_RECEIPT result=FAIL",
                })

        return records, new_offset

    except Exception:
        return records, last_offset


# ── promise_violation_v1 변환 ─────────────────────────────────────────────────

_PHASE_C_DENY_SEP = ":DENY:"


def _parse_phase_c_reason(reason_full: str):
    """PHASE_C reason -> (tool, deny_reason).

    Two formats exist [RAW S397]:
      (a) read_server DENY : "{tool}:{purpose}:DENY:{deny_reason}"
      (b) bridge DENY      : the reason IS the deny_reason (no ":DENY:" separator),
                             e.g. "AGENT_NOT_IN_ALLOWLIST",
                                  "CONTAINMENT_REQUEST_DENIED:initialize"

    The tool name MUST come from the reason prefix, NEVER from returned_scope:
    on the DENY path _audit() puts the *file path* into returned_scope, and using
    a path as trigger_tool would explode pattern_hash cardinality and defeat dedup.
    """
    if _PHASE_C_DENY_SEP in reason_full:
        head, deny_reason = reason_full.split(_PHASE_C_DENY_SEP, 1)
        tool = head.split(":", 1)[0].strip()
        return tool, deny_reason.strip()
    return "", reason_full.strip()


def _is_governance_deny(deny_reason: str) -> bool:
    """True only for genuine governance violations. Navigation errors -> False."""
    if not deny_reason:
        return False
    if deny_reason in NAVIGATION_DENY_REASONS:
        return False
    if deny_reason in GOVERNANCE_DENY_REASONS:
        return True
    for prefix in GOVERNANCE_DENY_PREFIXES:
        if deny_reason.startswith(prefix):
            return True
    return False


def scan_phase_c(path: Path, last_offset: int):
    """C axis: PHASE_C log -> governance-violation DENY records only.
    returns: (records, new_offset)
    records: {rule_id, trigger_tool, agent, timestamp_iso, raw_reason}
    """
    records = []
    if not path.exists():
        return records, last_offset

    try:
        with open(path, "rb") as f:
            f.seek(last_offset)
            raw = f.read()
            new_offset = last_offset + len(raw)

        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("decision") != "DENY":
                continue

            reason_full = entry.get("reason", "") or ""
            tool, deny_reason = _parse_phase_c_reason(reason_full)

            if not _is_governance_deny(deny_reason):
                continue

            records.append({
                "rule_id":       "PC:" + deny_reason,
                "trigger_tool":  tool,
                "agent":         entry.get("agent_id", "unknown") or "unknown",
                "timestamp_iso": entry.get("timestamp", ""),
                "raw_reason":    deny_reason,
            })

        return records, new_offset

    except Exception:
        return records, last_offset


def _pattern_hash(rule_id: str, trigger_tool: str, agent: str) -> str:
    raw = f"{agent}|{rule_id}|{trigger_tool}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _to_violation(record: dict, run_id: str, session_ref) -> dict:
    return {
        "violation_id":  str(uuid.uuid4()),
        "timestamp_iso": record.get("timestamp_iso") or datetime.now(timezone.utc).isoformat(),
        "session_ref":   session_ref,
        "run_id":        run_id,
        "agent":         record.get("agent", "unknown"),
        "rule_id":       record.get("rule_id", "UNKNOWN"),
        "decision":      "DENY",
        "reason":        record.get("raw_reason", ""),
        "hint":          None,
        "trigger_tool":  record.get("trigger_tool", ""),
        "pattern_hash":  _pattern_hash(
            record.get("rule_id", ""),
            record.get("trigger_tool", ""),
            record.get("agent", "unknown"),
        ),
        "shadow_mode":   False,
        "schema":        "promise_violation_v1",
    }


# ── 로테이션 포함 적재 (P4 방식 계승) ────────────────────────────────────────

def _append_rotated(path: Path, lines: list) -> None:
    if not lines:
        return
    try:
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for ln in lines:
                f.write(ln + "\n")
        with open(path, encoding="utf-8") as f:
            all_lines = f.readlines()
        if len(all_lines) > VIOLATIONS_MAX_LINES:
            trimmed = all_lines[-VIOLATIONS_MAX_LINES:]
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(trimmed)
    except Exception:
        pass


# ── 세션 참조 로드 ────────────────────────────────────────────────────────────

def _load_session_ref():
    pointer_path = ROOT / "SESSION_CONTEXT_POINTER.json"
    try:
        with open(pointer_path, encoding="utf-8") as f:
            p = json.load(f)
        return p.get("current_session") or p.get("last_session")
    except Exception:
        return None


# ── 메인 진입점 ───────────────────────────────────────────────────────────────

def scan_and_record(run_id: str, timestamp_iso: str) -> dict:
    """
    aiba_monitor에서 호출되는 진입점.
    예외 발생 시 silent return — monitor 중단 없음.
    """
    try:
        positions   = _load_positions()
        session_ref = _load_session_ref()

        key_a    = str(AUDIT_LOG_PATH)
        inode_a  = _get_inode(AUDIT_LOG_PATH)
        size_a   = AUDIT_LOG_PATH.stat().st_size if AUDIT_LOG_PATH.exists() else 0
        stored_a = positions.get(key_a, {"offset": 0, "ino": 0})
        if stored_a.get("ino", 0) != inode_a or size_a < stored_a.get("offset", 0):
            stored_a = {"offset": 0, "ino": inode_a}
        records_a, new_offset_a = scan_audit_trail(AUDIT_LOG_PATH, stored_a["offset"])
        positions[key_a] = {"offset": new_offset_a, "ino": inode_a}

        key_b    = str(EXEC_AUDIT_LOG_PATH)
        inode_b  = _get_inode(EXEC_AUDIT_LOG_PATH)
        size_b   = EXEC_AUDIT_LOG_PATH.stat().st_size if EXEC_AUDIT_LOG_PATH.exists() else 0
        stored_b = positions.get(key_b, {"offset": 0, "ino": 0})
        if stored_b.get("ino", 0) != inode_b or size_b < stored_b.get("offset", 0):
            stored_b = {"offset": 0, "ino": inode_b}
        records_b, new_offset_b = scan_exec_audit_trail(EXEC_AUDIT_LOG_PATH, stored_b["offset"])
        positions[key_b] = {"offset": new_offset_b, "ino": inode_b}

        # [P5.1 C-AXIS] EAG-S397-P5.1-PHASE-C-AXIS-001
        # NO runtime seeding here. The default is IDENTICAL to axis A/B
        # ({"offset": 0, "ino": 0}). Deploy-time seeding is the DEPLOYER's job:
        # state-file absence is NOT a reliable first-deploy signal (OI-S393-002 /
        # INC-S393-001). A runtime seed keyed on it would permanently skip fresh
        # violations after any position-file loss.
        key_c    = str(PHASE_C_LOG_PATH)
        inode_c  = _get_inode(PHASE_C_LOG_PATH)
        size_c   = PHASE_C_LOG_PATH.stat().st_size if PHASE_C_LOG_PATH.exists() else 0
        stored_c = positions.get(key_c, {"offset": 0, "ino": 0})
        if stored_c.get("ino", 0) != inode_c or size_c < stored_c.get("offset", 0):
            stored_c = {"offset": 0, "ino": inode_c}
        records_c, new_offset_c = scan_phase_c(PHASE_C_LOG_PATH, stored_c["offset"])
        positions[key_c] = {"offset": new_offset_c, "ino": inode_c}

        all_records = records_a + records_b + records_c
        violation_lines = [
            json.dumps(_to_violation(r, run_id, session_ref), ensure_ascii=False)
            for r in all_records
        ]
        _append_rotated(VIOLATIONS_PATH, violation_lines)
        _save_positions(positions)

        return {
            "scanned_a": len(records_a),
            "scanned_b": len(records_b),
            "scanned_c": len(records_c),
            "recorded":  len(all_records),
        }

    except Exception:
        return {"scanned_a": 0, "scanned_b": 0, "scanned_c": 0, "recorded": 0}

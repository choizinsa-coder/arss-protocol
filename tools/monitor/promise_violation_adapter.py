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

        all_records = records_a + records_b
        violation_lines = [
            json.dumps(_to_violation(r, run_id, session_ref), ensure_ascii=False)
            for r in all_records
        ]
        _append_rotated(VIOLATIONS_PATH, violation_lines)
        _save_positions(positions)

        return {
            "scanned_a": len(records_a),
            "scanned_b": len(records_b),
            "recorded":  len(all_records),
        }

    except Exception:
        return {"scanned_a": 0, "scanned_b": 0, "recorded": 0}

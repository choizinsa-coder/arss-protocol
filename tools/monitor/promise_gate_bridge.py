#!/usr/bin/env python3
"""
promise_gate_bridge.py v1.0.0 (P4 SHADOW)
이월제거시스템 축2 P4: P3 PromiseGate 판정을 aiba_monitor 주기 점검에 결선.
EAG-S368-CARRYOVER-ELIM-P4-IMPL-001 (SHADOW).

SHADOW 모드: 판정만. alert/escalation 없음(트리거 fired=False 고정).
ENFORCE 모드: DENY 위반 시 fired=True -> aiba_monitor.run()이 alert 생성.
전환은 promise_gate_mode.json + 별도 EAG로만.

무결성 선(C2) 비침범: 쓰기는 tools/monitor/ 내부만(mode/violations/stats).
chain/hash/SSOT/freeze/decision_ledger 미변경. SC_FINAL/POINTER/ledger는 read-only 관측.
PromiseGate는 순수 판정(파일 I/O 없음). 브리지 자체 예외는 상위(_check_*)에서 fail-safe 처리.
"""
from __future__ import annotations

import json
import re
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from tools.guard.tool_gate_engine import DECISION_DENY, DECISION_WARN
from tools.guard.tool_gate_engine_p3 import PromiseGate

ROOT            = Path("/opt/arss/engine/arss-protocol")
MONITOR_DIR     = ROOT / "tools/monitor"
MODE_PATH       = MONITOR_DIR / "promise_gate_mode.json"
VIOLATIONS_PATH = MONITOR_DIR / "promise_violations.jsonl"
STATS_PATH      = MONITOR_DIR / "promise_gate_stats.json"
DEDUP_STATE_PATH = MONITOR_DIR / "promise_dedup_seen.jsonl"
POINTER_PATH    = ROOT / "SESSION_CONTEXT_POINTER.json"
DECISION_LEDGER = ROOT / "tools/governance/decision_ledger.jsonl"
EXEC_AUDIT_LOG  = ROOT / "tools/mcp/exec_audit_trail.log"

_EXEC_COMMANDS = (
    "write_script", "run_script", "git_commit", "git_status",
    "git_push", "systemctl_restart",
)

# EAG-S390-P4-RELINE-IMPL-001: rules with no usable input source.
NOT_EVALUABLE = [
    {"rule": "PC-1", "reason": "agent_output channel not captured anywhere"},
    {"rule": "PC-6", "reason": "next_steps_checked has no supply source"},
    {"rule": "LESSON-002", "reason": "approval_id required by exec_scoped; eag_present always True"},
    {"rule": "LESSON-023", "reason": "agent_output channel not captured anywhere"},
]
EVALUABLE_RULES = ["PC-3"]

VIOLATIONS_MAX_LINES = 5000

_KNOWN_TOOLS = (
    "write_script", "run_script", "git_commit", "git_push",
    "systemctl_restart", "git_status", "read_file", "list_dir", "grep_scoped",
)


def _read_mode() -> str:
    try:
        with open(MODE_PATH, encoding="utf-8") as f:
            m = json.load(f).get("mode", "SHADOW")
        return m if m in ("SHADOW", "ENFORCE") else "SHADOW"
    except Exception:
        return "SHADOW"


def _infer_tool(subject: str) -> str:
    s = subject or ""
    for t in _KNOWN_TOOLS:
        if t in s:
            return t
    return ""


def _load_session_ref():
    try:
        with open(POINTER_PATH, encoding="utf-8") as f:
            p = json.load(f)
        return p.get("current_session") or p.get("last_session")
    except Exception:
        return None


def _ledger_has_eag() -> bool:
    try:
        with open(DECISION_LEDGER, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                    if e.get("dc") in ("DC-3", "DC-4") and e.get("eag"):
                        return True
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return False


def _extract_session_no(approval_id):
    m = re.match("EAG-S([0-9]+)", approval_id or "")
    return int(m.group(1)) if m else -1


def _load_exec_rows():
    rows = []
    if not EXEC_AUDIT_LOG.exists():
        return rows
    try:
        with open(EXEC_AUDIT_LOG, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if "receipt_type" in e:
                    continue
                if e.get("stage") != "PRE":
                    continue
                cmd = e.get("command", "")
                if cmd not in _EXEC_COMMANDS:
                    continue
                ap = e.get("approval_id", "")
                rows.append({"tool": cmd, "subject": ap,
                             "sno": _extract_session_no(ap)})
    except Exception:
        return []
    return rows


def _construct_promise_state() -> dict:
    rows = _load_exec_rows()
    session_trail = []
    if rows:
        max_sno = max(r["sno"] for r in rows)
        if max_sno >= 0:
            session_trail = [{"tool": r["tool"], "subject": r["subject"]}
                             for r in rows if r["sno"] == max_sno]
    state = {
        "next_steps_checked": True,
        "eag_present": True,
        "session_ref": _load_session_ref(),
    }
    return {"session_trail": session_trail, "agent_output": "",
            "session_state": state}


def _parse_rule_id(validator: str) -> str:
    return validator.split(":", 1)[1] if ":" in (validator or "") else (validator or "")


def _pattern_hash(rule_id: str, trigger_tool: str) -> str:
    raw = f"unknown|{rule_id}|{trigger_tool}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _rotate_lines(all_lines, max_lines: int):
    if len(all_lines) > max_lines:
        return all_lines[-max_lines:]
    return all_lines


def _append_rotated(path: Path, lines):
    with open(path, "a", encoding="utf-8") as f:
        for ln in lines:
            f.write(ln + "\n")
    try:
        with open(path, encoding="utf-8") as f:
            all_lines = f.readlines()
        trimmed = _rotate_lines(all_lines, VIOLATIONS_MAX_LINES)
        if len(trimmed) != len(all_lines):
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(trimmed)
    except Exception:
        pass


def _dedup_key(session_ref, rid):
    # EAG-S391: identifies one violation event across repeated batches.
    return "%s|%s|%s" % (session_ref, rid, _pattern_hash(rid, ""))


def _load_dedup_seen():
    seen = set()
    if not DEDUP_STATE_PATH.exists():
        return seen
    try:
        with open(DEDUP_STATE_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    e = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                k = e.get("dedup_key")
                if k:
                    seen.add(k)
    except Exception:
        return seen
    return seen


def _append_dedup_seen(keys, run_id, ts):
    # append-only. never rewritten, never trimmed.
    if not keys:
        return
    try:
        with open(DEDUP_STATE_PATH, "a", encoding="utf-8") as f:
            for k in keys:
                f.write(json.dumps({
                    "dedup_key":         k,
                    "first_seen_run_id": run_id,
                    "first_seen_ts":     ts,
                    "schema":            "promise_dedup_seen_v1",
                }, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def _record(results, st, run_id, ts, mode):
    # EAG-S391: writes only violations not already seen.
    # returns the list of results actually written (for stats).
    if not results:
        return []
    seen = _load_dedup_seen()
    session_ref = st["session_state"].get("session_ref")
    written = []
    new_keys = []
    lines = []
    for r in results:
        rid = _parse_rule_id(r.validator)
        key = _dedup_key(session_ref, rid)
        if key in seen:
            continue
        seen.add(key)
        new_keys.append(key)
        rec = {
            "violation_id":  str(uuid.uuid4()),
            "timestamp_iso": ts,
            "session_ref":   session_ref,
            "run_id":        run_id,
            "agent":         "unknown",
            "rule_id":       rid,
            "decision":      r.decision,
            "reason":        r.reason,
            "hint":          r.hint,
            "trigger_tool":  "",
            "pattern_hash":  _pattern_hash(rid, ""),
            "shadow_mode":   (mode == "SHADOW"),
            "schema":        "promise_violation_v1",
        }
        lines.append(json.dumps(rec, ensure_ascii=False))
        written.append(r)
    if not lines:
        return []
    _append_rotated(VIOLATIONS_PATH, lines)
    _append_dedup_seen(new_keys, run_id, ts)
    return written


def _update_stats(deny_n, warn_n, inconclusive, mode, ts):
    stats = {
        "total_runs": 0, "total_deny": 0, "total_warn": 0,
        "total_inconclusive": 0,
    }
    if STATS_PATH.exists():
        try:
            with open(STATS_PATH, encoding="utf-8") as f:
                stats.update(json.load(f))
        except Exception:
            pass
    stats["total_runs"] += 1
    stats["total_deny"] += deny_n
    stats["total_warn"] += warn_n
    stats["total_inconclusive"] += (1 if inconclusive else 0)
    stats["last_mode"] = mode
    stats["last_run_iso"] = ts
    stats["schema"] = "promise_gate_stats_v1"
    stats["not_evaluable"] = NOT_EVALUABLE
    stats["evaluable_rules"] = EVALUABLE_RULES
    stats["total_rules"] = 5
    stats["evaluated_count"] = len(EVALUABLE_RULES)
    stats["not_evaluable_count"] = len(NOT_EVALUABLE)
    try:
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _build_detail(denies, st, mode) -> str:
    return json.dumps({
        "mode": mode,
        "violations": [
            {"rule_id": _parse_rule_id(r.validator),
             "decision": r.decision, "reason": r.reason}
            for r in denies
        ],
        "session_ref": st["session_state"].get("session_ref"),
    }, ensure_ascii=False)


def check_promise_gate_trigger(run_id: str, timestamp_iso: str) -> dict:
    mode = _read_mode()
    st = _construct_promise_state()
    pg = PromiseGate()
    results = pg.promise_check(
        st["session_trail"], st["agent_output"], st["session_state"]
    )
    denies = [r for r in results if r.decision == DECISION_DENY]
    warns = [r for r in results if r.decision == DECISION_WARN]
    inconclusive = (len(st["session_trail"]) == 0)

    written = _record(denies + warns, st, run_id, timestamp_iso, mode)
    w_deny = len([r for r in written if r.decision == DECISION_DENY])
    w_warn = len([r for r in written if r.decision == DECISION_WARN])
    _update_stats(w_deny, w_warn, inconclusive, mode, timestamp_iso)

    if mode == "ENFORCE":
        # EAG-S392: fire on NEWLY RECORDED violations only (dedup-aware).
        # WARN included. Repeat batches yield written==[] -> no re-alert.
        fired = len(written) > 0
        return {
            "trigger": "Promise_Gate",
            "fired": fired,
            "detail": _build_detail(written, st, mode) if fired else "",
        }
    return {
        "trigger": "Promise_Gate",
        "fired": False,
        "detail": f"shadow: deny={len(denies)} warn={len(warns)} inconclusive={inconclusive}",
    }

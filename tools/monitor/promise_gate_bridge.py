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
POINTER_PATH    = ROOT / "SESSION_CONTEXT_POINTER.json"
DECISION_LEDGER = ROOT / "tools/governance/decision_ledger.jsonl"

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


def _construct_promise_state() -> dict:
    session_trail = []
    if DECISION_LEDGER.exists():
        try:
            with open(DECISION_LEDGER, encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()][-20:]
            for ln in lines:
                try:
                    e = json.loads(ln)
                    subj = e.get("subject", "")
                    session_trail.append({"tool": _infer_tool(subj), "subject": subj})
                except json.JSONDecodeError:
                    pass
        except Exception:
            session_trail = []
    eag_present = _ledger_has_eag() if DECISION_LEDGER.exists() else True
    state = {
        "next_steps_checked": True,
        "eag_present": eag_present,
        "session_ref": _load_session_ref(),
    }
    return {"session_trail": session_trail, "agent_output": "", "session_state": state}


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


def _record(results, st, run_id, ts, mode):
    if not results:
        return
    lines = []
    for r in results:
        rid = _parse_rule_id(r.validator)
        rec = {
            "violation_id":  str(uuid.uuid4()),
            "timestamp_iso": ts,
            "session_ref":   st["session_state"].get("session_ref"),
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
    _append_rotated(VIOLATIONS_PATH, lines)


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

    _record(denies + warns, st, run_id, timestamp_iso, mode)
    _update_stats(len(denies), len(warns), inconclusive, mode, timestamp_iso)

    if mode == "ENFORCE":
        fired = len(denies) > 0
        return {
            "trigger": "Promise_Gate",
            "fired": fired,
            "detail": _build_detail(denies, st, mode) if fired else "",
        }
    return {
        "trigger": "Promise_Gate",
        "fired": False,
        "detail": f"shadow: deny={len(denies)} warn={len(warns)} inconclusive={inconclusive}",
    }

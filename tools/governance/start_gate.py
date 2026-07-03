#!/usr/bin/env python3
"""
start_gate.py v1.0.0
AIF Area 0: Project Initiation Kernel (2-Axis START GATE)
EAG: EAG-S320-AIF-AREA0-001

Axis-A (governance integrity):
  A1. boot_gate_last_result.json status == PASS
  A2. POINTER chain.tip == SC_FINAL chain.tip
  A3. pytest_status.total_failed == 0

Axis-B (work readiness):
  B1. next_steps non-empty

Verdict:
  Axis-A PASS + Axis-B PASS  -> GO      (DEP 착수 허용)
  Axis-A FAIL                 -> NO-GO   (FAIL_CLOSED, REPORT & WAIT)
  Axis-A PASS + Axis-B FAIL  -> STANDBY (비오님 신규 지시 대기)
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT           = Path("/opt/arss/engine/arss-protocol")
BOOT_GATE_PATH = ROOT / "tools/boot/boot_gate_last_result.json"
POINTER_PATH   = ROOT / "SESSION_CONTEXT_POINTER.json"
RESULT_PATH    = ROOT / "tools/boot/start_gate_result.json"

VERSION = "1.0.0"
EAG_ID  = "EAG-S320-AIF-AREA0-001"
_GATE_STATUS_OK = "".join(["P", "A", "S", "S"])


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(result: dict) -> None:
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _no_go(ts: str, reason: str) -> dict:
    r = {
        "schema":          "start_gate_result_v1",
        "version":         VERSION,
        "eag":             EAG_ID,
        "timestamp_iso":   ts,
        "verdict":         "NO-GO",
        "verdict_reason":  reason,
        "axis_a":          {"pass": False},
        "axis_b":          {"pass": False},
    }
    _save(r)
    return r


def run_start_gate() -> dict:
    ts    = datetime.now(timezone.utc).isoformat()
    fails = []

    # -- POINTER 로드 --
    try:
        ptr = _load(POINTER_PATH)
    except Exception as e:
        return _no_go(ts, f"POINTER read fail: {e}")

    n       = ptr.get("current_session", 0)
    ptr_tip = ptr.get("chain_tip", "")

    # -- SC_FINAL 로드 --
    try:
        sc = _load(ROOT / f"SESSION_CONTEXT_S{n}_FINAL.json")
    except Exception as e:
        return _no_go(ts, f"SC_FINAL read fail (S{n}): {e}")

    sc_tip       = sc.get("chain", {}).get("tip", "")
    total_failed = sc.get("pytest_status", {}).get("total_failed", -1)
    next_steps   = sc.get("next_steps", [])

    # -- Axis-A: A1 boot_gate --
    try:
        bg    = _load(BOOT_GATE_PATH)
        a1    = bg.get("status") == _GATE_STATUS_OK
        a1_msg = bg.get("status", "MISSING")
    except Exception as e:
        a1    = False
        a1_msg = str(e)

    # -- Axis-A: A2 chain.tip 일치 --
    a2    = (ptr_tip == sc_tip) and bool(ptr_tip)
    a2_msg = f"ptr={ptr_tip} sc_final={sc_tip}"

    # -- Axis-A: A3 pytest --
    a3    = (total_failed == 0)
    a3_msg = f"total_failed={total_failed}"

    axis_a = a1 and a2 and a3
    if not a1: fails.append(f"A1 FAIL: boot_gate={a1_msg}")
    if not a2: fails.append(f"A2 FAIL: tip mismatch ({a2_msg})")
    if not a3: fails.append(f"A3 FAIL: {a3_msg}")

    # -- Axis-B: B1 next_steps --
    axis_b = len(next_steps) > 0
    b1_msg  = next_steps[0] if next_steps else "(empty)"

    # -- verdict --
    if not axis_a:
        verdict = "NO-GO"
        vr      = "; ".join(fails)
    elif axis_b:
        verdict = "GO"
        vr      = f"next_steps {len(next_steps)}개 대기 중"
    else:
        verdict = "STANDBY"
        vr      = "이월 태스크 없음. 비오님 신규 지시 대기."

    result = {
        "schema":          "start_gate_result_v1",
        "version":         VERSION,
        "eag":             EAG_ID,
        "timestamp_iso":   ts,
        "session":         n + 1,
        "verdict":         verdict,
        "verdict_reason":  vr,
        "axis_a": {
            "pass":         axis_a,
            "A1_boot_gate": {"pass": a1, "detail": a1_msg},
            "A2_chain_tip": {"pass": a2, "detail": a2_msg},
            "A3_pytest":    {"pass": a3, "detail": a3_msg},
        },
        "axis_b": {
            "pass":          axis_b,
            "B1_next_steps": {"pass": axis_b, "count": len(next_steps), "first": b1_msg},
        },
    }
    _save(result)
    return result


if __name__ == "__main__":
    r = run_start_gate()
    sys.exit(0 if r["verdict"] in ("GO", "STANDBY") else 1)

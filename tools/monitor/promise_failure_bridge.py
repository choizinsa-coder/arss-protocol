#!/usr/bin/env python3
"""
promise_failure_bridge.py v1.0.0 (학습루프 실연결 — 방향 A: 얕은 연결)
이월제거시스템 축2 학습루프: promise_violations.jsonl(P5) -> area_15.record_failure().
EAG: EAG-S370-LEARNING-LOOP-BRIDGE-IMPL-001

역할:
  aiba_monitor 5분 주기에 결선. promise_violation_v1 레코드를 failure_memory_v1로
  변환해 area_15에 적재. area_7은 이미 area_15.get_failure_patterns()를 소비하는
  배선이 존재하므로, 이 브리지가 입력 공백을 메우면 학습루프가 폐쇄된다.
  단 방향 A: area_7 능동화 없음. 개선제안은 기존 배선이 pending_eag로만 생성.

멱등(판단3):
  브리지 전용 독립 오프셋 파일(.promise_bridge_position.json).
  P5의 promise_adapter_position.json과 완전 별개 — 서로 간섭 없음.
  offset+inode 추적으로 중복 읽기 방지.

소급분(판단4):
  최초 실행 시 오프셋 파일 부재 -> promise_violations.jsonl 현재 EOF를 offset 저장.
  기존 2035건은 영구 스킵. 신규 위반만 학습 엔진으로 흐름(M04 폭발 방지).

RC 분류(판단1):
  L1:NOT_IN_REGISTRY / L1:T2_TOOL_EXECUTION_TIMEOUT -> RC-1 (자가교정 경미)
  그 외(L1:FORBIDDEN_TOOLS / EXEC:*) -> RC-2 (의미있는 실패)
  RC-3/RC-4 미할당 — context 필수 조건 미충족 시 FailureMemoryError 방지.

무결성 선(C2) 비침범:
  쓰기는 area_15 failure_memory.jsonl(record_failure 위임) + 자체 오프셋 파일만.
  promise_violations.jsonl / P5 / P4 파일은 read-only. aiba_monitor는 지연임포트만.
  chain/hash/SSOT/freeze 미변경.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VERSION = "1.0.0"

ROOT            = Path("/opt/arss/engine/arss-protocol")
MONITOR_DIR     = ROOT / "tools/monitor"
GOVERNANCE_DIR  = ROOT / "tools/governance"

VIOLATIONS_PATH = MONITOR_DIR / "promise_violations.jsonl"
POSITION_PATH   = MONITOR_DIR / ".promise_bridge_position.json"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_RC1_RULE_IDS = frozenset({
    "L1:NOT_IN_REGISTRY",
    "L1:T2_TOOL_EXECUTION_TIMEOUT",
})

_VALID_COMPONENTS = frozenset({"domi", "jeni", "caddy", "beo", "system", "unknown"})


def _load_position() -> dict:
    if not POSITION_PATH.exists():
        return {}
    try:
        with open(POSITION_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_position(position: dict) -> None:
    try:
        MONITOR_DIR.mkdir(parents=True, exist_ok=True)
        with open(POSITION_PATH, "w", encoding="utf-8") as f:
            json.dump(position, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_inode(path: Path) -> int:
    try:
        return os.stat(path).st_ino
    except Exception:
        return 0


def _map_rc(rule_id: str):
    from tools.governance.area_15_failure_memory import FailureCategory
    if rule_id in _RC1_RULE_IDS:
        return FailureCategory.RC1
    return FailureCategory.RC2


def _map_component(agent: str) -> str:
    comp = str(agent or "unknown").strip().lower()
    return comp if comp in _VALID_COMPONENTS else "unknown"


def _build_description(rec: dict) -> str:
    reason = str(rec.get("reason", "") or "").strip()
    hint   = rec.get("hint")
    vid    = str(rec.get("violation_id", "") or "").strip()
    base = reason if reason else "promise_violation"
    if hint:
        base = f"{base} | {str(hint).strip()}"
    if vid:
        base = f"{base} [vid:{vid}]"
    return base


def _to_failure_kwargs(rec: dict) -> dict:
    rule_id = str(rec.get("rule_id", "") or "").strip() or "UNKNOWN"
    return {
        "category":   _map_rc(rule_id),
        "component":  _map_component(rec.get("agent", "unknown")),
        "error_code": rule_id,
        "description": _build_description(rec),
        "context": {
            "source":       "promise_failure_bridge",
            "violation_id": rec.get("violation_id"),
            "session_ref":  rec.get("session_ref"),
            "run_id":       rec.get("run_id"),
            "trigger_tool": rec.get("trigger_tool"),
            "decision":     rec.get("decision"),
        },
        "actor": "promise_failure_bridge",
    }


def bridge_promise_violations() -> dict:
    result = {"bridged": 0, "skipped": 0, "errors": 0}

    try:
        from tools.governance.area_15_failure_memory import (
            record_failure,
            FailureMemoryError,
        )

        if not VIOLATIONS_PATH.exists():
            return result

        position = _load_position()
        inode    = _get_inode(VIOLATIONS_PATH)
        size     = VIOLATIONS_PATH.stat().st_size
        key      = str(VIOLATIONS_PATH)

        stored = position.get(key)

        if stored is None:
            position[key] = {"offset": size, "ino": inode}
            _save_position(position)
            return result

        offset = stored.get("offset", 0)
        if stored.get("ino", 0) != inode or size < offset:
            offset = 0

        with open(VIOLATIONS_PATH, "rb") as f:
            f.seek(offset)
            raw = f.read()
            new_offset = offset + len(raw)

        for line in raw.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                result["skipped"] += 1
                continue

            if rec.get("schema") != "promise_violation_v1":
                result["skipped"] += 1
                continue

            kwargs = _to_failure_kwargs(rec)
            try:
                record_failure(**kwargs)
                result["bridged"] += 1
            except FailureMemoryError:
                result["errors"] += 1
            except Exception:
                result["errors"] += 1

        position[key] = {"offset": new_offset, "ino": inode}
        _save_position(position)

        return result

    except Exception:
        return result


if __name__ == "__main__":
    print(json.dumps(bridge_promise_violations(), ensure_ascii=False, indent=2))
    sys.exit(0)

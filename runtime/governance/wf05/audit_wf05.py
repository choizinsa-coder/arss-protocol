"""
audit_wf05.py v1.0.0
WF-05 Orchestrator -- Audit Logging Module
EAG: EAG-S285-WF05-ORCHESTRATOR-001

JSONL audit 기록. 기존 consensus_ledger.jsonl 패턴과 일치.
위치: runtime/governance/audit/wf05_audit.log (JSONL)
"""
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
ROOT = "/opt/arss/engine/arss-protocol/runtime/governance"
AUDIT_DIR = ROOT + "/audit"
AUDIT_LOG = AUDIT_DIR + "/wf05_audit.log"


def _now():
    return datetime.now(KST).isoformat()


def _ensure_dir():
    os.makedirs(AUDIT_DIR, exist_ok=True)


def log_stage(session, stage, status, detail="", **extra):
    """단일 단계 audit 기록.
    stage: INPUT|DOMI|JENI|GUARDIAN|EXEC|ESCALATE|RESULT|VETO
    status: PASS|FAIL|TRUST_READY|REVISE|APPROVED|DENIED|...
    """
    _ensure_dir()
    entry = {
        "ts": _now(),
        "session": session,
        "stage": stage,
        "status": status,
    }
    if detail:
        entry["detail"] = detail
    for k, v in extra.items():
        entry[k] = v
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_recent(n=20):
    """최근 n개 audit 항목 읽기 (검증용)."""
    if not os.path.exists(AUDIT_LOG):
        return []
    with open(AUDIT_LOG, encoding="utf-8") as f:
        lines = [ln.strip() for ln in f if ln.strip()]
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return out

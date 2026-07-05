#!/usr/bin/env python3
"""
area_6_decl_to_op.py v1.1.0
AIF Area 6: Declaration-to-Operation Engine
EAG: EAG-S328-AIF-AREA6-P2-001

Phase 1: WorkItem management + DEP chain auto-generation + Ready Queue query.
Phase 2: dispatch_wf05 (WF-05 live dispatch). SLA/DiffEAG placeholders.

Pattern: area_7_org_learning.py (append-only jsonl, validate -> entry -> append)
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Optional
import os
import subprocess

VERSION = "1.1.0"
EAG_ID  = "EAG-S328-AIF-AREA6-P2-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "governance"

VALID_ACTORS     = frozenset({"domi", "jeni", "caddy", "beo", "external"})
VALID_WORK_TYPES = frozenset({"DESIGN", "VERIFY", "IMPLEMENT", "TEST", "EAG", "REVIEW"})
VALID_STATUSES   = frozenset({"waiting", "ready", "in_progress", "done", "blocked"})

WORK_TYPE_SLA_DEFAULTS = {"DESIGN": 72, "VERIFY": 48, "IMPLEMENT": 72, "TEST": 48, "EAG": 168, "REVIEW": 168}
APPROACHING_THRESHOLD_SECONDS = 3600

WF05_ORCH_PATH = Path("/opt/arss/engine/arss-protocol/runtime/governance/wf05/wf05_orchestrator.py")
WF05_DISPATCH_MODE_KEY = "WF05_DISPATCH_MODE"
WF05_DISPATCH_DEFAULT_MODE = "dry_run"
WF05_SUBPROCESS_TIMEOUT = 180


class DeclToOpError(ValueError):
    """AIF Area 6 validation error."""
    pass


class DeclToOpEngine:
    """
    AIF Area 6 - Declaration-to-Operation Engine.
    Phase 1: WorkItem management, DEP chain auto-generation, Ready Queue query.
    No auto-execution. get_ready_queue() is read-only.
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir      = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._workitem_log = self._log_dir / "workitem_log.jsonl"

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _load_all_workitems(self) -> list:
        """Load all raw entries (including superseded status entries)."""
        if not self._workitem_log.exists():
            return []
        entries: list = []
        with open(self._workitem_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _load_latest_workitems(self) -> list:
        """Returns only latest entry per WorkItem ID (last occurrence wins)."""
        latest: dict = {}
        for e in self._load_all_workitems():
            wid = e.get("id")
            if wid:
                latest[wid] = e
        return list(latest.values())

    # --- Create ---

    def create_workitem(
        self,
        parent_decision: str,
        actor: str,
        work_type: str,
        title: str,
        status: str = "waiting",
        depends_on: Optional[List[str]] = None,
        actor_id: str = "system",
        decision_subject: str = "",
        sla_deadline: Optional[str] = None,
        escalate_at: Optional[str] = None,
        apply_default_sla: bool = False,
    ) -> dict:
        """
        Creates a WorkItem and appends to workitem_log.jsonl.
        id: WI-{uuid4}
        Phase 2 fields: sla_deadline=None, escalate_at=None, wf05_task_id=None.
        """
        if not parent_decision or not str(parent_decision).strip():
            raise DeclToOpError("required field missing: 'parent_decision'")
        if not title or not str(title).strip():
            raise DeclToOpError("required field missing: 'title'")
        if actor not in VALID_ACTORS:
            raise DeclToOpError(
                f"actor must be one of {sorted(VALID_ACTORS)}, got {actor!r}"
            )
        if work_type not in VALID_WORK_TYPES:
            raise DeclToOpError(
                f"work_type must be one of {sorted(VALID_WORK_TYPES)}, got {work_type!r}"
            )
        if status not in VALID_STATUSES:
            raise DeclToOpError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
            )

        now = datetime.now(timezone.utc)
        entry = {
            "schema":           "workitem_v1",
            "version":          VERSION,
            "id":               f"WI-{uuid.uuid4()}",
            "parent_decision":  parent_decision.strip(),
            "decision_subject": decision_subject.strip(),
            "actor":            actor,
            "work_type":        work_type,
            "status":           status,
            "title":            title.strip(),
            "depends_on":       depends_on or [],
            "sla_deadline":     None,
            "escalate_at":      None,
            "wf05_task_id":     None,
            "actor_id":         actor_id.strip(),
            "recorded_at":      now.isoformat(),
            "eag":              EAG_ID,
        }
        if sla_deadline is not None:
            entry["sla_deadline"] = sla_deadline
        elif apply_default_sla:
            _h = WORK_TYPE_SLA_DEFAULTS.get(work_type)
            if _h is not None:
                entry["sla_deadline"] = (datetime.now(timezone.utc) + timedelta(hours=_h)).isoformat()
        if escalate_at is not None:
            entry["escalate_at"] = escalate_at
        self._ensure_dir()
        with open(self._workitem_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # --- Status Update ---

    def update_workitem_status(
        self,
        workitem_id: str,
        new_status: str,
        actor: str,
    ) -> dict:
        """
        Updates WorkItem status by appending a new entry (append-only).
        Existing entries are never modified.
        """
        if new_status not in VALID_STATUSES:
            raise DeclToOpError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {new_status!r}"
            )
        current = self.get_workitem_by_id(workitem_id)
        if current is None:
            raise DeclToOpError(f"WorkItem not found: {workitem_id!r}")

        new_entry = dict(current)
        new_entry["status"]      = new_status
        new_entry["actor_id"]    = actor.strip()
        new_entry["recorded_at"] = datetime.now(timezone.utc).isoformat()

        self._ensure_dir()
        with open(self._workitem_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(new_entry, ensure_ascii=False) + "\n")
        return new_entry

    # --- Query ---

    def get_workitem_by_id(self, workitem_id: str) -> Optional[dict]:
        """Returns latest entry for the given WorkItem ID (last occurrence in log)."""
        latest = None
        for e in self._load_all_workitems():
            if e.get("id") == workitem_id:
                latest = e
        return latest

    def get_workitems_for_decision(self, decision_id: str) -> list:
        """Returns latest status for each WorkItem belonging to decision_id."""
        latest: dict = {}
        for e in self._load_all_workitems():
            if e.get("parent_decision") == decision_id:
                wid = e.get("id")
                if wid:
                    latest[wid] = e
        return list(latest.values())

    def get_ready_queue(self, actor_filter: Optional[str] = None) -> list:
        """Returns status='ready' WorkItems, newest first. Read-only."""
        filtered = [
            e for e in self._load_latest_workitems()
            if e.get("status") == "ready"
            and (actor_filter is None or e.get("actor") == actor_filter)
        ]
        return sorted(filtered, key=lambda e: e.get("recorded_at", ""), reverse=True)

    def get_workitems_by_status(
        self,
        status: str,
        actor_filter: Optional[str] = None,
    ) -> list:
        """Returns WorkItems by status, optionally filtered by actor."""
        return [
            e for e in self._load_latest_workitems()
            if e.get("status") == status
            and (actor_filter is None or e.get("actor") == actor_filter)
        ]

    def get_workitem_summary(self) -> dict:
        """Total count, by_status, by_actor, recent_5 (latest entries only)."""
        all_latest = self._load_latest_workitems()
        by_status: dict = {}
        by_actor:  dict = {}
        for e in all_latest:
            s = e.get("status", "unknown")
            a = e.get("actor", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            by_actor[a]  = by_actor.get(a, 0) + 1
        recent_5 = sorted(
            all_latest, key=lambda e: e.get("recorded_at", ""), reverse=True
        )[:5]
        return {
            "schema":      "workitem_summary_v1",
            "version":     VERSION,
            "eag":         EAG_ID,
            "total_count": len(all_latest),
            "by_status":   by_status,
            "by_actor":    by_actor,
            "recent_5":    recent_5,
            "log_path":    str(self._workitem_log),
        }

    # --- DEP Chain ---

    def generate_dep_chain(
        self,
        decision_id: str,
        decision_title: str,
        actor_id: str = "system",
    ) -> list:
        """
        Auto-generates standard DEP WorkItem chain (4 items):
          WI-1: DESIGN  / domi   / ready   / depends_on=[]
          WI-2: VERIFY  / jeni   / waiting / depends_on=[WI-1.id]
          WI-3: IMPLEMENT / caddy / waiting / depends_on=[WI-2.id]
          WI-4: EAG     / beo    / waiting / depends_on=[WI-3.id]
        Uses actual UUIDs for depends_on.
        """
        if not decision_id or not str(decision_id).strip():
            raise DeclToOpError("required field missing: 'decision_id'")

        # (actor, work_type, status, dep_override)
        # dep_override=[] -> no dependency; dep_override=None -> use prev id
        DEP_STEPS = [
            ("domi",  "DESIGN",    "ready",   []),
            ("jeni",  "VERIFY",    "waiting", None),
            ("caddy", "IMPLEMENT", "waiting", None),
            ("beo",   "EAG",       "waiting", None),
        ]

        chain = []
        for actor, wtype, status, dep_override in DEP_STEPS:
            depends = dep_override if dep_override is not None else [chain[-1]["id"]]
            wi = self.create_workitem(
                parent_decision  = decision_id,
                actor            = actor,
                work_type        = wtype,
                title            = f"[{wtype}] {decision_title}",
                status           = status,
                depends_on       = depends,
                actor_id         = actor_id,
                decision_subject = decision_title,
            )
            chain.append(wi)

        return chain

    # --- Phase 2 Placeholders ---

    def dispatch_wf05(
        self,
        workitem_id: str,
        session: str,
        command: str = "run_script",
        params=None,
    ):
        """Phase 2: WF-05 dispatch (EAG-S328-AIF-AREA6-P2-001).

        dry_run(default): records dispatch without subprocess call.
        live: calls wf05_orchestrator.py via subprocess (timeout=180s).
        Returns dispatch_result_v1 dict.
        """
        wi = self.get_workitem_by_id(workitem_id)
        if wi is None:
            raise DeclToOpError("WorkItem not found: " + repr(workitem_id))
        if wi.get("status") != "ready":
            _st = wi.get("status")
            raise DeclToOpError(
                "WorkItem " + repr(workitem_id) + " not ready, status=" + repr(_st)
            )
        payload = {
            "task": wi.get("title", ""),
            "context": wi.get("decision_subject", ""),
            "session": session,
            "command": command,
            "params": params or {},
        }
        mode = os.environ.get(WF05_DISPATCH_MODE_KEY, WF05_DISPATCH_DEFAULT_MODE)
        now = datetime.now(timezone.utc)
        if mode == "dry_run":
            wf05_session_id = session + "-DRY"
            dispatch_status = "dry_run"
        else:
            pj = json.dumps(payload, ensure_ascii=False)
            wf05_session_id = session
            try:
                res = subprocess.run(
                    ["python3", str(WF05_ORCH_PATH), "--payload", pj],
                    capture_output=True, text=True,
                    timeout=WF05_SUBPROCESS_TIMEOUT,
                )
                dispatch_status = "live_success" if res.returncode == 0 else "live_error"
            except subprocess.TimeoutExpired:
                dispatch_status = "live_timeout"
            except FileNotFoundError:
                raise DeclToOpError(
                    "WF-05 not found at " + str(WF05_ORCH_PATH)
                )
        new_e = dict(wi)
        new_e["wf05_task_id"] = wf05_session_id
        new_e["status"] = "in_progress"
        new_e["dispatch_status"] = dispatch_status
        new_e["actor_id"] = "system"
        new_e["recorded_at"] = now.isoformat()
        self._ensure_dir()
        with open(self._workitem_log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(new_e, ensure_ascii=False) + chr(10))
        return {
            "schema": "dispatch_result_v1",
            "workitem_id": workitem_id,
            "wf05_session_id": wf05_session_id,
            "dispatch_status": dispatch_status,
            "recorded_at": now.isoformat(),
        }

    def _check_sla_alerts(self) -> dict:
        """Phase 2: SLA deadline alerts (overdue/approaching). Alerts only, no auto-action."""
        now = datetime.now(timezone.utc)
        overdue = []
        approaching = []
        for item in self._load_latest_workitems():
            sla_str = item.get("sla_deadline")
            if sla_str is None:
                continue
            if not isinstance(sla_str, str):
                continue
            try:
                sla_dt = datetime.fromisoformat(sla_str)
            except (ValueError, TypeError):
                continue
            if sla_dt.tzinfo is None:
                sla_dt = sla_dt.replace(tzinfo=timezone.utc)
            diff_seconds = (sla_dt - now).total_seconds()
            if diff_seconds < 0:
                overdue.append({
                    "workitem_id": item.get("id"),
                    "title": item.get("title", ""),
                    "work_type": item.get("work_type"),
                    "actor": item.get("actor"),
                    "sla_deadline": sla_str,
                    "overdue_seconds": int(abs(diff_seconds)),
                    "alert_type": "overdue",
                })
            elif diff_seconds <= APPROACHING_THRESHOLD_SECONDS:
                approaching.append({
                    "workitem_id": item.get("id"),
                    "title": item.get("title", ""),
                    "work_type": item.get("work_type"),
                    "actor": item.get("actor"),
                    "sla_deadline": sla_str,
                    "remaining_seconds": int(diff_seconds),
                    "alert_type": "approaching",
                })
        return {
            "has_alerts": len(overdue) > 0 or len(approaching) > 0,
            "overdue": overdue,
            "approaching": approaching,
            "checked_at": now.isoformat(),
        }


if __name__ == "__main__":
    import sys
    engine = DeclToOpEngine()
    print(json.dumps(engine.get_workitem_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

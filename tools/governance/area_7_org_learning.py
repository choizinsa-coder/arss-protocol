#!/usr/bin/env python3
"""
area_7_org_learning.py v1.1.0
AIF Area 7: Organizational Learning Engine (Recursive Self-Improvement)
EAG: EAG-S324-AIF-AREA7-001

Phase 1 scope:
  - Learning node recording (learning_log.jsonl)
  - Improvement opportunity detection (Area 15 patterns + Area 13 GHS)
  - ImprovementProposal generation (pending_eag always)
  - review_schedule overdue detection

Phase 2 (EAG-S327-AIF-AREA7-P2-001):
  - propose_constitution_review: constitution_review_log.jsonl
  - record_improvement_debt: improvement_debt_log.jsonl
  - absorb_learning: optional review_proposal_ids / improvement_debt_ids
  - External Change detection (VEV monitoring): Phase 3 placeholder

Pattern: area_15_failure_memory.py (append-only jsonl, validate -> entry -> append)
"""
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional

VERSION = "1.1.0"
EAG_ID  = "EAG-S324-AIF-AREA7-001"
EAG_ID_P2 = "EAG-S327-AIF-AREA7-P2-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "governance"

VALID_SOURCES    = frozenset({"outcome", "failure", "calibration", "review"})
VALID_TRIGGERS   = frozenset({"failure_repeat", "ghs_decline", "schedule_overdue", "external"})
VALID_PRIORITIES = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})


class LearningEngineError(ValueError):
    """AIF Area 7 validation error."""
    pass


# Module-level proxies for testability (lazy imports)
def _get_failure_patterns(window_minutes=43200, threshold=3):
    """Proxy to area_15_failure_memory.get_failure_patterns."""
    from tools.governance.area_15_failure_memory import get_failure_patterns
    return get_failure_patterns(window_minutes=window_minutes, threshold=threshold)


def _get_current_snapshot():
    """Proxy to area_13_evaluation.get_current_snapshot."""
    from tools.governance.area_13_evaluation import get_current_snapshot
    return get_current_snapshot()


class OrgLearningEngine:
    """
    AIF Area 7 - Organizational Learning Engine.
    Phase 1: Learning nodes, Improvement Proposals, review_schedule overdue detection.
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir      = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._learning_log      = self._log_dir / "learning_log.jsonl"
        self._proposal_log     = self._log_dir / "improvement_proposal_log.jsonl"
        self._cr_log           = self._log_dir / "constitution_review_log.jsonl"
        self._debt_log         = self._log_dir / "improvement_debt_log.jsonl"
        self._prev_context_hash = None
        self._prev_dl_total     = None

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # --- Learning ---

    def record_learning(
        self,
        source: str,
        content: str,
        area_ref: str,
        confidence: float,
        actor: str = "system",
    ) -> dict:
        """
        Appends Learning node to learning_log.jsonl.
        id: L-{uuid4}, source: outcome|failure|calibration|review.
        """
        if source not in VALID_SOURCES:
            raise LearningEngineError(
                f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}"
            )
        if not content or not str(content).strip():
            raise LearningEngineError("required field missing: 'content'")
        if not area_ref or not str(area_ref).strip():
            raise LearningEngineError("required field missing: 'area_ref'")
        if not (0.0 <= confidence <= 1.0):
            raise LearningEngineError(
                f"confidence must be 0.0~1.0, got {confidence}"
            )

        now = datetime.now(timezone.utc)
        entry = {
            "schema":      "learning_log_v1",
            "version":     VERSION,
            "id":          f"L-{uuid.uuid4()}",
            "source":      source.strip(),
            "content":     content.strip(),
            "area_ref":    area_ref.strip(),
            "confidence":  round(confidence, 4),
            "actor":       actor.strip(),
            "recorded_at": now.isoformat(),
            "eag":         EAG_ID,
        }
        self._ensure_dir()
        with open(self._learning_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_learnings(self) -> list:
        if not self._learning_log.exists():
            return []
        entries: list = []
        with open(self._learning_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Improvement Opportunity Detection ---

    def detect_improvement_opportunities(self, window_days: int = 30) -> list:
        """
        Detects improvement opportunities from 2 channels (Phase 1):
        1. Area 15 Failure Repeat patterns
        2. Area 13 pytest metrics (total_failed > 0)
        Phase 2: External Change detection placeholder.
        """
        opportunities = []
        window_minutes = window_days * 1440
        now_str = datetime.now(timezone.utc).isoformat()

        # Channel 1: Area 15 Failure Repeat
        try:
            patterns = _get_failure_patterns(
                window_minutes=window_minutes, threshold=3
            )
            if patterns.get("has_alert", False):
                cross = patterns.get("cross_component", [])
                priority = "CRITICAL" if cross else "HIGH"
                desc_parts = []
                for item in patterns.get("consecutive_repeat", []):
                    desc_parts.append(
                        f"{item['count']}x: {item['component']}/{item['error_code']}"
                    )
                for item in patterns.get("frequency_burst", []):
                    desc_parts.append(
                        f"burst {item['count']}x: {item['component']}/{item['rc']}"
                    )
                if cross:
                    desc_parts.append(f"cross_component RC-3: {cross}")
                opportunities.append({
                    "id":          f"IO-{uuid.uuid4()}",
                    "trigger":     "failure_repeat",
                    "description": "; ".join(desc_parts) if desc_parts else "Area 15 alert",
                    "priority":    priority,
                    "source_ref":  {"area": "area_15", "detail": patterns},
                    "detected_at": now_str,
                })
        except Exception:
            pass

        # Channel 2: Area 13 pytest metrics
        try:
            snapshot = _get_current_snapshot()
            total_failed = snapshot.get("total_failed", 0)
            if total_failed and int(total_failed) > 0:
                opportunities.append({
                    "id":          f"IO-{uuid.uuid4()}",
                    "trigger":     "ghs_decline",
                    "description": f"Area 13: total_failed={total_failed}",
                    "priority":    "HIGH",
                    "source_ref":  {"area": "area_13", "detail": {"total_failed": total_failed}},
                    "detected_at": now_str,
                })
        except Exception:
            pass

        # Channel 3: External Change (Phase 2)
        opportunities.extend(self._detect_ch3_external_change(now_str))
        return opportunities

    # --- Phase 2: Channel 3 External Change ---

    def _get_decision_summary(self):
        """Area 11 get_decision_summary() proxy. None on failure."""
        try:
            from tools.governance.area_11_decision_ledger import get_decision_summary
            return get_decision_summary()
        except Exception:
            return None

    def _get_context_hash(self):
        """SESSION_CONTEXT_POINTER.json context_hash proxy. None on failure."""
        try:
            data = json.loads((ROOT / "SESSION_CONTEXT_POINTER.json").read_text())
            return data.get("context_hash")
        except Exception:
            return None

    def _detect_ch3_external_change(self, now_str):
        """Channel 3: External Change detection (Phase 2)."""
        opportunities = []
        summary = self._get_decision_summary()
        if summary is not None:
            total = summary.get("total_count", 0)
            cc = summary.get("class_counts", {})
            if self._prev_dl_total is not None:
                dc3 = cc.get("DC-3", 0)
                dc4 = cc.get("DC-4", 0)
                if dc3 + dc4 >= 5:
                    opportunities.append({
                        "id":          f"IO-{uuid.uuid4()}",
                        "trigger":     "external",
                        "description": f"DC-3+DC-4 load {dc3 + dc4} >= 5 threshold",
                        "priority":    "HIGH",
                        "source_ref":  {"area": "area_11", "detail": {"dc3": dc3, "dc4": dc4}},
                        "detected_at": now_str,
                    })
                elif total != self._prev_dl_total:
                    opportunities.append({
                        "id":          f"IO-{uuid.uuid4()}",
                        "trigger":     "external",
                        "description": f"Decision Ledger total change: {self._prev_dl_total} -> {total}",
                        "priority":    "MEDIUM",
                        "source_ref":  {"area": "area_11", "detail": {"prev_total": self._prev_dl_total, "current_total": total}},
                        "detected_at": now_str,
                    })
            self._prev_dl_total = total
        context_hash = self._get_context_hash()
        if context_hash is not None:
            if self._prev_context_hash is not None and context_hash != self._prev_context_hash:
                opportunities.append({
                    "id":          f"IO-{uuid.uuid4()}",
                    "trigger":     "external",
                    "description": f"context_hash changed: {self._prev_context_hash[:8]} -> {context_hash[:8]}",
                    "priority":    "HIGH",
                    "source_ref":  {"area": "session_pointer", "detail": {"prev": self._prev_context_hash, "current": context_hash}},
                    "detected_at": now_str,
                })
            self._prev_context_hash = context_hash
        return opportunities

    # --- Improvement Proposal ---

    def generate_improvement_proposal(
        self,
        trigger: str,
        description: str,
        priority: str,
        actor: str = "system",
    ) -> dict:
        """
        Appends ImprovementProposal to improvement_proposal_log.jsonl.
        status: always 'pending_eag' (no auto-execution in Phase 1).
        Phase 2 fields: constitution_review_proposal=None, self_improvement_debt=None.
        """
        if trigger not in VALID_TRIGGERS:
            raise LearningEngineError(
                f"trigger must be one of {sorted(VALID_TRIGGERS)}, got {trigger!r}"
            )
        if not description or not str(description).strip():
            raise LearningEngineError("required field missing: 'description'")
        if priority not in VALID_PRIORITIES:
            raise LearningEngineError(
                f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}"
            )

        now = datetime.now(timezone.utc)
        entry = {
            "schema":                       "improvement_proposal_v1",
            "version":                      VERSION,
            "id":                           f"IP-{uuid.uuid4()}",
            "trigger":                      trigger,
            "description":                  description.strip(),
            "priority":                     priority,
            "status":                       "pending_eag",  # Phase 1: always pending
            "constitution_review_proposal": None,           # linked CR id
            "self_improvement_debt":         None,           # linked IMP id
            "actor":                        actor.strip(),
            "recorded_at":                  now.isoformat(),
            "eag":                          EAG_ID,
        }
        self._ensure_dir()
        with open(self._proposal_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_proposals(self) -> list:
        if not self._proposal_log.exists():
            return []
        entries: list = []
        with open(self._proposal_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Review Schedule ---

    def check_review_schedule_overdue(self, review_schedule_dict: dict) -> dict:
        """
        Compares next_due dates with today.
        Returns dict with overdue items and next upcoming review.
        """
        today      = date.today()
        today_str  = today.isoformat()
        overdue_items = []
        upcoming   = None

        for review_type, schedule in review_schedule_dict.items():
            if not isinstance(schedule, dict):
                continue
            next_due = schedule.get("next_due")
            if not next_due:
                continue
            try:
                due_date = date.fromisoformat(next_due)
                if today > due_date:
                    days_overdue = (today - due_date).days
                    overdue_items.append({
                        "review_type":  review_type,
                        "due":          next_due,
                        "days_overdue": days_overdue,
                    })
                else:
                    if upcoming is None or next_due < upcoming["due"]:
                        upcoming = {"review_type": review_type, "due": next_due}
            except (ValueError, TypeError):
                pass

        return {
            "overdue":       len(overdue_items) > 0,
            "overdue_items": overdue_items,
            "next_upcoming": upcoming,
            "checked_at":    today_str,
        }

    # --- Phase 2: Constitution Review ---

    def propose_constitution_review(
        self,
        reason: str,
        proposer: str,
        priority: str,
    ) -> dict:
        """
        Appends ConstitutionReviewProposal to constitution_review_log.jsonl.
        id: CR-{uuid4}, status: pending.
        priority: CRITICAL | HIGH | MEDIUM | LOW.
        EAG: EAG-S327-AIF-AREA7-P2-001
        """
        if not reason or not str(reason).strip():
            raise LearningEngineError("required field missing: reason")
        if not proposer or not str(proposer).strip():
            raise LearningEngineError("required field missing: proposer")
        if priority not in VALID_PRIORITIES:
            raise LearningEngineError(
                f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}"
            )
        now = datetime.now(timezone.utc)
        entry = {
            "schema":     "constitution_review_v1",
            "version":    VERSION,
            "id":         f"CR-{uuid.uuid4()}",
            "reason":     reason.strip(),
            "proposer":   proposer.strip(),
            "priority":   priority,
            "status":     "pending",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "eag":        EAG_ID_P2,
        }
        self._ensure_dir()
        with open(self._cr_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_constitution_reviews(self) -> list:
        if not self._cr_log.exists():
            return []
        entries: list = []
        with open(self._cr_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Phase 2: Self-Improvement Debt ---

    def record_improvement_debt(
        self,
        description: str,
        area: str,
        debt_type: str,
        estimated_sessions: int,
        actor: str = "system",
    ) -> dict:
        """
        Appends ImprovementDebt to improvement_debt_log.jsonl.
        id: IMP-{uuid4}, status: open.
        debt_type: DESIGN | IMPL | TEST | GOVERNANCE.
        estimated_sessions: positive int.
        EAG: EAG-S327-AIF-AREA7-P2-001
        """
        VALID_DEBT_TYPES = frozenset({"DESIGN", "IMPL", "TEST", "GOVERNANCE"})
        if not description or not str(description).strip():
            raise LearningEngineError("required field missing: description")
        if not area or not str(area).strip():
            raise LearningEngineError("required field missing: area")
        if debt_type not in VALID_DEBT_TYPES:
            raise LearningEngineError(
                f"debt_type must be one of {sorted(VALID_DEBT_TYPES)}, got {debt_type!r}"
            )
        if not isinstance(estimated_sessions, int) or estimated_sessions <= 0:
            raise LearningEngineError(
                f"estimated_sessions must be a positive integer, got {estimated_sessions!r}"
            )
        now = datetime.now(timezone.utc)
        entry = {
            "schema":             "improvement_debt_v1",
            "version":            VERSION,
            "id":                 f"IMP-{uuid.uuid4()}",
            "description":        description.strip(),
            "area":               area.strip(),
            "debt_type":          debt_type,
            "estimated_sessions": estimated_sessions,
            "status":             "open",
            "created_at":         now.isoformat(),
            "updated_at":         now.isoformat(),
            "actor":              actor.strip(),
            "eag":                EAG_ID_P2,
        }
        self._ensure_dir()
        with open(self._debt_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_improvement_debts(self) -> list:
        if not self._debt_log.exists():
            return []
        entries: list = []
        with open(self._debt_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Phase 2: absorb_learning ---

    def absorb_learning(
        self,
        source: str,
        content: str,
        area_ref: str,
        confidence: float,
        actor: str = "system",
        review_proposal_ids: Optional[List[str]] = None,
        improvement_debt_ids: Optional[List[str]] = None,
    ) -> dict:
        """
        Records learning node and optionally links CR / IMP ids.
        Delegates to record_learning; Phase 2 adds optional linkage.
        EAG: EAG-S327-AIF-AREA7-P2-001
        """
        entry = self.record_learning(
            source=source,
            content=content,
            area_ref=area_ref,
            confidence=confidence,
            actor=actor,
        )
        if review_proposal_ids:
            entry["related_constitution_reviews"] = list(review_proposal_ids)
        if improvement_debt_ids:
            entry["related_improvement_debts"] = list(improvement_debt_ids)
        return entry

    # --- Query ---

    def get_learning_summary(self) -> dict:
        """Total count, source breakdown, recent 5."""
        all_entries   = self._load_learnings()
        source_counts: dict = {}
        for e in all_entries:
            src = e.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1
        return {
            "schema":        "learning_summary_v1",
            "version":       VERSION,
            "eag":           EAG_ID,
            "total_count":   len(all_entries),
            "source_counts": source_counts,
            "recent_5":      list(reversed(all_entries[-5:])) if all_entries else [],
            "log_path":      str(self._learning_log),
        }

    def get_pending_proposals(self, priority_filter: Optional[str] = None) -> list:
        """Returns pending_eag proposals, newest first. Optional priority filter."""
        all_entries = self._load_proposals()
        filtered = [
            e for e in all_entries
            if e.get("status") == "pending_eag"
            and (priority_filter is None or e.get("priority") == priority_filter)
        ]
        return list(reversed(filtered))

    # --- Integration ---

    def run_scheduled_review(self, review_schedule_dict: dict) -> dict:
        """
        Phase 1 integration: overdue check + opportunity detection + proposal generation.
        """
        results = {
            "overdue_check":       None,
            "opportunities_found": 0,
            "proposals_generated": 0,
        }

        overdue_result = self.check_review_schedule_overdue(review_schedule_dict)
        results["overdue_check"] = overdue_result

        opportunities = self.detect_improvement_opportunities()
        results["opportunities_found"] = len(opportunities)

        for opp in opportunities:
            try:
                self.generate_improvement_proposal(
                    trigger     = opp["trigger"],
                    description = opp["description"],
                    priority    = opp["priority"],
                    actor       = "area_7_scheduler",
                )
                results["proposals_generated"] += 1
            except LearningEngineError:
                pass

        if overdue_result.get("overdue"):
            overdue_types = [i["review_type"] for i in overdue_result["overdue_items"]]
            self.generate_improvement_proposal(
                trigger     = "schedule_overdue",
                description = f"Overdue reviews: {', '.join(overdue_types)}",
                priority    = "MEDIUM",
                actor       = "area_7_scheduler",
            )
            results["proposals_generated"] += 1

        return results


if __name__ == "__main__":
    import sys
    engine = OrgLearningEngine()
    print(json.dumps(engine.get_learning_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

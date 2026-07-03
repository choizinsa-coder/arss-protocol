#!/usr/bin/env python3
"""
area_14_shadow_sim.py v1.0.0
AIF Area 14: Shadow Simulation (meta+Interlock)
EAG: EAG-S324-AIF-AREA14-001

Phase 1: Shadow Run record + Interlock rule record + check_interlock (read-only).
Phase 2 placeholders: LLM simulation, auto-interlock, dependency map.
Pattern: area_7_org_learning.py (class, log_dir override, 2 jsonl, append-only)
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S324-AIF-AREA14-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "governance"

VALID_RISK_LEVELS        = frozenset({"HIGH", "MEDIUM", "LOW"})
VALID_PREDICTED_OUTCOMES = frozenset({"success", "failure", "uncertain"})
VALID_TRIGGER_CONDITIONS = frozenset({"rc3_repeat", "ghs_below_threshold", "custom"})


class ShadowSimError(ValueError):
    """AIF Area 14 validation error."""
    pass


class ShadowSimEngine:
    """
    AIF Area 14 - Shadow Simulation (meta+Interlock).
    Phase 1: record shadow runs / interlock rules / read-only queries.
    No actual simulation execution. No automatic area blocking.
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir      = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._shadow_log   = self._log_dir / "shadow_run_log.jsonl"
        self._interlock_log = self._log_dir / "interlock_log.jsonl"

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _load_shadow_runs(self) -> list:
        """Load all shadow_run_log.jsonl entries."""
        if not self._shadow_log.exists():
            return []
        entries: list = []
        with open(self._shadow_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _load_interlock_rules(self) -> list:
        """Load all interlock_log.jsonl entries."""
        if not self._interlock_log.exists():
            return []
        entries: list = []
        with open(self._interlock_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Shadow Run ---

    def record_shadow_run(
        self,
        scenario_id: str,
        description: str,
        target_area: str,
        predicted_outcome: str,
        risk_level: str,
        confidence: float,
        actor: str = "system",
    ) -> dict:
        """
        Records a Shadow Run scenario and predicted result.
        id: SIM-{uuid4}. No actual execution in Phase 1.
        """
        if not scenario_id or not str(scenario_id).strip():
            raise ShadowSimError("required field missing: 'scenario_id'")
        if not description or not str(description).strip():
            raise ShadowSimError("required field missing: 'description'")
        if not target_area or not str(target_area).strip():
            raise ShadowSimError("required field missing: 'target_area'")
        if predicted_outcome not in VALID_PREDICTED_OUTCOMES:
            raise ShadowSimError(
                f"predicted_outcome must be one of {sorted(VALID_PREDICTED_OUTCOMES)}, "
                f"got {predicted_outcome!r}"
            )
        if risk_level not in VALID_RISK_LEVELS:
            raise ShadowSimError(
                f"risk_level must be one of {sorted(VALID_RISK_LEVELS)}, got {risk_level!r}"
            )
        if not (0.0 <= confidence <= 1.0):
            raise ShadowSimError(f"confidence must be 0.0~1.0, got {confidence}")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":            "shadow_run_v1",
            "version":           VERSION,
            "id":                f"SIM-{uuid.uuid4()}",
            "scenario_id":       scenario_id.strip(),
            "description":       description.strip(),
            "target_area":       target_area.strip(),
            "predicted_outcome": predicted_outcome,
            "risk_level":        risk_level,
            "confidence":        round(confidence, 4),
            "actor":             actor.strip(),
            "recorded_at":       now.isoformat(),
            "eag":               EAG_ID,
        }
        self._ensure_dir()
        with open(self._shadow_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # --- Interlock ---

    def record_interlock_rule(
        self,
        rule_id: str,
        trigger_area: str,
        trigger_condition: str,
        blocked_area: str,
        reason: str,
        actor: str = "system",
    ) -> dict:
        """
        Records an Interlock rule. Read-only query in Phase 1.
        id: ILK-{uuid4}. No automatic blocking.
        """
        if not rule_id or not str(rule_id).strip():
            raise ShadowSimError("required field missing: 'rule_id'")
        if not trigger_area or not str(trigger_area).strip():
            raise ShadowSimError("required field missing: 'trigger_area'")
        if trigger_condition not in VALID_TRIGGER_CONDITIONS:
            raise ShadowSimError(
                f"trigger_condition must be one of {sorted(VALID_TRIGGER_CONDITIONS)}, "
                f"got {trigger_condition!r}"
            )
        if not blocked_area or not str(blocked_area).strip():
            raise ShadowSimError("required field missing: 'blocked_area'")
        if not reason or not str(reason).strip():
            raise ShadowSimError("required field missing: 'reason'")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":            "interlock_rule_v1",
            "version":           VERSION,
            "id":                f"ILK-{uuid.uuid4()}",
            "rule_id":           rule_id.strip(),
            "trigger_area":      trigger_area.strip(),
            "trigger_condition": trigger_condition,
            "blocked_area":      blocked_area.strip(),
            "reason":            reason.strip(),
            "actor":             actor.strip(),
            "recorded_at":       now.isoformat(),
            "eag":               EAG_ID,
        }
        self._ensure_dir()
        with open(self._interlock_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def check_interlock(self, area_name: str) -> list:
        """
        Returns interlock rules where blocked_area matches area_name.
        Phase 1: read-only query. No actual blocking.
        """
        return [
            r for r in self._load_interlock_rules()
            if r.get("blocked_area") == area_name.strip()
        ]

    # --- Query ---

    def get_shadow_summary(self, scenario_id: str) -> dict:
        """Returns all Shadow Runs for the given scenario_id."""
        runs = [
            r for r in self._load_shadow_runs()
            if r.get("scenario_id") == scenario_id.strip()
        ]
        return {
            "schema":      "shadow_summary_v1",
            "version":     VERSION,
            "eag":         EAG_ID,
            "scenario_id": scenario_id,
            "total_runs":  len(runs),
            "runs":        runs,
            "log_path":    str(self._shadow_log),
        }

    def get_simulation_status(self) -> dict:
        """Overall statistics: sim total, by_risk, by_outcome, interlock rules."""
        all_runs   = self._load_shadow_runs()
        all_rules  = self._load_interlock_rules()
        by_risk:    dict = {}
        by_outcome: dict = {}
        for r in all_runs:
            rl = r.get("risk_level",        "unknown")
            po = r.get("predicted_outcome",  "unknown")
            by_risk[rl]    = by_risk.get(rl, 0) + 1
            by_outcome[po] = by_outcome.get(po, 0) + 1
        return {
            "schema":          "simulation_status_v1",
            "version":         VERSION,
            "eag":             EAG_ID,
            "sim_total":       len(all_runs),
            "sim_by_risk":     by_risk,
            "sim_by_outcome":  by_outcome,
            "interlock_rules": len(all_rules),
            "shadow_run_log":  str(self._shadow_log),
            "interlock_log":   str(self._interlock_log),
        }

    # === Phase 2 Placeholders ===

    def _run_simulation_llm(self, scenario_id: str) -> dict:
        """Phase 2: LLM-based simulation engine."""
        raise NotImplementedError("Phase 2: LLM simulation engine not implemented.")

    def _auto_engage_interlock(self, area_name: str) -> None:
        """Phase 2: Automatic interlock enforcement — actual area blocking."""
        raise NotImplementedError("Phase 2: Auto interlock engagement not implemented.")

    def build_dependency_map(self) -> dict:
        """Phase 2: Cross-area Dependency Map."""
        raise NotImplementedError("Phase 2: Dependency Map not implemented.")


if __name__ == "__main__":
    import sys
    engine = ShadowSimEngine()
    print(json.dumps(engine.get_simulation_status(), ensure_ascii=False, indent=2))
    sys.exit(0)

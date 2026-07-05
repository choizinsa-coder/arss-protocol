#!/usr/bin/env python3
"""
area_14_shadow_sim.py v1.1.0
AIF Area 14: Shadow Simulation (meta+Interlock)
EAG: EAG-S328-AIF-AREA14-P2-001

Phase 1: Shadow Run record + Interlock rule record + check_interlock (read-only).
Phase 2: run_simulation_llm (Domi LLM via 8448/ask). auto-interlock/dep-map placeholders.
Pattern: area_7_org_learning.py (class, log_dir override, 2 jsonl, append-only)
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import re
import urllib.request
import urllib.error

VERSION = "1.1.0"
EAG_ID  = "EAG-S328-AIF-AREA14-P2-001"

LLM_TIMEOUT = 125
DOMI_ASK_URL = "http://127.0.0.1:8448/ask"

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
            "event_type":        "rule",
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

    def run_simulation_llm(self, scenario_id: str, session: str, actor: str = "system") -> dict:
        """Phase 2: LLM-based shadow simulation via Domi (EAG-S328-AIF-AREA14-P2-001).

        Calls Domi 8448/ask with scenario data, parses JSON response,
        records new shadow run with [LLM_SIM] prefix.
        """
        runs = self._load_shadow_runs()
        latest = None
        for r in reversed(runs):
            if r.get("scenario_id") == scenario_id.strip():
                latest = r
                break
        if latest is None:
            raise ShadowSimError("No shadow run for scenario: " + repr(scenario_id))
        desc = latest.get("description", "")
        tgt  = latest.get("target_area", "")
        risk = latest.get("risk_level", "LOW")
        prompt = (
            "Simulate: scenario_id=" + scenario_id
            + " desc=" + desc + " tgt=" + tgt + " risk=" + risk
            + ". Respond JSON only: predicted_outcome, risk_level, confidence, reasoning."
        )
        body = json.dumps({
            "prompt": prompt, "context": "shadow_simulation",
            "session": session, "escalate": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            DOMI_ASK_URL, data=body,
            headers={"Content-Type": "application/json",
                     "Content-Length": str(len(body))},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                rdata = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ShadowSimError("Domi LLM unreachable: " + str(e))
        text = rdata.get("text", "") if isinstance(rdata, dict) else ""
        parsed = None
        if text:
            _m = re.search(r"{.*?}", text, re.DOTALL)
            if _m:
                try:
                    parsed = json.loads(_m.group(0))
                except json.JSONDecodeError:
                    parsed = None
        if parsed:
            po = parsed.get("predicted_outcome", latest.get("predicted_outcome", "uncertain"))
            rl = parsed.get("risk_level", latest.get("risk_level", "LOW"))
            try:
                cf = max(0.0, min(1.0, float(parsed.get("confidence", latest.get("confidence", 0.5)))))
            except (ValueError, TypeError):
                cf = latest.get("confidence", 0.5)
            if po not in VALID_PREDICTED_OUTCOMES:
                po = latest.get("predicted_outcome", "uncertain")
            if rl not in VALID_RISK_LEVELS:
                rl = latest.get("risk_level", "LOW")
            reasoning = str(parsed.get("reasoning", ""))
        else:
            po = latest.get("predicted_outcome", "uncertain")
            rl = latest.get("risk_level", "LOW")
            cf = latest.get("confidence", 0.5)
            reasoning = "parse_failed"
        entry = self.record_shadow_run(
            scenario_id=scenario_id,
            description="[LLM_SIM] " + latest.get("description", ""),
            target_area=latest.get("target_area", ""),
            predicted_outcome=po,
            risk_level=rl,
            confidence=cf,
            actor=actor,
        )
        entry["source"] = "llm_simulation"
        entry["llm_session"] = session
        entry["reasoning"] = reasoning
        return entry

    def _auto_engage_interlock(self, area_name: str, actor: str = "shadow_sim") -> Optional[str]:
        """Phase 2: Automatic interlock enforcement — actual area blocking."""
        area = str(area_name).strip()
        if not area:
            raise ShadowSimError("required field missing: area_name")
        if area in self.get_blocked_areas():
            return None
        rule_ids = [
            r.get("rule_id", r.get("id", ""))
            for r in self._load_interlock_rules()
            if r.get("event_type", "rule") == "rule" and r.get("blocked_area") == area
        ]
        now = datetime.now(timezone.utc)
        entry = {
            "schema":      "interlock_event_v1",
            "version":     VERSION,
            "id":          "BLK-" + str(uuid.uuid4()),
            "event_type":  "block",
            "area_name":   area,
            "rule_ids":    rule_ids,
            "reason":      "Auto interlock: " + str(len(rule_ids)) + " rule(s)",
            "actor":       str(actor).strip(),
            "recorded_at": now.isoformat(),
            "eag":         EAG_ID,
        }
        self._ensure_dir()
        with open(self._interlock_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
        return entry["id"]

    def get_blocked_areas(self) -> list:
        """Return sorted list of currently blocked areas. Latest event wins."""
        rules = self._load_interlock_rules()
        events = [
            r for r in rules
            if r.get("event_type") in ("block", "unblock")
            and r.get("area_name")
            and r.get("recorded_at")
        ]
        latest_state = {}
        latest_time = {}
        for ev in events:
            a_n = ev["area_name"]
            ts = ev["recorded_at"]
            if a_n not in latest_time or ts >= latest_time[a_n]:
                latest_time[a_n] = ts
                latest_state[a_n] = ev["event_type"]
        return sorted([a for a, s in latest_state.items() if s == "block"])

    def unblock_area(self, area_name: str, actor: str = "beo", eag_id: str = "") -> Optional[str]:
        """Append an unblock event. EAG recovery only; no auto-resume."""
        area = str(area_name).strip()
        if not area:
            raise ShadowSimError("required field missing: area_name")
        if area not in self.get_blocked_areas():
            return None
        now = datetime.now(timezone.utc)
        entry = {
            "schema":      "interlock_event_v1",
            "version":     VERSION,
            "id":          "UNB-" + str(uuid.uuid4()),
            "event_type":  "unblock",
            "area_name":   area,
            "reason":      eag_id or "manual unblock",
            "actor":       str(actor).strip(),
            "eag_id":      eag_id,
            "recorded_at": now.isoformat(),
            "eag":         EAG_ID,
        }
        self._ensure_dir()
        with open(self._interlock_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
        return entry["id"]

    def build_dependency_map(self) -> dict:
        """Phase 2: Cross-area Dependency Map."""
        rules = self._load_interlock_rules()
        interlock_rules = [r for r in rules if r.get("event_type", "rule") == "rule"]
        runs = self._load_shadow_runs()
        blocked = set(self.get_blocked_areas())
        areas = set()
        for r in interlock_rules:
            if r.get("trigger_area"):
                areas.add(r["trigger_area"])
            if r.get("blocked_area"):
                areas.add(r["blocked_area"])
        for run in runs:
            if run.get("target_area"):
                areas.add(run["target_area"])
        latest_run = {}
        run_count = {}
        for run in runs:
            ta = run.get("target_area")
            if not ta:
                continue
            run_count[ta] = run_count.get(ta, 0) + 1
            ts = run.get("recorded_at", "")
            if ta not in latest_run or ts >= latest_run[ta].get("recorded_at", ""):
                latest_run[ta] = run
        nodes = []
        for a in sorted(areas):
            lr = latest_run.get(a, {})
            nodes.append({
                "area_name":         a,
                "blocked":           a in blocked,
                "risk_level":        lr.get("risk_level", "unknown"),
                "predicted_outcome": lr.get("predicted_outcome", "unknown"),
                "confidence":        lr.get("confidence"),
                "total_runs":        run_count.get(a, 0),
            })
        edge_map = {}
        for r in interlock_rules:
            src_a = r.get("trigger_area")
            tgt_a = r.get("blocked_area")
            if not src_a or not tgt_a:
                continue
            key = src_a + ">" + tgt_a
            if key not in edge_map:
                edge_map[key] = {
                    "source":            src_a,
                    "target":            tgt_a,
                    "type":              "interlock",
                    "trigger_condition": r.get("trigger_condition", ""),
                    "reason":            r.get("reason", ""),
                    "weight":            0,
                }
            edge_map[key]["weight"] += 1
        edges = list(edge_map.values())
        cycles = self._detect_cycles(edges)
        return {
            "schema":       "dependency_map_v1",
            "version":      VERSION,
            "eag":          EAG_ID,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes":        nodes,
            "edges":        edges,
            "cycles":       cycles,
            "stats": {
                "total_nodes":   len(nodes),
                "total_edges":   len(edges),
                "cycle_count":   len(cycles),
                "blocked_nodes": len(blocked),
            },
        }

    def _detect_cycles(self, edges: list) -> list:
        """Detect directed cycles via DFS. Returns list of node-path lists."""
        adj = {}
        for e in edges:
            adj.setdefault(e["source"], []).append(e["target"])
            adj.setdefault(e["target"], [])
        visited = set()
        rec = []
        cycles = []
        seen = set()

        def _dfs(node):
            visited.add(node)
            rec.append(node)
            for nb in adj.get(node, []):
                if nb not in visited:
                    _dfs(nb)
                elif nb in rec:
                    idx = rec.index(nb)
                    cyc = rec[idx:] + [nb]
                    key = frozenset(cyc)
                    if key not in seen:
                        seen.add(key)
                        cycles.append(cyc)
            rec.pop()

        for n in list(adj.keys()):
            if n not in visited:
                _dfs(n)
        return cycles


if __name__ == "__main__":
    import sys
    engine = ShadowSimEngine()
    print(json.dumps(engine.get_simulation_status(), ensure_ascii=False, indent=2))
    sys.exit(0)

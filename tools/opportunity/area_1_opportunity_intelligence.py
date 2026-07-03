#!/usr/bin/env python3
"""
area_1_opportunity_intelligence.py v1.0.0
AIF Area 1: Trust-Bound Opportunity Intelligence Engine (Phase 1 MVKG)
EAG: EAG-S323-AIF-AREA1-001

Phase 1 scope:
  Evidence / Assumption / Opportunity nodes + Opportunity Score engine.
  Signal Verification Gate, Pre-Mortem Gate, Differential EAG = Phase 2 placeholder.
  Counter-Hypothesis Loop, Belief Revision propagation = Phase 2 placeholder.

Pattern: area_15_failure_memory.py (append-only jsonl, validate -> entry -> append).
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S323-AIF-AREA1-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "opportunity"

REVERSIBILITY_PENALTY: dict = {"HIGH": 1.0, "MEDIUM": 1.5, "LOW": 2.0}
VALID_REVERSIBILITY   = frozenset({"HIGH", "MEDIUM", "LOW"})
VALID_STATUS          = frozenset({"active", "stale", "quarantine", "retired"})


class OpportunityError(ValueError):
    """AIF Area 1 validation error."""
    pass


class OpportunityIntelligenceEngine:
    """
    AIF Area 1 - Trust-Bound Opportunity Intelligence Engine.
    Phase 1 MVKG: Evidence / Assumption / Opportunity nodes (3 types).
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir         = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._evidence_log    = self._log_dir / "evidence_log.jsonl"
        self._assumption_log  = self._log_dir / "assumption_log.jsonl"
        self._opportunity_log = self._log_dir / "opportunity_log.jsonl"

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    # --- Evidence ---

    def record_evidence(
        self,
        content: str,
        evidence_confidence: float,
        inference_confidence: float,
        source: str,
        ttl_days: int = 30,
        actor: str = "system",
    ) -> dict:
        """
        Appends Evidence node to evidence_log.jsonl.
        id: E-{uuid4}, source_hash: SHA-256(content), expires_at: now+ttl_days.
        """
        if not content or not str(content).strip():
            raise OpportunityError("required field missing: 'content'")
        if not source or not str(source).strip():
            raise OpportunityError("required field missing: 'source'")
        if not (0.0 <= evidence_confidence <= 1.0):
            raise OpportunityError(
                f"evidence_confidence must be 0.0~1.0, got {evidence_confidence}"
            )
        if not (0.0 <= inference_confidence <= 1.0):
            raise OpportunityError(
                f"inference_confidence must be 0.0~1.0, got {inference_confidence}"
            )
        if ttl_days <= 0:
            raise OpportunityError(f"ttl_days must be positive, got {ttl_days}")

        now         = datetime.now(timezone.utc)
        source_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        entry = {
            "schema":               "evidence_v1",
            "version":              VERSION,
            "id":                   f"E-{uuid.uuid4()}",
            "content":              content.strip(),
            "source":               source.strip(),
            "source_hash":          source_hash,
            "evidence_confidence":  round(evidence_confidence, 4),
            "inference_confidence": round(inference_confidence, 4),
            "ttl_days":             ttl_days,
            "expires_at":           (now + timedelta(days=ttl_days)).isoformat(),
            "actor":                actor.strip(),
            "recorded_at":          now.isoformat(),
        }
        self._ensure_dir()
        with open(self._evidence_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_evidence(self) -> list:
        if not self._evidence_log.exists():
            return []
        entries: list = []
        with open(self._evidence_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Assumption ---

    def record_assumption(
        self,
        content: str,
        confidence: float,
        ttl_days: int = 30,
        depends_on: Optional[List[str]] = None,
        vev_declared: bool = False,
        actor: str = "system",
    ) -> dict:
        """
        Appends Assumption node to assumption_log.jsonl.
        id: A-{uuid4}, depends_on: stored only (propagation Phase 2).
        belief_revision_events: [] Phase 1 placeholder.
        """
        if not content or not str(content).strip():
            raise OpportunityError("required field missing: 'content'")
        if not (0.0 <= confidence <= 1.0):
            raise OpportunityError(
                f"confidence must be 0.0~1.0, got {confidence}"
            )
        if ttl_days <= 0:
            raise OpportunityError(f"ttl_days must be positive, got {ttl_days}")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":                 "assumption_v1",
            "version":                VERSION,
            "id":                     f"A-{uuid.uuid4()}",
            "content":                content.strip(),
            "confidence":             round(confidence, 4),
            "ttl_days":               ttl_days,
            "expires_at":             (now + timedelta(days=ttl_days)).isoformat(),
            "depends_on":             depends_on or [],
            "vev_declared":           vev_declared,
            "belief_revision_events": [],
            "actor":                  actor.strip(),
            "recorded_at":            now.isoformat(),
        }
        self._ensure_dir()
        with open(self._assumption_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_assumptions(self) -> list:
        if not self._assumption_log.exists():
            return []
        entries: list = []
        with open(self._assumption_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Opportunity Score ---

    def calculate_opportunity_score(
        self,
        expected_value: float,
        evidence_ids: List[str],
        assumption_ids: List[str],
        strategic_alignment: float,
        wrong_cost_factor: float,
        reversibility: str,
        validate_cost: float = 1.0,
        operational_alignment: float = 1.0,
        capability_fit: float = 1.0,
    ) -> float:
        """
        Score = (EV * avg_ec * avg_ic * freshness * SA * OA * CF)
                / (validate_cost * WCF * reversibility_penalty)
        Phase 1: OA=1.0 fixed, CF=1.0 fixed.
        freshness = fraction of linked Evidence where expires_at > now.
        No linked evidence: avg_ec=0.5, avg_ic=0.5, freshness=1.0.
        Result: round(..., 4), min 0.0.
        """
        if reversibility not in VALID_REVERSIBILITY:
            raise OpportunityError(
                f"reversibility must be one of {sorted(VALID_REVERSIBILITY)}, got {reversibility!r}"
            )
        if not (0.0 <= strategic_alignment <= 1.0):
            raise OpportunityError(
                f"strategic_alignment must be 0.0~1.0, got {strategic_alignment}"
            )
        if wrong_cost_factor < 1.0:
            raise OpportunityError(
                f"wrong_cost_factor must be >= 1.0, got {wrong_cost_factor}"
            )
        if validate_cost <= 0.0:
            raise OpportunityError(f"validate_cost must be > 0, got {validate_cost}")

        ev_index = {e["id"]: e for e in self._load_evidence()}
        linked   = [ev_index[eid] for eid in evidence_ids if eid in ev_index]
        now      = datetime.now(timezone.utc)

        if linked:
            avg_ec = sum(e["evidence_confidence"]  for e in linked) / len(linked)
            avg_ic = sum(e["inference_confidence"] for e in linked) / len(linked)
            fresh  = sum(
                1 for e in linked
                if datetime.fromisoformat(e["expires_at"]) > now
            ) / len(linked)
        else:
            avg_ec = 0.5
            avg_ic = 0.5
            fresh  = 1.0

        rp    = REVERSIBILITY_PENALTY[reversibility]
        numer = (
            expected_value * avg_ec * avg_ic * fresh
            * strategic_alignment * operational_alignment * capability_fit
        )
        denom = validate_cost * wrong_cost_factor * rp
        score = numer / denom if denom != 0 else 0.0
        return round(max(score, 0.0), 4)

    # --- Opportunity ---

    def record_opportunity(
        self,
        title: str,
        evidence_ids: List[str],
        assumption_ids: List[str],
        strategic_alignment: float,
        wrong_cost_factor: float,
        reversibility: str,
        expected_value: float = 1.0,
        actor: str = "system",
    ) -> dict:
        """
        Auto-calculates Opportunity Score and appends to opportunity_log.jsonl.
        id: OP-{uuid4}, status: active.
        Phase 2 placeholders: signal_verification_gate, pre_mortem_gate, differential_eag.
        """
        if not title or not str(title).strip():
            raise OpportunityError("required field missing: 'title'")

        score = self.calculate_opportunity_score(
            expected_value      = expected_value,
            evidence_ids        = evidence_ids,
            assumption_ids      = assumption_ids,
            strategic_alignment = strategic_alignment,
            wrong_cost_factor   = wrong_cost_factor,
            reversibility       = reversibility,
        )
        now = datetime.now(timezone.utc)
        entry = {
            "schema":                   "opportunity_v1",
            "version":                  VERSION,
            "id":                       f"OP-{uuid.uuid4()}",
            "title":                    title.strip(),
            "evidence_ids":             evidence_ids,
            "assumption_ids":           assumption_ids,
            "expected_value":           expected_value,
            "strategic_alignment":      strategic_alignment,
            "wrong_cost_factor":        wrong_cost_factor,
            "reversibility":            reversibility,
            "score":                    score,
            "status":                   "active",
            "signal_verification_gate": None,
            "pre_mortem_gate":          None,
            "differential_eag":         None,
            "actor":                    actor.strip(),
            "recorded_at":              now.isoformat(),
        }
        self._ensure_dir()
        with open(self._opportunity_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def _load_opportunities(self) -> list:
        if not self._opportunity_log.exists():
            return []
        entries: list = []
        with open(self._opportunity_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Query ---

    def get_active_opportunities(self, min_score: float = 0.0) -> list:
        """Returns status='active' Opportunities with score >= min_score, newest first."""
        all_ops  = self._load_opportunities()
        filtered = [
            op for op in all_ops
            if op.get("status") == "active" and op.get("score", 0.0) >= min_score
        ]
        return list(reversed(filtered))

    def get_evidence_summary(self) -> dict:
        """Total count, active/expired classification, recent 5."""
        all_entries   = self._load_evidence()
        now           = datetime.now(timezone.utc)
        active_count  = 0
        expired_count = 0
        for e in all_entries:
            try:
                exp = datetime.fromisoformat(e["expires_at"])
                if exp > now:
                    active_count  += 1
                else:
                    expired_count += 1
            except (KeyError, ValueError):
                expired_count += 1
        return {
            "schema":        "evidence_summary_v1",
            "version":       VERSION,
            "eag":           EAG_ID,
            "total_count":   len(all_entries),
            "active_count":  active_count,
            "expired_count": expired_count,
            "recent_5":      list(reversed(all_entries[-5:])) if all_entries else [],
            "log_path":      str(self._evidence_log),
        }

    def get_assumption_summary(self) -> dict:
        """Total count, active/invalidated classification."""
        all_entries   = self._load_assumptions()
        now           = datetime.now(timezone.utc)
        active_count  = 0
        invalid_count = 0
        for a in all_entries:
            try:
                exp = datetime.fromisoformat(a["expires_at"])
                if exp > now:
                    active_count  += 1
                else:
                    invalid_count += 1
            except (KeyError, ValueError):
                invalid_count += 1
        return {
            "schema":            "assumption_summary_v1",
            "version":           VERSION,
            "eag":               EAG_ID,
            "total_count":       len(all_entries),
            "active_count":      active_count,
            "invalidated_count": invalid_count,
            "log_path":          str(self._assumption_log),
        }


if __name__ == "__main__":
    import sys
    engine = OpportunityIntelligenceEngine()
    print(json.dumps(engine.get_evidence_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

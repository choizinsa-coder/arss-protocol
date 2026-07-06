#!/usr/bin/env python3
"""
area_1_opportunity_intelligence.py v1.1.0
AIF Area 1: Trust-Bound Opportunity Intelligence Engine (Phase 1 MVKG)
EAG: EAG-S323-AIF-AREA1-001

Phase 1 scope:
  Evidence / Assumption / Opportunity nodes + Opportunity Score engine.
  Signal Verification Gate: verify_signal() (EAG-S327-AIF-AREA1-P2-001).
  Pre-Mortem Gate: run_pre_mortem() (EAG-S327-AIF-AREA1-P2-001).
  Differential EAG = Phase 3 placeholder.
  Counter-Hypothesis Loop, Belief Revision propagation = Phase 2 placeholder.

Pattern: area_15_failure_memory.py (append-only jsonl, validate -> entry -> append).
"""
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

VERSION = "1.1.0"
EAG_ID    = "EAG-S323-AIF-AREA1-001"
EAG_ID_P2 = "EAG-S327-AIF-AREA1-P2-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "opportunity"

REVERSIBILITY_PENALTY: dict = {"HIGH": 1.0, "MEDIUM": 1.5, "LOW": 2.0}
VALID_REVERSIBILITY   = frozenset({"HIGH", "MEDIUM", "LOW"})
VALID_STATUS          = frozenset({"active", "stale", "quarantine", "retired", "rejected"})
VALID_SIGNAL_SOURCES  = frozenset({"evidence", "assumption", "external", "review"})


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
        self._opportunity_log     = self._log_dir / "opportunity_log.jsonl"
        self._signal_verify_log   = self._log_dir / "signal_verification_log.jsonl"
        self._pre_mortem_log      = self._log_dir / "pre_mortem_log.jsonl"

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

    # --- Phase 2: Signal Verification Gate ---

    def verify_signal(
        self,
        opportunity_id: str,
        signal_source: str,
        signal_confidence: float,
        actor: str = "system",
    ) -> dict:
        """
        Signal Verification Gate.
        signal_source: evidence|assumption|external|review.
        verdict: VERIFIED (>= 0.7) / UNVERIFIED (< 0.7).
        Appends to signal_verification_log.jsonl (id: SV-{uuid4}).
        Updates opportunity_log.jsonl signal_verification_gate field (append-only).
        EAG: EAG-S327-AIF-AREA1-P2-001
        """
        if not opportunity_id or not str(opportunity_id).strip():
            raise OpportunityError("required field missing: opportunity_id")
        if signal_source not in VALID_SIGNAL_SOURCES:
            raise OpportunityError(
                f"signal_source must be one of {sorted(VALID_SIGNAL_SOURCES)}, got {signal_source!r}"
            )
        if not isinstance(signal_confidence, (int, float)):
            raise OpportunityError("signal_confidence must be a float")
        signal_confidence = float(signal_confidence)
        if not (0.0 <= signal_confidence <= 1.0):
            raise OpportunityError(
                f"signal_confidence must be 0.0~1.0, got {signal_confidence}"
            )
        verdict = "VERIFIED" if signal_confidence >= 0.7 else "UNVERIFIED"
        now = datetime.now(timezone.utc)
        sv_entry = {
            "schema":             "signal_verification_v1",
            "version":            VERSION,
            "id":                 f"SV-{uuid.uuid4()}",
            "opportunity_id":     opportunity_id.strip(),
            "signal_source":      signal_source,
            "signal_confidence":  round(signal_confidence, 4),
            "verdict":            verdict,
            "actor":              actor.strip(),
            "recorded_at":        now.isoformat(),
            "eag":                EAG_ID_P2,
        }
        self._ensure_dir()
        with open(self._signal_verify_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(sv_entry, ensure_ascii=False) + "\n")
        # Update opportunity entry (append-only: re-append with updated field)
        all_ops = self._load_opportunities()
        matched = None
        for op in reversed(all_ops):
            if op.get("id") == opportunity_id.strip():
                matched = dict(op)
                break
        if matched:
            matched["signal_verification_gate"] = sv_entry
            matched["recorded_at"] = now.isoformat()
            with open(self._opportunity_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(matched, ensure_ascii=False) + "\n")
        return sv_entry

    # --- Phase 2: Pre-Mortem Gate ---

    def run_pre_mortem(
        self,
        opportunity_id: str,
        failure_scenarios: List[str],
        actor: str = "system",
    ) -> dict:
        """
        Pre-Mortem Gate. Failure scenario analysis.
        failure_scenarios: List[str], 1 or more required.
        risk_level: HIGH (>= 3) / MEDIUM (2) / LOW (1).
        Appends to pre_mortem_log.jsonl (id: PM-{uuid4}).
        Updates opportunity_log.jsonl pre_mortem_gate field (append-only).
        EAG: EAG-S327-AIF-AREA1-P2-001
        """
        if not opportunity_id or not str(opportunity_id).strip():
            raise OpportunityError("required field missing: opportunity_id")
        if not failure_scenarios or not isinstance(failure_scenarios, list):
            raise OpportunityError("failure_scenarios must be a non-empty list")
        if len(failure_scenarios) < 1:
            raise OpportunityError("at least one failure_scenario is required")
        n = len(failure_scenarios)
        if n >= 3:
            risk_level = "HIGH"
        elif n == 2:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"
        now = datetime.now(timezone.utc)
        pm_entry = {
            "schema":             "pre_mortem_v1",
            "version":            VERSION,
            "id":                 f"PM-{uuid.uuid4()}",
            "opportunity_id":     opportunity_id.strip(),
            "failure_scenarios":  [s.strip() for s in failure_scenarios if s.strip()],
            "risk_level":         risk_level,
            "actor":              actor.strip(),
            "recorded_at":        now.isoformat(),
            "eag":                EAG_ID_P2,
        }
        self._ensure_dir()
        with open(self._pre_mortem_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(pm_entry, ensure_ascii=False) + "\n")
        # Update opportunity entry (append-only: re-append with updated field)
        all_ops = self._load_opportunities()
        matched = None
        for op in reversed(all_ops):
            if op.get("id") == opportunity_id.strip():
                matched = dict(op)
                break
        if matched:
            matched["pre_mortem_gate"] = pm_entry
            matched["recorded_at"] = now.isoformat()
            with open(self._opportunity_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(matched, ensure_ascii=False) + "\n")
        return pm_entry

    # --- Phase 2: Counter-Hypothesis Loop ---

    def reject_opportunity(
        self,
        opportunity_id: str,
        shattering_trigger_assumption_ids: List[str],
        reason: str,
        actor: str = "system",
    ) -> dict:
        """
        Counter-Hypothesis Loop (Section 4.8). Opportunity를 'rejected' 상태로 전환.
        shattering_trigger_assumption_ids: 이 가정(들)이 무너지면 재활성화 대상.
        append-only + last-wins(reversed 순회 후 첫 매치) 원칙 준수.
        EAG: EAG-S346-AIF-AREA1-COUNTERHYPO-001
        """
        if not opportunity_id or not str(opportunity_id).strip():
            raise OpportunityError("required field missing: opportunity_id")
        if not reason or not str(reason).strip():
            raise OpportunityError("required field missing: reason")

        all_ops = self._load_opportunities()
        target = None
        for entry in reversed(all_ops):
            if entry.get("id") == opportunity_id:
                target = entry
                break
        if target is None:
            raise OpportunityError(f"Opportunity not found: {opportunity_id}")
        if target.get("status") == "rejected":
            raise OpportunityError(f"Opportunity already rejected: {opportunity_id}")

        now = datetime.now(timezone.utc).isoformat()
        rejected_entry = dict(target)
        rejected_entry.update({
            "status": "rejected",
            "shattering_trigger_assumption_ids": list(shattering_trigger_assumption_ids),
            "rejected_reason": reason.strip(),
            "rejected_at": now,
            "rejected_by": actor.strip(),
        })
        self._ensure_dir()
        with open(self._opportunity_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(rejected_entry, ensure_ascii=False) + "\n")
        return rejected_entry

    def check_counter_hypothesis(
        self,
        assumption_id: str,
        new_confidence: float,
        threshold: float = 0.3,
    ) -> list:
        """
        Counter-Hypothesis Loop (Section 4.8). assumption의 confidence가
        threshold 미만으로 떨어지면, 이를 shattering_trigger로 등록한
        'rejected' 상태 Opportunity들을 자동 재활성화('active').
        2-pass last-wins: (1) id별 최신 entry 수집 (2) 조건 만족분만 재활성화.
        EAG: EAG-S346-AIF-AREA1-COUNTERHYPO-001
        """
        if new_confidence >= threshold:
            return []

        all_ops = self._load_opportunities()
        latest_ops: dict = {}
        for entry in reversed(all_ops):
            eid = entry.get("id")
            if eid and eid not in latest_ops:
                latest_ops[eid] = entry

        triggered_ids = []
        for eid, entry in latest_ops.items():
            if entry.get("status") != "rejected":
                continue
            triggers = entry.get("shattering_trigger_assumption_ids", [])
            if assumption_id in triggers:
                triggered_ids.append(eid)
        if not triggered_ids:
            return []

        now = datetime.now(timezone.utc).isoformat()
        reactivated = []
        for eid in triggered_ids:
            target = latest_ops[eid]
            reactivated_entry = dict(target)
            reactivated_entry.update({
                "status": "active",
                "reactivated_at": now,
                "reactivated_by": "counter_hypothesis",
                "reactivation_trigger_assumption_id": assumption_id,
            })
            self._ensure_dir()
            with open(self._opportunity_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(reactivated_entry, ensure_ascii=False) + "\n")
            reactivated.append(reactivated_entry)
        return reactivated

    # --- Phase 2: Belief Revision Propagation ---

    def record_belief_revision(
        self,
        assumption_id: str,
        new_confidence: float,
        reason: str,
        evidence_ref: Optional[str] = None,
        actor: str = "system",
    ) -> dict:
        """
        Assumption Graph - Belief Revision (Section 4.4). append-only,
        reject_opportunity()와 동일 패턴. 기존 줄 덮어쓰기/삭제 없음.
        confidence 하락시에만 depends_on 그래프를 따라 비대칭 하향 전파.
        EAG: EAG-S346-AIF-AREA1-BELIEFREVISION-001
        """
        all_entries = self._load_assumptions()
        target = None
        for entry in reversed(all_entries):
            if entry.get("id") == assumption_id:
                target = entry
                break
        if target is None:
            raise OpportunityError(f"Assumption not found: {assumption_id}")

        previous_confidence = target.get("confidence", 0.0)
        if not (0.0 <= new_confidence <= 1.0):
            raise OpportunityError(
                f"new_confidence must be in [0.0, 1.0], got {new_confidence}"
            )

        now = datetime.now(timezone.utc).isoformat()
        revised_entry = dict(target)
        revised_entry["confidence"] = new_confidence
        revised_entry["revised_at"] = now
        revised_entry["revised_by"] = actor.strip()

        events = list(revised_entry.get("belief_revision_events", []))
        events.append({
            "revised_at": now,
            "previous_confidence": previous_confidence,
            "new_confidence": new_confidence,
            "reason": reason.strip(),
            "evidence_ref": evidence_ref.strip() if evidence_ref else evidence_ref,
        })
        revised_entry["belief_revision_events"] = events

        if new_confidence < previous_confidence:
            self._propagate_revision_downward(
                revised_entry, new_confidence, reason, evidence_ref, actor, _depth=0
            )

        self._ensure_dir()
        with open(self._assumption_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(revised_entry, ensure_ascii=False) + "\n")

        return {
            "assumption_id": assumption_id,
            "previous_confidence": previous_confidence,
            "new_confidence": new_confidence,
            "revised_at": now,
            "propagated": new_confidence < previous_confidence,
        }

    def _propagate_revision_downward(
        self,
        entry: dict,
        new_confidence: float,
        reason: str,
        evidence_ref: Optional[str],
        actor: str,
        _depth: int = 0,
    ) -> None:
        """
        depends_on 그래프 역방향 탐색: entry에 의존하는(depends_on에 entry.id 포함)
        하위 노드들을 찾아 confidence를 min()으로 재계산(비대칭, 하락시만).
        MAX_DEPTH=5로 순환참조/무한재귀 방지.
        """
        MAX_DEPTH = 5
        if _depth >= MAX_DEPTH:
            return

        all_entries = self._load_assumptions()
        latest_map: dict = {}
        for e in reversed(all_entries):
            eid = e.get("id")
            if eid and eid not in latest_map:
                latest_map[eid] = e

        entry_id = entry.get("id")
        dependent_ids = [
            eid for eid, e in latest_map.items()
            if entry_id in e.get("depends_on", []) and eid != entry_id
        ]

        for dep_id in dependent_ids:
            dep_target = latest_map[dep_id]
            dep_prev = dep_target.get("confidence", 0.0)
            dep_new = min(dep_prev, new_confidence)
            if dep_new >= dep_prev:
                continue

            now = datetime.now(timezone.utc).isoformat()
            revised_dep = dict(dep_target)
            revised_dep["confidence"] = dep_new
            revised_dep["revised_at"] = now
            revised_dep["revised_by"] = actor.strip()

            dep_events = list(revised_dep.get("belief_revision_events", []))
            dep_events.append({
                "revised_at": now,
                "previous_confidence": dep_prev,
                "new_confidence": dep_new,
                "reason": f"[propagated] {reason.strip()}",
                "evidence_ref": evidence_ref.strip() if evidence_ref else evidence_ref,
            })
            revised_dep["belief_revision_events"] = dep_events

            self._ensure_dir()
            with open(self._assumption_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(revised_dep, ensure_ascii=False) + "\n")

            self._propagate_revision_downward(
                revised_dep, dep_new, reason, evidence_ref, actor, _depth=_depth + 1
            )

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
        """Total count, active/invalidated classification. id-기준 last-wins 보정(append-only 중복집계 방지)."""
        all_entries = self._load_assumptions()
        now         = datetime.now(timezone.utc)

        latest_map: dict = {}
        for e in reversed(all_entries):
            eid = e.get("id")
            if eid and eid not in latest_map:
                latest_map[eid] = e

        active_count  = 0
        invalid_count = 0
        for a in latest_map.values():
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
            "total_count":       len(latest_map),
            "active_count":      active_count,
            "invalidated_count": invalid_count,
            "log_path":          str(self._assumption_log),
        }


if __name__ == "__main__":
    import sys
    engine = OpportunityIntelligenceEngine()
    print(json.dumps(engine.get_evidence_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

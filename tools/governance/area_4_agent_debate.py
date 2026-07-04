#!/usr/bin/env python3
"""
area_4_agent_debate.py v1.1.0
AIF Area 4: Agent Debate Protocol (에이전트 간 토론)
EAG: EAG-S324-AIF-AREA4-001

Phase 1: open_debate / record_position / record_round_result / close_debate
         get_debate_summary / get_open_debates
         append-only 상태 추적 (type='open'/'round_result'/'close')

Phase 2 (EAG-S327-AIF-AREA4-P2-001): link_wf05_workitem (WF-05 연동, append-only).
Phase 3 placeholders: 자동 합의 판정, Area 11 양방향 연결.

Pattern: area_7_org_learning.py (class, log_dir override, 2 jsonl)
"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

VERSION = "1.1.0"
EAG_ID    = "EAG-S324-AIF-AREA4-001"
EAG_ID_P2 = "EAG-S327-AIF-AREA4-P2-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "governance"

VALID_AGENTS         = frozenset({"domi", "jeni", "caddy", "beo"})
VALID_POSITION_TYPES = frozenset({"support", "oppose", "neutral", "conditional"})
VALID_OUTCOMES       = frozenset({"consensus", "no_consensus", "deferred", "beo_decision"})


class DebateError(ValueError):
    """AIF Area 4 validation error."""
    pass


class AgentDebateEngine:
    """
    AIF Area 4 - Agent Debate Protocol.
    Phase 1: open / record positions / record rounds / close (append-only).
    State tracked via type='open'+'close' entries in debate_log.jsonl.
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir      = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._debate_log   = self._log_dir / "debate_log.jsonl"
        self._position_log = self._log_dir / "position_log.jsonl"

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _load_debates(self) -> list:
        """Load all raw entries from debate_log.jsonl."""
        if not self._debate_log.exists():
            return []
        entries: list = []
        with open(self._debate_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _load_positions(self) -> list:
        """Load all raw entries from position_log.jsonl."""
        if not self._position_log.exists():
            return []
        entries: list = []
        with open(self._position_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    def _get_debate_status(self, debate_id: str) -> Optional[str]:
        """Returns 'open', 'closed', or None (not found) for debate_id."""
        found_open  = False
        found_close = False
        for d in self._load_debates():
            if d.get("id") == debate_id:
                if d.get("type") == "open":
                    found_open  = True
                elif d.get("type") == "close":
                    found_close = True
        if not found_open:
            return None
        return "closed" if found_close else "open"

    def _get_open_entry(self, debate_id: str) -> Optional[dict]:
        """Returns the type='open' entry for debate_id."""
        for d in self._load_debates():
            if d.get("id") == debate_id and d.get("type") == "open":
                return d
        return None

    # --- Core methods ---

    def open_debate(
        self,
        topic_id: str,
        topic_title: str,
        initiator: str,
        actor: str = "system",
    ) -> dict:
        """
        Opens a new debate topic.
        id: DEB-{uuid4}, type: 'open', status: 'open'.
        """
        if initiator not in VALID_AGENTS:
            raise DebateError(
                f"initiator must be one of {sorted(VALID_AGENTS)}, got {initiator!r}"
            )
        if not topic_id or not str(topic_id).strip():
            raise DebateError("required field missing: 'topic_id'")
        if not topic_title or not str(topic_title).strip():
            raise DebateError("required field missing: 'topic_title'")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":      "debate_log_v1",
            "version":     VERSION,
            "id":          f"DEB-{uuid.uuid4()}",
            "type":        "open",
            "topic_id":    topic_id.strip(),
            "topic_title": topic_title.strip(),
            "initiator":   initiator,
            "status":      "open",
            "actor":       actor.strip(),
            "opened_at":   now.isoformat(),
            "eag":         EAG_ID,
        }
        self._ensure_dir()
        with open(self._debate_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def record_position(
        self,
        debate_id: str,
        agent: str,
        position_type: str,
        content: str,
        confidence: float,
        actor: str = "system",
    ) -> dict:
        """
        Records an agent's position on a debate.
        id: POS-{uuid4}, links to debate via debate_id.
        Raises DebateError if debate not found or already closed.
        """
        if agent not in VALID_AGENTS:
            raise DebateError(
                f"agent must be one of {sorted(VALID_AGENTS)}, got {agent!r}"
            )
        if position_type not in VALID_POSITION_TYPES:
            raise DebateError(
                f"position_type must be one of {sorted(VALID_POSITION_TYPES)}, got {position_type!r}"
            )
        if not content or not str(content).strip():
            raise DebateError("required field missing: 'content'")
        if not (0.0 <= confidence <= 1.0):
            raise DebateError(f"confidence must be 0.0~1.0, got {confidence}")

        status = self._get_debate_status(debate_id)
        if status is None:
            raise DebateError(f"debate not found: {debate_id!r}")
        if status == "closed":
            raise DebateError(f"debate {debate_id!r} is already closed")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":        "position_log_v1",
            "version":       VERSION,
            "id":            f"POS-{uuid.uuid4()}",
            "debate_id":     debate_id,
            "agent":         agent,
            "position_type": position_type,
            "content":       content.strip(),
            "confidence":    round(confidence, 4),
            "actor":         actor.strip(),
            "recorded_at":   now.isoformat(),
            "eag":           EAG_ID,
        }
        self._ensure_dir()
        with open(self._position_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def record_round_result(
        self,
        debate_id: str,
        round_number: int,
        summary: str,
        actor: str = "system",
    ) -> dict:
        """
        Records a round result for a debate.
        Appends type='round_result' entry to debate_log.jsonl.
        """
        if not isinstance(round_number, int) or round_number < 1:
            raise DebateError(f"round_number must be int >= 1, got {round_number!r}")
        if not summary or not str(summary).strip():
            raise DebateError("required field missing: 'summary'")

        status = self._get_debate_status(debate_id)
        if status is None:
            raise DebateError(f"debate not found: {debate_id!r}")
        if status == "closed":
            raise DebateError(f"debate {debate_id!r} is already closed")

        now = datetime.now(timezone.utc)
        entry = {
            "schema":       "debate_log_v1",
            "version":      VERSION,
            "id":           debate_id,
            "type":         "round_result",
            "round_number": round_number,
            "summary":      summary.strip(),
            "actor":        actor.strip(),
            "recorded_at":  now.isoformat(),
            "eag":          EAG_ID,
        }
        self._ensure_dir()
        with open(self._debate_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def close_debate(
        self,
        debate_id: str,
        outcome: str,
        consensus_level: float,
        decision_ref: Optional[str] = None,
        actor: str = "system",
    ) -> dict:
        """
        Closes a debate with final outcome.
        Appends type='close' entry to debate_log.jsonl.
        decision_ref: Area 11 Decision ID (external reference only, Phase 1).
        wf05_workitem: None (Phase 2 placeholder).
        """
        if outcome not in VALID_OUTCOMES:
            raise DebateError(
                f"outcome must be one of {sorted(VALID_OUTCOMES)}, got {outcome!r}"
            )
        if not (0.0 <= consensus_level <= 1.0):
            raise DebateError(f"consensus_level must be 0.0~1.0, got {consensus_level}")

        status = self._get_debate_status(debate_id)
        if status is None:
            raise DebateError(f"debate not found: {debate_id!r}")
        if status == "closed":
            raise DebateError(f"debate {debate_id!r} is already closed")

        open_entry = self._get_open_entry(debate_id)
        now = datetime.now(timezone.utc)
        entry = {
            "schema":          "debate_log_v1",
            "version":         VERSION,
            "id":              debate_id,
            "type":            "close",
            "status":          "closed",
            "topic_id":        open_entry.get("topic_id") if open_entry else None,
            "topic_title":     open_entry.get("topic_title") if open_entry else None,
            "outcome":         outcome,
            "consensus_level": round(consensus_level, 4),
            "decision_ref":    decision_ref,   # Phase 1: external ref only
            "wf05_workitem":   None,           # Phase 2 placeholder
            "actor":           actor.strip(),
            "closed_at":       now.isoformat(),
            "eag":             EAG_ID,
        }
        self._ensure_dir()
        with open(self._debate_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # --- Phase 2: WF-05 Workitem Link ---

    def link_wf05_workitem(
        self,
        debate_id: str,
        workitem_id: str,
        actor: str = "system",
    ) -> dict:
        """
        Links a WF-05 workitem to an existing close entry (append-only).
        Finds the latest close entry for debate_id, sets wf05_workitem,
        and appends updated entry to debate_log.jsonl.
        debate_id, workitem_id: both required.
        Raises DebateError if debate not found.
        EAG: EAG-S327-AIF-AREA4-P2-001
        """
        if not debate_id or not str(debate_id).strip():
            raise DebateError("required field missing: debate_id")
        if not workitem_id or not str(workitem_id).strip():
            raise DebateError("required field missing: workitem_id")
        # Find latest close entry for debate_id
        all_entries = self._load_debates()
        close_entry = None
        for e in reversed(all_entries):
            if e.get("id") == debate_id.strip() and e.get("type") == "close":
                close_entry = dict(e)
                break
        if close_entry is None:
            raise DebateError(
                f"no close entry found for debate_id {debate_id!r}")
        # Append updated close entry (append-only, wf05_workitem set)
        now = datetime.now(timezone.utc)
        close_entry["wf05_workitem"] = workitem_id.strip()
        close_entry["linked_at"]     = now.isoformat()
        close_entry["eag"]           = EAG_ID_P2
        self._ensure_dir()
        with open(self._debate_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(close_entry, ensure_ascii=False) + "\n")
        return close_entry

    # --- Query ---

    def get_open_debates(self) -> list:
        """Returns all debates without a 'close' entry."""
        all_debates = self._load_debates()
        closed_ids  = {d.get("id") for d in all_debates if d.get("type") == "close"}
        return [
            d for d in all_debates
            if d.get("type") == "open" and d.get("id") not in closed_ids
        ]

    def get_debate_summary(self, debate_id: str) -> dict:
        """Returns integrated summary: debate info + positions + rounds + outcome."""
        all_debates  = self._load_debates()
        open_entry   = None
        round_results = []
        close_entry  = None

        for d in all_debates:
            if d.get("id") == debate_id:
                t = d.get("type")
                if t == "open":
                    open_entry = d
                elif t == "round_result":
                    round_results.append(d)
                elif t == "close":
                    close_entry = d

        if open_entry is None:
            raise DebateError(f"debate not found: {debate_id!r}")

        positions   = [p for p in self._load_positions() if p.get("debate_id") == debate_id]
        pos_counts: dict = {}
        for p in positions:
            pt = p.get("position_type", "unknown")
            pos_counts[pt] = pos_counts.get(pt, 0) + 1

        return {
            "schema":           "debate_summary_v1",
            "version":          VERSION,
            "eag":              EAG_ID,
            "debate_id":        debate_id,
            "topic_id":         open_entry.get("topic_id"),
            "topic_title":      open_entry.get("topic_title"),
            "initiator":        open_entry.get("initiator"),
            "status":           "closed" if close_entry else "open",
            "round_count":      len(round_results),
            "position_count":   len(positions),
            "position_summary": pos_counts,
            "outcome":          close_entry.get("outcome")         if close_entry else None,
            "consensus_level":  close_entry.get("consensus_level") if close_entry else None,
            "decision_ref":     close_entry.get("decision_ref")    if close_entry else None,
            "positions":        positions,
            "round_results":    round_results,
        }


if __name__ == "__main__":
    import sys
    engine = AgentDebateEngine()
    debates = engine.get_open_debates()
    print(json.dumps({"open_debates": len(debates)}, ensure_ascii=False, indent=2))
    sys.exit(0)

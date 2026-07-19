#!/usr/bin/env python3
"""
area7_activation.py v1.0.0
WP-2: Area 7 Organizational Learning activation for aiba_monitor.
EAG: EAG-S374-LEARNING-LOOP-B-ACTIVATE-IMPL-001

Wires area_7.detect_improvement_opportunities() into the monitor batch:
  - L1 file-persistent 30-min cooldown (survives systemd 5-min restarts)
  - L2 stable-field content-hash dedup (trigger+description+priority) -> no proposal flood
  - Channel 3 (external change) self-excludes on fresh instance (_prev_*=None)
  - overdue proposals OUT of scope (boot_briefing already reports)
  - Proposals are pending_eag only; caller returns fired=False (no alert firing)
C2: area_7 / area_15 modules UNCHANGED.
"""
import json
import re
import time
import hashlib
from pathlib import Path

ROOT          = Path("/opt/arss/engine/arss-protocol")
THROTTLE_PATH = ROOT / "tools/monitor/area7_throttle.json"
COOLDOWN_SEC  = 1800  # 30 min (mirrors model_probe PROBE_INTERVAL_SEC)
MAX_HASHES    = 100
ACTOR         = "area_7_scheduler"


def _load_state(path):
    """Load throttle state; fail-safe default on any error."""
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {
                    "last_run_ts":     float(data.get("last_run_ts", 0.0)),
                    "proposal_hashes": list(data.get("proposal_hashes", [])),
                }
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        pass
    return {"last_run_ts": 0.0, "proposal_hashes": []}


def _save_state(path, state):
    """Persist throttle state; fail-safe (monitoring must not halt)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


_ID_PATTERN  = re.compile(r'([A-Za-z]+-\d+)')   # PC-3, RC-2, DC-3 -> preserved
_HEX_PATTERN = re.compile(r'\b[a-f0-9]{6,}\b')  # context_hash[:8] -> {H}
_NUM_PATTERN = re.compile(r'\d+')               # remaining counts -> {N}


def _to_letters(n):
    """0->a, 1->b, ... 25->z, 26->aa. Digit-free placeholder index."""
    result = ""
    while True:
        result = chr(97 + n % 26) + result
        n = n // 26
        if n == 0:
            break
    return result


def _description_pattern(description):
    """v3 (S431): normalise volatile counts out of description, keep signal identity.
    Steps: preserve identifier tokens -> mask hex hashes -> mask digits -> restore.
    Placeholders are digit-free, so the digit mask cannot corrupt them.
    Note: 'Area 13' also becomes 'Area {N}' (13 is not an identifier token);
    harmless because channel 2 is the sole ghs_decline signal."""
    if not isinstance(description, str):
        return ""
    preserved = {}
    counter = [0]

    def _save_id(m):
        token = m.group(0)
        ph = "__K%s__" % _to_letters(counter[0])
        counter[0] += 1
        preserved[ph] = token
        return ph

    s = _ID_PATTERN.sub(_save_id, description)
    s = _HEX_PATTERN.sub("{H}", s)
    s = _NUM_PATTERN.sub("{N}", s)
    for ph, token in preserved.items():
        s = s.replace(ph, token)
    return s


def _stable_hash(opp):
    """Hash over STABLE fields only (excludes volatile id/detected_at/source_ref).
    C1 fix: hashing the full opp dict would never match (uuid id + timestamp) -> dedup broken.
    v3 (S431): description is normalised by _description_pattern so that count
    increments stop producing new keys, while PC-1/PC-3, RC-1/RC-2 and component
    names stay distinct."""
    stable = {
        "trigger":     opp.get("trigger", ""),
        "description": _description_pattern(opp.get("description", "")),
        "priority":    opp.get("priority", ""),
    }
    content = json.dumps(stable, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def run_area7_activation(engine=None, throttle_path=None, now_ts=None):
    """Run one area_7 activation cycle. Returns summary dict.
    engine / throttle_path / now_ts are injectable for test isolation.
    Raises on unexpected engine errors (caller wraps in try/except, per monitor pattern).
    """
    if throttle_path is None:
        throttle_path = THROTTLE_PATH
    if now_ts is None:
        now_ts = time.time()

    state = _load_state(throttle_path)

    # L1: 30-min cooldown gate
    if (now_ts - state["last_run_ts"]) < COOLDOWN_SEC:
        return {"ran": False, "throttled": True, "opportunities": 0,
                "new_proposals": 0, "dedup_skipped": 0}

    # Update timestamp FIRST (avoid retry storm on error) -- mirrors model_probe
    state["last_run_ts"] = now_ts
    _save_state(throttle_path, state)

    if engine is None:
        from tools.governance.area_7_org_learning import OrgLearningEngine
        engine = OrgLearningEngine()

    opportunities = engine.detect_improvement_opportunities(window_days=30)
    if not opportunities:
        return {"ran": True, "throttled": False, "opportunities": 0,
                "new_proposals": 0, "dedup_skipped": 0}

    existing_list = list(state.get("proposal_hashes", []))
    seen = set(existing_list)
    new_hashes = []
    new_proposals = 0
    dedup_skipped = 0

    for opp in opportunities:
        h = _stable_hash(opp)
        if h in seen:
            dedup_skipped += 1
            continue
        priority = opp.get("priority") or "MEDIUM"
        try:
            engine.generate_improvement_proposal(
                trigger     = opp.get("trigger"),
                description = opp.get("description", ""),
                priority    = priority,
                actor       = ACTOR,
            )
        except Exception:
            # invalid opp (detect should provide valid values) -> skip, do NOT record hash
            continue
        seen.add(h)
        new_hashes.append(h)
        new_proposals += 1

    combined = existing_list + new_hashes
    if len(combined) > MAX_HASHES:
        combined = combined[-MAX_HASHES:]  # MRU: keep most recent
    state["proposal_hashes"] = combined
    _save_state(throttle_path, state)

    return {"ran": True, "throttled": False, "opportunities": len(opportunities),
            "new_proposals": new_proposals, "dedup_skipped": dedup_skipped}

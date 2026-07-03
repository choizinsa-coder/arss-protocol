#!/usr/bin/env python3
"""
area_2_vps_autoguard.py v1.0.0
AIF Area 2: VPS AutoGuard (3-stage security detection)
EAG: EAG-S324-AIF-AREA2-001

Stage 1: record_security_event  -> security_event_log.jsonl
Stage 2: check_service_health, check_file_integrity, detect_rc_pattern_threat
Stage 3: generate_security_alert -> security_alert_log.jsonl (pending_review)

Phase 2 placeholders: auto-isolation, external intrusion, agent ID anomaly.
Pattern: area_7_org_learning.py (append-only jsonl, validate -> entry -> append)
"""
import json
import socket
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import List, Optional

VERSION = "1.0.0"
EAG_ID  = "EAG-S324-AIF-AREA2-001"

ROOT            = Path("/opt/arss/engine/arss-protocol")
DEFAULT_LOG_DIR = ROOT / "tools" / "governance"

VALID_EVENT_TYPES = frozenset({
    "service_down", "file_integrity", "rc_pattern",
    "resource_threshold", "unknown",
})
VALID_SEVERITIES  = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})
VALID_ACTORS      = frozenset({"domi", "jeni", "caddy", "beo", "system", "unknown"})
VALID_PRIORITIES  = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW"})

AIBA_PORTS = {
    "bridge":   8443,
    "jeni":     8447,
    "domi":     8448,
    "exec":     8449,
    "guardian": 8450,
}


class AutoGuardError(ValueError):
    """AIF Area 2 validation error."""
    pass


# Module-level proxy for port checking (testability)
def _check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check TCP port reachability. Proxy for testability."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        result = sock.connect_ex((host, port))
        return result == 0
    except Exception:
        return False
    finally:
        sock.close()


# Module-level proxies for Area 15 (read-only, testability)
def _get_failure_patterns(window_minutes=10080, threshold=3):
    """Proxy to area_15_failure_memory.get_failure_patterns (read-only)."""
    from tools.governance.area_15_failure_memory import get_failure_patterns
    return get_failure_patterns(window_minutes=window_minutes, threshold=threshold)


def _get_failures_by_rc(rc_value: str):
    """Proxy to area_15_failure_memory.get_failures_by_rc (read-only)."""
    from tools.governance.area_15_failure_memory import FailureCategory, get_failures_by_rc
    return get_failures_by_rc(FailureCategory(rc_value))


class VPSAutoGuard:
    """
    AIF Area 2 - VPS AutoGuard (3-stage security detection).
    Phase 1: record / detect / classify / propose (no auto-action).
    log_dir: optional override for testing (default: DEFAULT_LOG_DIR).
    """

    def __init__(self, log_dir: Optional[Path] = None) -> None:
        self._log_dir   = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self._event_log = self._log_dir / "security_event_log.jsonl"
        self._alert_log = self._log_dir / "security_alert_log.jsonl"

    def _ensure_dir(self) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _load_events(self) -> list:
        """Load all raw security event entries."""
        if not self._event_log.exists():
            return []
        entries: list = []
        with open(self._event_log, encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        entries.append(json.loads(stripped))
                    except json.JSONDecodeError:
                        pass
        return entries

    # --- Stage 1: Detection (Record) ---

    def record_security_event(
        self,
        event_type: str,
        severity: str,
        description: str,
        source: str,
        actor: str = "system",
    ) -> dict:
        """
        Appends security event to security_event_log.jsonl.
        id: SE-{uuid4}
        """
        if event_type not in VALID_EVENT_TYPES:
            raise AutoGuardError(
                f"event_type must be one of {sorted(VALID_EVENT_TYPES)}, got {event_type!r}"
            )
        if severity not in VALID_SEVERITIES:
            raise AutoGuardError(
                f"severity must be one of {sorted(VALID_SEVERITIES)}, got {severity!r}"
            )
        if not description or not str(description).strip():
            raise AutoGuardError("required field missing: 'description'")
        if not source or not str(source).strip():
            raise AutoGuardError("required field missing: 'source'")
        actor_norm = actor.strip().lower()
        if actor_norm not in VALID_ACTORS:
            raise AutoGuardError(
                f"actor must be one of {sorted(VALID_ACTORS)}, got {actor!r}"
            )

        now = datetime.now(timezone.utc)
        entry = {
            "schema":      "security_event_v1",
            "version":     VERSION,
            "id":          f"SE-{uuid.uuid4()}",
            "event_type":  event_type,
            "severity":    severity,
            "description": description.strip(),
            "source":      source.strip(),
            "actor":       actor_norm,
            "recorded_at": now.isoformat(),
            "eag":         EAG_ID,
        }
        self._ensure_dir()
        with open(self._event_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # --- Stage 2: Classification ---

    def check_service_health(self) -> dict:
        """
        Checks AIBA service ports via TCP connect.
        Ports: bridge(8443), jeni(8447), domi(8448), exec(8449), guardian(8450).
        Non-reachable ports auto-record 'service_down' event.
        Returns: {service: {expected: True, actual: bool}}
        """
        results = {}
        for name, port in AIBA_PORTS.items():
            actual = _check_port("127.0.0.1", port)
            results[name] = {"expected": True, "actual": actual}
            if not actual:
                self.record_security_event(
                    event_type  = "service_down",
                    severity    = "HIGH",
                    description = f"Port {port} ({name}) unreachable",
                    source      = f"tcp://127.0.0.1:{port}",
                    actor       = "system",
                )
        return results

    def check_file_integrity(self, paths: List[str]) -> dict:
        """
        SHA-256 spot-check for specified file paths.
        Phase 2: real-time inotify monitoring.
        Returns: {path: hash_str | None}
        """
        results = {}
        for path_str in paths:
            p = Path(path_str)
            if not p.exists() or not p.is_file():
                results[path_str] = None
                continue
            try:
                h = sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                results[path_str] = h.hexdigest()
            except (IOError, PermissionError):
                results[path_str] = None
        return results

    def detect_rc_pattern_threat(self, window_days: int = 7) -> list:
        """
        Reads Area 15 RC patterns (read-only) to detect RC-3/RC-4 threats.
        Auto-records 'rc_pattern' CRITICAL event if threats found.
        Returns: list of threat dicts.
        """
        threats = []
        window_minutes = window_days * 1440

        try:
            patterns = _get_failure_patterns(
                window_minutes=window_minutes, threshold=3
            )
            if patterns.get("has_alert", False):
                rc3 = _get_failures_by_rc("RC-3")
                rc4 = _get_failures_by_rc("RC-4")
                high_risk = rc3 + rc4

                if high_risk:
                    threats.append({
                        "rc":          "RC-3/RC-4",
                        "source":      "area_15",
                        "description": f"{len(high_risk)} critical failures detected",
                        "count":       len(high_risk),
                        "patterns": {
                            "consecutive_repeat": patterns.get("consecutive_repeat", []),
                            "frequency_burst":    patterns.get("frequency_burst", []),
                            "cross_component":    patterns.get("cross_component", []),
                        },
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    })
                    self.record_security_event(
                        event_type  = "rc_pattern",
                        severity    = "CRITICAL",
                        description = f"RC-3/RC-4 threat: {len(high_risk)} failures",
                        source      = "area_15_failure_memory",
                        actor       = "system",
                    )
        except Exception:
            pass

        return threats

    # --- Stage 3: Proposal (SecurityAlert) ---

    def generate_security_alert(
        self,
        event_ref: str,
        description: str,
        priority: str,
        actor: str = "system",
    ) -> dict:
        """
        Appends SecurityAlert to security_alert_log.jsonl.
        status: always 'pending_review' (no auto-action in Phase 1).
        auto_isolation: None (Phase 2 placeholder).
        """
        if not event_ref or not str(event_ref).strip():
            raise AutoGuardError("required field missing: 'event_ref'")
        if not description or not str(description).strip():
            raise AutoGuardError("required field missing: 'description'")
        if priority not in VALID_PRIORITIES:
            raise AutoGuardError(
                f"priority must be one of {sorted(VALID_PRIORITIES)}, got {priority!r}"
            )

        now = datetime.now(timezone.utc)
        entry = {
            "schema":         "security_alert_v1",
            "version":        VERSION,
            "id":             f"SA-{uuid.uuid4()}",
            "event_ref":      event_ref.strip(),
            "description":    description.strip(),
            "priority":       priority,
            "status":         "pending_review",
            "auto_isolation": None,
            "actor":          actor.strip(),
            "recorded_at":    now.isoformat(),
            "eag":            EAG_ID,
        }
        self._ensure_dir()
        with open(self._alert_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    # --- Summary ---

    def get_security_summary(self) -> dict:
        """Total events, by_severity, by_event_type, recent 5."""
        all_entries    = self._load_events()
        by_severity:   dict = {}
        by_event_type: dict = {}
        for e in all_entries:
            s = e.get("severity",   "unknown")
            t = e.get("event_type", "unknown")
            by_severity[s]   = by_severity.get(s, 0) + 1
            by_event_type[t] = by_event_type.get(t, 0) + 1
        return {
            "schema":        "security_summary_v1",
            "version":       VERSION,
            "eag":           EAG_ID,
            "total_events":  len(all_entries),
            "by_severity":   by_severity,
            "by_event_type": by_event_type,
            "recent_5":      list(reversed(all_entries[-5:])) if all_entries else [],
            "log_path":      str(self._event_log),
        }


if __name__ == "__main__":
    import sys
    guard = VPSAutoGuard()
    print(json.dumps(guard.get_security_summary(), ensure_ascii=False, indent=2))
    sys.exit(0)

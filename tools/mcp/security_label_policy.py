"""
security_label_policy.py
Layer 2 - SECURITY_LABEL_REGISTRY + Break-Glass policy (S427)

Called AFTER Layer 1 (whitelist, mcp_read_server._validate_path) passes.
Contract:
  - enforce_label_policy(resolved_path) -> None on ALLOW, raises LabelPolicyDeny on DENY.

Rules:
  - registry file missing / unreadable / malformed  -> Fail-Closed DENY
  - path == registry file itself                    -> DENY (protected)
  - label SECRET                                     -> DENY
  - label RESTRICTED                                 -> ALLOW only if a valid Break-Glass marker exists
  - label UNRESTRICTED or unregistered              -> ALLOW

Break-Glass marker integrity (design v1.0.2 §4-(a)):
  - marker dir: root-owned, mode 0700, real directory
  - marker file: root-owned (st_uid == 0)
  - 6 fields present: target_path, created_by, expires_at, max_reads, reason, auth
  - not expired (expires_at >= now)
  - max_reads in 1..3
  - target_path resolves to the requested path
  - min-approach auth gate = owner-uid==0 (already enforced by root ownership check)
  - engine (runs as root) decrements max_reads; deletes marker when it reaches 0
"""
import json
import os
import stat
import time
from pathlib import Path

CODE_ROOT = Path("/opt/arss/engine/arss-protocol")

# Paths are env-overridable purely to allow isolated testing.
REGISTRY_PATH = Path(os.environ.get(
    "ARSS_LABEL_REGISTRY", str(CODE_ROOT / "SECURITY_LABEL_REGISTRY.json")))
BREAKGLASS_DIR = Path(os.environ.get(
    "ARSS_BREAKGLASS_DIR", str(CODE_ROOT / ".break_glass")))

_VALID_LABELS = {"SECRET", "RESTRICTED", "UNRESTRICTED"}
_REQUIRED_MARKER_FIELDS = ("target_path", "created_by", "expires_at",
                           "max_reads", "reason", "auth")


class LabelPolicyDeny(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _registry_self_path():
    try:
        return str(REGISTRY_PATH.resolve())
    except Exception:
        return str(REGISTRY_PATH)


def _load_registry():
    """Return {resolved_path: label}. Fail-Closed on any integrity problem."""
    try:
        raw = REGISTRY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise LabelPolicyDeny("REGISTRY_MISSING_FAILCLOSED")
    except Exception:
        raise LabelPolicyDeny("REGISTRY_READ_FAILCLOSED")
    try:
        data = json.loads(raw)
    except Exception:
        raise LabelPolicyDeny("REGISTRY_PARSE_FAILCLOSED")
    if (not isinstance(data, dict)
            or not isinstance(data.get("labels"), list)):
        raise LabelPolicyDeny("REGISTRY_SCHEMA_FAILCLOSED")
    mapping = {}
    for entry in data["labels"]:
        if not isinstance(entry, dict) or "path" not in entry or "label" not in entry:
            raise LabelPolicyDeny("REGISTRY_ENTRY_FAILCLOSED")
        label = entry["label"]
        if label not in _VALID_LABELS:
            raise LabelPolicyDeny("REGISTRY_LABEL_FAILCLOSED")
        try:
            p = str(Path(entry["path"]).resolve())
        except Exception:
            raise LabelPolicyDeny("REGISTRY_PATH_FAILCLOSED")
        mapping[p] = label
    return mapping


def _breakglass_dir_ok():
    """marker dir must be a real directory, root-owned, mode 0700."""
    try:
        st = os.stat(BREAKGLASS_DIR)
    except FileNotFoundError:
        return False
    except Exception:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    if st.st_uid != 0:
        return False
    if stat.S_IMODE(st.st_mode) != 0o700:
        return False
    return True


def _find_valid_marker(resolved_path_str):
    """Return (marker_path, data) for a valid, matching, active marker; else None."""
    if not _breakglass_dir_ok():
        return None
    now = time.time()
    try:
        entries = list(BREAKGLASS_DIR.iterdir())
    except Exception:
        return None
    for mp in entries:
        try:
            mst = os.stat(mp)
        except Exception:
            continue
        if not stat.S_ISREG(mst.st_mode):
            continue
        if mst.st_uid != 0:
            continue
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if not all(k in data for k in _REQUIRED_MARKER_FIELDS):
            continue
        try:
            if str(Path(data["target_path"]).resolve()) != resolved_path_str:
                continue
        except Exception:
            continue
        try:
            if float(data["expires_at"]) < now:
                continue
        except Exception:
            continue
        try:
            mr = int(data["max_reads"])
        except Exception:
            continue
        if mr < 1 or mr > 3:
            continue
        return (mp, data)
    return None


def _consume_marker(mp, data):
    """Decrement remaining reads; delete when exhausted. Engine runs as root."""
    remaining = int(data["max_reads"]) - 1
    if remaining <= 0:
        mp.unlink()
    else:
        data["max_reads"] = remaining
        mp.write_text(json.dumps(data), encoding="utf-8")


def enforce_label_policy(resolved_path):
    """ALLOW -> return None. DENY -> raise LabelPolicyDeny."""
    try:
        rp = str(Path(resolved_path).resolve())
    except Exception:
        raise LabelPolicyDeny("PATH_RESOLVE_FAILCLOSED")

    # The registry file itself is never readable through the read tools.
    if rp == _registry_self_path():
        raise LabelPolicyDeny("LABEL_REGISTRY_PROTECTED")

    registry = _load_registry()  # Fail-Closed embedded
    label = registry.get(rp)

    if label is None or label == "UNRESTRICTED":
        return  # ALLOW

    if label == "SECRET":
        raise LabelPolicyDeny("LABEL_SECRET_DENY")

    if label == "RESTRICTED":
        found = _find_valid_marker(rp)
        if found is None:
            raise LabelPolicyDeny("LABEL_RESTRICTED_NO_BREAKGLASS")
        mp, data = found
        try:
            _consume_marker(mp, data)
        except Exception:
            raise LabelPolicyDeny("BREAKGLASS_DECREMENT_FAILED")
        return  # ALLOW

    raise LabelPolicyDeny("LABEL_UNKNOWN_FAILCLOSED")

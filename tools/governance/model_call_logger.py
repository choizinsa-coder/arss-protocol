# -*- coding: utf-8 -*-
"""model_call_logger.py — durable per-call model metrics log.
S446 EAG-S446-MODEL-METRICS-STAGE1-001.
Fail-soft: never raises into the caller. Concurrency-safe (flock). Reason field scrubbed.
"""
import json, os, sys, re, fcntl
from datetime import datetime, timezone

MODEL_CALL_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "model_call_log.jsonl")
_MAX_BYTES = 10 * 1024 * 1024
_MAX_ROTATIONS = 5
_MAX_REASON_LEN = 300

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|bearer|password|passwd|authorization)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)xai-[A-Za-z0-9]{8,}"),
    re.compile(r"/(?:etc|opt|home|root|var)/\S+"),
    re.compile(r"[A-Za-z0-9_\-]{32,}"),
]

def _scrub(text):
    if not text:
        return text
    s = str(text)[:_MAX_REASON_LEN]
    for pat in _SECRET_PATTERNS:
        s = pat.sub("[REDACTED]", s)
    return s

def _extract_tokens(usage):
    if not isinstance(usage, dict):
        return None, None
    p = usage.get("prompt_tokens", usage.get("promptTokenCount"))
    c = usage.get("completion_tokens", usage.get("candidatesTokenCount"))
    return p, c

def _rotate_if_needed(path):
    try:
        if os.path.exists(path) and os.path.getsize(path) > _MAX_BYTES:
            for i in range(_MAX_ROTATIONS - 1, 0, -1):
                src = "%s.%d" % (path, i)
                dst = "%s.%d" % (path, i + 1)
                if os.path.exists(src):
                    os.replace(src, dst)
            os.replace(path, "%s.1" % path)
    except Exception:
        pass

def append_model_call(agent=None, session_id=None, escalate=False, reason=None,
                      model_requested=None, model_served=None, ok=None,
                      usage=None, llm_duration_ms=None, round_index=None,
                      log_path=None):
    """Append one model-call record as a JSONL line. Fail-soft; never raises."""
    if (log_path is None) and (os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules):
        return None  # S446: do not pollute production log during test runs
    path = log_path or MODEL_CALL_LOG_PATH
    try:
        p_tok, c_tok = _extract_tokens(usage)
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "agent": agent,
            "session_id": session_id,
            "escalate": bool(escalate),
            "reason": _scrub(reason) if reason else None,
            "model_requested": model_requested,
            "model_served": model_served,
            "ok": ok,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "llm_duration_ms": llm_duration_ms,
            "round_index": round_index,
        }
        line = json.dumps(rec, ensure_ascii=False, default=str)
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(line + "\n")
                f.flush()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return True
    except Exception as exc:
        print("[WARN] append_model_call failed: %s" % exc, file=sys.stderr)
        return False

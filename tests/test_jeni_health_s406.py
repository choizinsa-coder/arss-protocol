#!/usr/bin/env python3
# tests/test_jeni_health_s406.py
# OI-S403-005 -- /health max_output_tokens display bug fix.
# EAG-S406-JENI-HEALTH-FIX-001
from pathlib import Path

ARSS_ROOT = Path("/opt/arss/engine/arss-protocol")
JENI_RUNTIME = ARSS_ROOT / "tools/jeni_runtime/aiba_jeni_runtime.py"


def _find_max_output_tokens_line():
    src = JENI_RUNTIME.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines(), start=1):
        if '"max_output_tokens"' in line:
            return i, line.strip()
    return None, None


def test_health_max_output_tokens_uses_llm_not_gemini():
    lineno, line = _find_max_output_tokens_line()
    assert lineno is not None, '"/health max_output_tokens" line not found'
    assert "GEMINI_MAX_OUTPUT_TOKENS" not in line, (
        f"Line {lineno} still references GEMINI_MAX_OUTPUT_TOKENS: {line}"
    )
    assert "LLM_MAX_TOKENS" in line, (
        f"Line {lineno} missing LLM_MAX_TOKENS: {line}"
    )


def test_health_max_output_tokens_not_hardcoded():
    lineno, line = _find_max_output_tokens_line()
    assert lineno is not None
    parts = line.split(":")
    assert len(parts) >= 2, f"Line {lineno} unexpected format: {line}"
    value_part = parts[-1].strip().rstrip(",")
    assert not value_part.isdigit(), (
        f"Line {lineno} has hardcoded numeric value {value_part}: {line}"
    )

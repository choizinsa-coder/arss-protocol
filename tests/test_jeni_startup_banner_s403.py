#!/usr/bin/env python3
"""tests/test_jeni_startup_banner_s403.py
EAG-S403-GROK45-PROD-SWITCH-001 -- OI-S401-008 fix verification.
Startup banner must reference LLM_MODEL/_IS_GEMINI, not GEMINI_MODEL.
"""
from pathlib import Path

ARSS_ROOT = Path("/opt/arss/engine/arss-protocol")
JENI_RUNTIME = ARSS_ROOT / "tools/jeni_runtime/aiba_jeni_runtime.py"


def _banner_line():
    src = JENI_RUNTIME.read_text(encoding="utf-8")
    for i, line in enumerate(src.splitlines()):
        if "[JENI_RUNTIME] starting" in line:
            return i, line
    return None, None


def _warn_line():
    src = JENI_RUNTIME.read_text(encoding="utf-8")
    for line in src.splitlines():
        if "FAIL_CLOSED" in line and "not set" in line and "JENI_RUNTIME" in line:
            return line
    return None


def test_startup_banner_uses_llm_model_not_gemini():
    """OI-S401-008: banner must print LLM_MODEL, not GEMINI_MODEL."""
    idx, banner = _banner_line()
    assert idx is not None, "Startup banner line not found"
    assert "GEMINI_MODEL" not in banner, (
        f"Banner still references GEMINI_MODEL at line {idx}: {banner}"
    )
    assert "LLM_MODEL" in banner, (
        f"Banner missing LLM_MODEL at line {idx}: {banner}"
    )


def test_startup_banner_has_is_gemini_flag():
    """OI-S401-008: banner must include is_gemini flag for operational visibility."""
    idx, banner = _banner_line()
    assert idx is not None, "Startup banner line not found"
    assert "_IS_GEMINI" in banner, (
        f"Banner missing _IS_GEMINI at line {idx}: {banner}"
    )


def test_startup_warn_uses_llm_api_key_not_gemini():
    """OI-S401-008: WARN line must check AIBA_LLM_API_KEY, not AIBA_GEMINI_API_KEY."""
    warn = _warn_line()
    assert warn is not None, "WARN/FAIL_CLOSED line not found"
    assert "AIBA_LLM_API_KEY" in warn, f"WARN still references old key: {warn}"
    assert "AIBA_GEMINI_API_KEY" not in warn, f"WARN still references Gemini key: {warn}"

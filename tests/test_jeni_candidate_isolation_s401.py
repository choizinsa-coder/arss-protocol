"""EAG-S401-CANDIDATE-JENI-ISOLATION-IMPL-001

Prove the 4 env overrides ACTUALLY work.

Why this file exists: the 2305-test regression only proves that with the envs
UNSET nothing changed. It proves nothing about the override path. Without
these TCs, the first proof that the candidate is isolated from the incumbent
would be the live run itself - i.e. we would discover a broken isolation only
AFTER exposing the incumbent's cost state, memory and global breaker to it.
(OI-S399-004: green tests prove structure, not behaviour.)

No network calls. Each module is loaded from file under a unique name, so
sys.modules is not polluted for other tests.
"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JENI_PATH = os.path.join(ROOT, "tools/jeni_runtime/aiba_jeni_runtime.py")
GCB_PATH = os.path.join(ROOT, "tools/governance/global_circuit_breaker.py")

ISOLATION_ENVS = (
    "AIBA_RUNTIME_PORT",
    "AIBA_DAILY_COST_STATE_PATH",
    "AIBA_SANDBOX_ROOT",
    "AIBA_GCB_STATE_PATH",
)


def _load(path: str, alias: str):
    """Load a module fresh from file under a throwaway name."""
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules.pop(alias, None)
    return mod


@pytest.fixture(autouse=True)
def _clean_isolation_env(monkeypatch):
    """Every TC starts from a state where none of the 4 envs is set."""
    for name in ISOLATION_ENVS:
        monkeypatch.delenv(name, raising=False)
    yield


# ── defaults: incumbent-as-default (OI-S399-001) ─────────────────────────────

def test_defaults_unchanged_when_envs_unset():
    m = _load(JENI_PATH, "_s401_jeni_default")
    assert m.RUNTIME_PORT == 8447
    assert m.DAILY_COST_STATE_PATH == os.path.join(
        m.ARSS_ROOT, "runtime/governance/budget/JENI_DAILY_COST_STATE.json")
    assert m.SANDBOX_ROOT == os.path.join(m.ARSS_ROOT, "tools/sandbox/jeni")


def test_gcb_default_unchanged_when_env_unset():
    g = _load(GCB_PATH, "_s401_gcb_default")
    assert g.GCB_STATE_PATH.endswith(
        "runtime/governance/gcb/global_circuit_breaker_state.json")


# ── overrides: the candidate must land somewhere else entirely ───────────────

def test_port_override(monkeypatch):
    monkeypatch.setenv("AIBA_RUNTIME_PORT", "8450")
    m = _load(JENI_PATH, "_s401_jeni_port")
    assert m.RUNTIME_PORT == 8450


def test_cost_state_override_does_not_touch_incumbent(tmp_path, monkeypatch):
    candidate = str(tmp_path / "CANDIDATE_COST.json")
    monkeypatch.setenv("AIBA_DAILY_COST_STATE_PATH", candidate)
    m = _load(JENI_PATH, "_s401_jeni_cost")
    assert m.DAILY_COST_STATE_PATH == candidate
    # the incumbent's budget file must not be the write target
    assert "JENI_DAILY_COST_STATE.json" not in m.DAILY_COST_STATE_PATH


def test_sandbox_override_moves_every_memory_dir(tmp_path, monkeypatch):
    candidate = str(tmp_path / "jeni_candidate")
    monkeypatch.setenv("AIBA_SANDBOX_ROOT", candidate)
    m = _load(JENI_PATH, "_s401_jeni_sandbox")
    assert m.SANDBOX_ROOT == candidate
    # the derived dirs are what _persist_conversation/_persist_audit write to,
    # and what _load_memory_context reads back into the NEXT verification.
    incumbent = os.path.join(m.ARSS_ROOT, "tools/sandbox/jeni")
    for d in (m.SANDBOX_ACTIVE, m.MEM_CONVERSATION_DIR, m.MEM_FINDINGS_DIR,
              m.MEM_AUDITS_DIR, m.MEM_STATE_DIR, m.MEM_STATE_FILE,
              m.MEM_TRACES_DIR):
        assert d.startswith(candidate)
        assert not d.startswith(incumbent)


def test_sandbox_override_moves_the_write_whitelist(tmp_path, monkeypatch):
    candidate = str(tmp_path / "jeni_candidate")
    monkeypatch.setenv("AIBA_SANDBOX_ROOT", candidate)
    m = _load(JENI_PATH, "_s401_jeni_wl")
    # candidate may write inside its own sandbox...
    assert m._is_write_allowed(os.path.join(candidate, "active/x.txt")) is True
    # ...and NOT into the incumbent's sandbox.
    incumbent_file = os.path.join(
        m.ARSS_ROOT, "tools/sandbox/jeni/active/state/runtime_state.json")
    assert m._is_write_allowed(incumbent_file) is False


def test_gcb_override(tmp_path, monkeypatch):
    candidate = str(tmp_path / "gcb_candidate.json")
    monkeypatch.setenv("AIBA_GCB_STATE_PATH", candidate)
    g = _load(GCB_PATH, "_s401_gcb_override")
    assert g.GCB_STATE_PATH == candidate
    assert "global_circuit_breaker_state.json" not in g.GCB_STATE_PATH

"""S456 repository hygiene contracts (EAG-S456-REPO-CLEAN-FIX-001).

Why these exist
---------------
S456 measured 1263 files that a single `git add -A` would have staged, three of
them service credential copies. The residue accumulated because .gitignore listed
sandbox subdirectories one by one, so every new subdirectory opened a fresh gap.

S455 lesson applied: a rule depends on human attention, a contract does not.
These tests read git itself, so they fail the moment the same class of residue
reappears -- no reviewer has to remember to look.
"""
import subprocess
import pathlib
import pytest

ROOT = pathlib.Path("/opt/arss/engine/arss-protocol")

SENSITIVE_SUFFIXES = (".env", ".pem", ".key", ".p12", ".pfx")
SENSITIVE_MARKERS = ("secrets", "credential", "private_key")

# Suffixes that ad-hoc backups have actually used in this repo. The historical
# `*.bak` rule never matched any of them, which is how nine files survived.
BACKUP_MARKERS = ("_bak", "bak", ".pre_purge", ".pre_backfill", ".pre_cleanup", ".pre_p5c")


def _git(*args):
    proc = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60)
    return proc.stdout.splitlines()


def _stageable():
    """Files git would stage right now: untracked and not covered by .gitignore."""
    return [f for f in _git("ls-files", "--others", "--exclude-standard") if f]


def test_no_credential_material_is_stageable():
    """No credential-like file may sit outside .gitignore. Root cause of S456."""
    hits = [
        f for f in _stageable()
        if f.lower().endswith(SENSITIVE_SUFFIXES)
        or any(m in f.lower() for m in SENSITIVE_MARKERS)
    ]
    assert hits == [], f"credential material exposed to git add: {hits}"


def test_no_backup_residue_is_stageable():
    """Ad-hoc backups must be ignored or removed, never committable."""
    hits = [
        f for f in _stageable()
        if any(m in pathlib.PurePath(f).name for m in BACKUP_MARKERS)
    ]
    assert hits == [], f"backup residue exposed to git add: {hits}"


def test_sandbox_tree_is_ignored_as_a_whole():
    """Blanket rule, not per-subdirectory. Per-subdir listing is what leaked S444."""
    probe = "tools/sandbox/a_subdir_that_does_not_exist_yet/file.txt"
    proc = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", probe],
        cwd=ROOT, capture_output=True, timeout=30,
    )
    assert proc.returncode == 0, (
        "a new tools/sandbox/ subdirectory would not be ignored; "
        "the blanket rule is missing"
    )


def test_session_context_files_are_not_tracked():
    """They are regenerated every session; tracking them made the repo permanently dirty."""
    tracked = set(_git("ls-files"))
    for name in ("SESSION_CONTEXT.json", "SESSION_CONTEXT_POINTER.json"):
        assert name not in tracked, f"{name} is tracked again; status noise returns"


def test_decision_ledger_stays_tracked():
    """Deliberate asymmetry: the ledger is audit evidence and git is its only remote copy."""
    tracked = set(_git("ls-files"))
    assert "tools/governance/decision_ledger.jsonl" in tracked, (
        "decision ledger lost git tracking; its only off-host backup is gone"
    )


def test_audit_snapshots_are_preserved_on_disk():
    """Ignored is not deleted. Purge snapshots are the sole copy of those moments."""
    survivors = list(ROOT.glob("tools/governance/*.pre_*"))
    assert survivors, "purge snapshots disappeared from disk"


@pytest.mark.parametrize("path", [
    "tools/autoroute/runtime/autoroute_bidir_counter_S248.json",
])
def test_referenced_runtime_state_survives_cleanup(path):
    """Guards a near-miss: this file looked expired but live code reads it."""
    assert (ROOT / path).is_file(), f"referenced runtime state deleted: {path}"


def test_stageable_surface_stays_small():
    """Regression budget. S456 brought 1263 down to single digits; drift shows up here."""
    count = len(_stageable())
    assert count <= 40, f"stageable file count regressed to {count}"

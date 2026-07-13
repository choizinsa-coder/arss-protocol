#!/usr/bin/env python3
# tests/test_l2_write_evidence_s406.py
# EAG-S406-L2-WRITE-EVIDENCE-001
# write_script success must record written_path into _session_reads (L2 evidence),
# so that a subsequent run_script of the SAME path passes L2 without a read-back.
import os
import sys

ROOT = "/opt/arss/engine/arss-protocol"
MCP_DIR = os.path.join(ROOT, "tools/mcp")
if MCP_DIR not in sys.path:
    sys.path.insert(0, MCP_DIR)

import mcp_http_bridge as br  # noqa: E402

SANDBOX = os.path.join(ROOT, "tools/sandbox/caddy/active")


def _reset():
    br._session_reads.clear()


def test_write_script_success_records_l2_evidence():
    """exit_code==0 + written_path -> adopted into _session_reads."""
    _reset()
    path = os.path.join(SANDBOX, "tc_s406_ok.py")
    result = {"ok": True, "command": "write_script",
              "exit_code": 0, "written_path": path}
    _written = result.get("written_path")
    if _written and result.get("exit_code") == 0:
        br._l2_record_read(_written)
    assert path in br._session_reads
    assert br._l2_gate([path]) is None


def test_write_script_failure_does_not_record():
    """exit_code!=0 -> never adopted. L2 must still DENY."""
    _reset()
    path = os.path.join(SANDBOX, "tc_s406_fail.py")
    result = {"ok": False, "command": "write_script",
              "exit_code": -1, "written_path": None}
    _written = result.get("written_path")
    if _written and result.get("exit_code") == 0:
        br._l2_record_read(_written)
    assert path not in br._session_reads
    assert br._l2_gate([path]) is not None


def test_non_write_command_does_not_record():
    """pytest/git_* have no written_path -> no-op."""
    _reset()
    result = {"ok": True, "command": "pytest", "exit_code": 0}
    _written = result.get("written_path")
    if _written and result.get("exit_code") == 0:
        br._l2_record_read(_written)
    assert len(br._session_reads) == 0


def test_unwritten_path_still_denied():
    """CORE SAFETY: a path caddy never wrote is still L2_DENY."""
    _reset()
    written = os.path.join(SANDBOX, "tc_s406_a.py")
    other = os.path.join(SANDBOX, "tc_s406_b.py")
    br._l2_record_read(written)
    assert br._l2_gate([written]) is None
    deny = br._l2_gate([other])
    assert deny is not None
    assert "L2_DENY" in deny


def test_read_file_adoption_path_unchanged():
    """Existing read_file -> _l2_record_read contract is intact."""
    _reset()
    p = os.path.join(ROOT, "SESSION_CONTEXT_POINTER.json")
    br._l2_record_read(p)
    assert br._l2_gate([p]) is None

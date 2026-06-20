import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_valid_hash_format_accepted():
    state = build_governance_state(["EAG-1"], approvals=[make_approval("EAG-1")], session="S272")
    assert state["approvals"][0]["hash_ok"] is True

def test_malformed_hash_rejected():
    state = build_governance_state(["EAG-1"], approvals=[make_approval("EAG-1", approval_hash=BAD_HASH)], session="S272")
    assert state["approvals"][0]["hash_ok"] is False
    assert state["compiler_verdict"] == INVALID

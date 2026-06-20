import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_missing_approved_by_review():
    app = make_approval()
    del app["approved_by"]
    state = build_governance_state(["EAG-1"], approvals=[app], session="S272")
    assert state["approvals"][0]["verdict"] == REVIEW

def test_missing_approval_id_review():
    app = make_approval()
    app["approval_id"] = None
    state = build_governance_state(["EAG-1"], approvals=[app], session="S272")
    assert state["approvals"][0]["verdict"] == REVIEW

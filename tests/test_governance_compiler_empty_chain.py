import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_empty_chain_review():
    out = compile_governance(make_context([]), approvals=None)
    assert out["governance_state"]["compiler_verdict"] == REVIEW
    assert out["governance_state"]["declared_count"] == 0

def test_none_chain_review():
    out = compile_governance({"session": "S272", "eag_chain": None})
    assert out["governance_state"]["compiler_verdict"] == REVIEW

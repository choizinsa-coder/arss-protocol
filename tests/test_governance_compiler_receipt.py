import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_receipt_fields():
    out = compile_governance(make_context(["EAG-1"]), approvals=[make_approval("EAG-1")])
    r = out["receipt"]
    assert r["receipt_scope"] == "R1"
    assert r["receipt_type"] == "GOVERNANCE_COMPILER"
    assert r["receipt_id"]
    assert r["projection_hash"] == out["projection"]["projection_hash"]

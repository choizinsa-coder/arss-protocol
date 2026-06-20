import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_same_input_same_hash():
    ctx = make_context(["EAG-1", "EAG-2"])
    apps = [make_approval("EAG-1"), make_approval("EAG-2")]
    o1 = compile_governance(ctx, approvals=apps)
    o2 = compile_governance(ctx, approvals=apps)
    assert o1["projection"]["projection_hash"] == o2["projection"]["projection_hash"]

def test_persisted_flag_false():
    out = compile_governance(make_context(["EAG-1"]), approvals=[make_approval("EAG-1")])
    assert out["projection"]["_persisted"] is False

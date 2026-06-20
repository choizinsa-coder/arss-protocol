import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_basic_compile_valid():
    ctx = make_context(["EAG-S271-AICS-001"])
    out = compile_governance(ctx, approvals=[make_approval()])
    assert out["governance_state"]["compiler_verdict"] == VALID
    assert out["projection"]["governance_state"] == VALID
    assert out["receipt"]["receipt_scope"] == "R1"

def test_basic_string_eag_chain():
    ctx = make_context("EAG-S271-AICS-001, EAG-S271-DIRECTCH-001")
    out = compile_governance(ctx, approvals=[make_approval(), make_approval("EAG-S271-DIRECTCH-001")])
    assert out["governance_state"]["declared_count"] == 2
    assert out["governance_state"]["compiler_verdict"] == VALID

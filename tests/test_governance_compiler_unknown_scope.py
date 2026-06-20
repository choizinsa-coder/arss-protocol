import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_token_without_evidence_review():
    # 토큰 선언됐으나 approval 미제공 → REVIEW
    ctx = make_context(["EAG-UNKNOWN-001"])
    out = compile_governance(ctx, approvals=None)
    assert out["governance_state"]["compiler_verdict"] == REVIEW
    assert out["governance_state"]["chain_complete"] is False

def test_projection_required_eag_present_false():
    ctx = make_context(["EAG-UNKNOWN-001"])
    out = compile_governance(ctx, approvals=None)
    assert out["projection"]["required_eag_present"] is False

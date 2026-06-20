import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_chain_incomplete_yields_review():
    # 토큰 2개 선언, 증거 1개 → 불완전 → REVIEW
    ctx = make_context(["EAG-1", "EAG-2"])
    state = build_governance_state(ctx["eag_chain"], approvals=[make_approval("EAG-1")], session="S272")
    assert state["chain_complete"] is False
    assert state["compiler_verdict"] == REVIEW

def test_chain_complete_coverage():
    ctx = make_context(["EAG-1"])
    state = build_governance_state(ctx["eag_chain"], approvals=[make_approval("EAG-1")], session="S272")
    assert state["chain_complete"] is True

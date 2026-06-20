import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
sys.path.insert(0, os.path.dirname(__file__))
from governance_compiler import (
    compile_governance, build_governance_state,
    build_bridge_projection, build_compiler_receipt,
)
from governance_compiler.governance_state_builder import VALID, INVALID, REVIEW
from _fixtures import make_approval, make_context, VALID_HASH, VALID_HASH_2, BAD_HASH


def test_projection_only_state_values():
    out = compile_governance(make_context(["EAG-1"]), approvals=[make_approval("EAG-1")])
    proj = out["projection"]
    # 권한 정보 미포함 확인
    assert "scope" not in proj
    assert "actor" not in proj
    assert "expires" not in proj
    assert proj["governance_state"] in (VALID, INVALID, REVIEW)

def test_projection_fallback_to_review():
    # 빈 증거 → REVIEW 폴백
    out = compile_governance(make_context(["EAG-1"]), approvals=[])
    assert out["projection"]["governance_state"] == REVIEW

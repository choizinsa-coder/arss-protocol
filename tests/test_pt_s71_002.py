# test_pt_s71_002.py -- PT-S71-002 Stage 재설계 검증
# TC-1~TC-7: PRE_DELTA_IDEMPOTENCY_GATE / PRE_COMMIT_GATE (FIX-2)
import json, os, shutil, pytest, sys
sys.path.insert(0, "/opt/arss/engine/arss-protocol")
from tools.delta_context.shadow_pipeline import run_shadow_pipeline
from tools.delta_context.commit_marker_manager import verify_commit_exists
from tools.delta_context.session_transaction_manager import create_transaction

DLB = "/opt/arss/engine/arss-protocol/DELTA_LOG"
TXP = "/opt/arss/engine/arss-protocol/DELTA_LOG/transactions"
CMP = "/opt/arss/engine/arss-protocol/DELTA_LOG/commits"

def _req(dom="test_s71"):
    return [{"domain": dom, "sequence_number": 1, "event_type": "agent_focus_updated",
             "target_key": "agent_focus", "new_value": {"caddy": "tc"},
             "cross_ref": "PT-S71-002", "prev_delta_id": None, "prev_content_hash": None}]

def _cleanup(s, dom="test_s71"):
    for p in [os.path.join(TXP, f"TX-S{s}.json"),
              os.path.join(CMP, f"COMMIT-S{s}.json"),
              os.path.join(DLB, dom, f"S{s}")]:
        if os.path.isfile(p): os.remove(p)
        elif os.path.isdir(p): shutil.rmtree(p)

def _cidx(s, dom="test_s71"):
    ip = os.path.join(DLB, "INDEX.json")
    if not os.path.exists(ip): return
    with open(ip) as f: idx = json.load(f)
    for d in list(idx.get("domains", {})): idx["domains"][d].get("sessions", {}).pop(f"S{s}", None)
    idx["transactions"] = [t for t in idx.get("transactions", []) if t.get("tx_id") != f"TX-S{s}"]
    with open(ip, "w") as f: json.dump(idx, f, indent=2, ensure_ascii=False)

# TC-1: 정상 흐름
def test_tc1_normal_flow():
    s = 9001; _cleanup(s); _cidx(s)
    try:
        r = run_shadow_pipeline(session_number=s, delta_requests=_req())
        assert r["success"] is True, f"TC-1 FAIL: {r}"
        assert r["commit_id"] == f"COMMIT-S{s}"
    finally:
        _cleanup(s); _cidx(s)

# TC-2: TX 있음 + COMMIT 없음 -> PRE_COMMIT_GATE HARD_STOP
def test_tc2_tx_no_commit():
    s = 9002; _cleanup(s)
    try:
        os.makedirs(TXP, exist_ok=True)
        with open(os.path.join(TXP, f"TX-S{s}.json"), "w") as f:
            json.dump({"tx_id": f"TX-S{s}", "status": "PENDING"}, f)
        r = verify_commit_exists(s)
        assert r.get("hard_stop") is True, f"TC-2 FAIL: {r}"
        assert "FIX-2" in r.get("reason", ""), f"TC-2 reason: {r}"
    finally:
        _cleanup(s)

# TC-3: COMMIT 있음 + TX 없음 -> exists True
def test_tc3_commit_no_tx():
    s = 9003; _cleanup(s)
    try:
        os.makedirs(CMP, exist_ok=True)
        with open(os.path.join(CMP, f"COMMIT-S{s}.json"), "w") as f:
            json.dump({"commit_id": f"COMMIT-S{s}", "status": "COMMITTED"}, f)
        r = verify_commit_exists(s)
        assert r.get("exists") is True, f"TC-3 FAIL: {r}"
        assert r.get("hard_stop") is not True
    finally:
        _cleanup(s)

# TC-4: included_deltas 비어 있음 -> TX 생성 실패 (BK-5 CASE-C)
def test_tc4_empty_deltas():
    r = create_transaction(session_number=9004, committed_by="caddy", included_deltas=[],
                           generated_at="2026-05-01T00:00:00.000+09:00")
    assert r["success"] is False, f"TC-4 FAIL: {r}"
    assert "비어" in r.get("reason", "") or "BK-5" in r.get("reason", ""), f"TC-4: {r}"

# TC-5: delta 존재 + TX/COMMIT 불완전 -> PARTIAL_STATE_DETECTED
def test_tc5_partial_state():
    s = 9005; dom = "test_s71"; _cleanup(s, dom)
    try:
        d = os.path.join(DLB, dom, f"S{s}"); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "dummy.json"), "w") as f: json.dump({"id": "x"}, f)
        r = run_shadow_pipeline(session_number=s, delta_requests=_req(dom))
        assert r["success"] is False, f"TC-5: {r}"
        assert r.get("hard_stop") is True, f"TC-5 hard_stop: {r}"
        assert r.get("reason") == "PARTIAL_STATE_DETECTED", f"TC-5 reason: {r}"
        assert r.get("stage") == "PRE_DELTA_IDEMPOTENCY_GATE"
    finally:
        _cleanup(s, dom)

# TC-6: delta 미존재 -> Stage 0 PASS -> 정상 완료
def test_tc6_no_delta_pass():
    s = 9006; dom = "test_s71"; _cleanup(s, dom); _cidx(s, dom)
    assert not os.path.exists(os.path.join(DLB, dom, f"S{s}")), "precondition fail"
    try:
        r = run_shadow_pipeline(session_number=s, delta_requests=_req(dom))
        assert r.get("stage") != "PRE_DELTA_IDEMPOTENCY_GATE", f"TC-6 blocked: {r}"
        assert r["success"] is True, f"TC-6 FAIL: {r}"
    finally:
        _cleanup(s, dom); _cidx(s, dom)

# TC-7: TX 없음 + COMMIT 없음 -> hard_stop False (정상)
def test_tc7_no_tx_no_commit():
    s = 9007; _cleanup(s)
    r = verify_commit_exists(s)
    assert r.get("exists") is False
    assert r.get("hard_stop") is not True, f"TC-7 FAIL: {r}"
    reason = r.get("reason", "")
    assert "TX 미존재" in reason or "정상" in reason, f"TC-7 reason: {reason}"

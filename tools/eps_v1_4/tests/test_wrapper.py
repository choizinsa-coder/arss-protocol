import pytest
from datetime import datetime, timezone
from tools.eps_v1_4.wrapper import wrapper_execute, safe_emit_wrapper_result

FRESH_VR = {
    "status": "PASS",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "ttl_sec": 30,
}

def test_all_pass_exploration():
    payload = {"raw_output": "가능성이 있습니다.", "context": {}}
    r = wrapper_execute(payload)
    assert r["status"] == "PASS"
    assert r["formatted_output"] is not None

def test_one_blocked_blocks_all(tmp_path):
    # E segment + A segment (no receipt) → BLOCKED
    payload = {
        "raw_output": "가능성이 있습니다. 완료되었습니다.",
        "context": {"receipt": None, "verifier_result": FRESH_VR, "evidence_paths": []},
    }
    r = wrapper_execute(payload)
    assert r["status"] == "BLOCKED"
    assert r["formatted_output"] is None

def test_empty_output_blocked():
    r = wrapper_execute({"raw_output": "", "context": {}})
    assert r["status"] == "BLOCKED"
    assert r["reason_code"] == "EMPTY_OUTPUT"

def test_proposal_block_passes():
    payload = {
        "raw_output": "수정하겠습니다.\nNext Action: 패키지 작성.",
        "context": {},
    }
    r = wrapper_execute(payload)
    assert r["status"] == "PASS"

def test_later_failure_returns_null(tmp_path):
    payload = {
        "raw_output": "가능성이 있습니다. 완료되었습니다.",
        "context": {"receipt": None, "verifier_result": FRESH_VR, "evidence_paths": []},
    }
    r = wrapper_execute(payload)
    assert r["formatted_output"] is None

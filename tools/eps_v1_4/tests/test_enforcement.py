import pytest
from datetime import datetime, timezone, timedelta
from tools.eps_v1_4.enforcement import enforce_statement

FRESH_VR = {
    "status": "PASS",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "ttl_sec": 30,
}

def _ctx(receipt=None, vr=None, paths=None):
    return {
        "receipt": receipt,
        "verifier_result": vr or FRESH_VR,
        "evidence_paths": paths or [],
    }

def test_a_missing_receipt():
    ctx = _ctx(receipt=None, paths=["/tmp/exist.json"])
    r = enforce_statement("완료되었습니다", ctx)
    assert r.status == "BLOCKED"
    assert "receipt" in r.reason

def test_a_verifier_fail():
    vr = {"status": "FAIL", "checked_at": datetime.now(timezone.utc).isoformat(), "ttl_sec": 30}
    ctx = _ctx(receipt={"receipt_id": "VR-0001"}, vr=vr, paths=["/tmp/exist.json"])
    r = enforce_statement("완료되었습니다", ctx)
    assert r.status == "BLOCKED"

def test_a_no_evidence():
    ctx = _ctx(receipt={"receipt_id": "VR-0001"}, paths=["/nonexistent/path/file.json"])
    r = enforce_statement("완료되었습니다", ctx)
    assert r.status == "BLOCKED"
    assert "evidence" in r.reason

def test_p_missing_next_action():
    r = enforce_statement("다음 단계로 수정 제안합니다", {})
    assert r.status == "BLOCKED"
    assert "Next Action" in r.reason

def test_e_empty_context():
    r = enforce_statement("가능성이 있습니다", {})
    assert r.status == "PASS"
    assert r.label == "E"

def test_a_valid_context(tmp_path):
    evidence = tmp_path / "VR-0001.json"
    evidence.write_text("{}")
    vr = {"status": "PASS", "checked_at": datetime.now(timezone.utc).isoformat(), "ttl_sec": 30}
    ctx = {
        "receipt": {"receipt_id": "VR-0001"},
        "verifier_result": vr,
        "evidence_paths": [str(evidence)],
    }
    r = enforce_statement("완료되었습니다", ctx)
    assert r.status == "PASS"
    assert r.label == "A"

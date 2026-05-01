import pytest
from datetime import datetime, timezone, timedelta
from tools.eps_v1_4.context_schema import verifier_is_fresh

def fresh_vr(delta_sec=0, status="PASS", ttl=30, checked_at=None, include_ttl=True):
    vr = {"status": status}
    if checked_at is not False:
        vr["checked_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delta_sec)).isoformat()
    if include_ttl:
        vr["ttl_sec"] = ttl
    return {"verifier_result": vr}

def test_pass_fresh():
    assert verifier_is_fresh(fresh_vr()) is True

def test_pass_expired():
    assert verifier_is_fresh(fresh_vr(delta_sec=-60, ttl=30)) is False

def test_pass_malformed_timestamp():
    ctx = {"verifier_result": {"status": "PASS", "checked_at": "not-a-date", "ttl_sec": 30}}
    assert verifier_is_fresh(ctx) is False

def test_fail_fresh():
    assert verifier_is_fresh(fresh_vr(status="FAIL")) is False

def test_pass_missing_ttl():
    assert verifier_is_fresh(fresh_vr(include_ttl=False)) is False

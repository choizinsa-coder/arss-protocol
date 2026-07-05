import pytest
from datetime import datetime, timezone, timedelta
from tools.governance.area_6_decl_to_op import DeclToOpEngine, WORK_TYPE_SLA_DEFAULTS, APPROACHING_THRESHOLD_SECONDS

def _engine(tmp_path):
    return DeclToOpEngine(log_dir=tmp_path)

def test_sla_hc_none(tmp_path):
    e = _engine(tmp_path)
    wi = e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="hc")
    assert wi["sla_deadline"] is None
    assert wi["escalate_at"] is None

def test_sla_default_optin(tmp_path):
    e = _engine(tmp_path)
    wi = e.create_workitem(parent_decision="D-1", actor="domi", work_type="DESIGN", title="d", apply_default_sla=True)
    assert wi["sla_deadline"] is not None
    dt = datetime.fromisoformat(wi["sla_deadline"])
    delta = dt - datetime.now(timezone.utc)
    assert timedelta(hours=71) < delta <= timedelta(hours=72)

def test_sla_explicit(tmp_path):
    e = _engine(tmp_path)
    wi = e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="x", sla_deadline="2026-12-31T23:59:59+00:00")
    assert wi["sla_deadline"] == "2026-12-31T23:59:59+00:00"

def test_sla_escalate(tmp_path):
    e = _engine(tmp_path)
    wi = e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="esc", escalate_at="2026-12-30T00:00:00+00:00")
    assert wi["escalate_at"] == "2026-12-30T00:00:00+00:00"

def test_sla_default_unknown_type_none(tmp_path):
    e = _engine(tmp_path)
    wi = e.create_workitem(parent_decision="D-1", actor="caddy", work_type="REVIEW", title="rv", apply_default_sla=True)
    assert wi["sla_deadline"] is not None

def test_sla_alerts_overdue(tmp_path):
    e = _engine(tmp_path)
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="od", sla_deadline=past)
    res = e._check_sla_alerts()
    assert res["has_alerts"] is True
    assert len(res["overdue"]) == 1
    assert res["overdue"][0]["alert_type"] == "overdue"
    assert res["overdue"][0]["workitem_id"] is not None

def test_sla_alerts_approaching(tmp_path):
    e = _engine(tmp_path)
    soon = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="ap", sla_deadline=soon)
    res = e._check_sla_alerts()
    assert res["has_alerts"] is True
    assert len(res["approaching"]) == 1
    assert res["approaching"][0]["alert_type"] == "approaching"

def test_sla_alerts_none(tmp_path):
    e = _engine(tmp_path)
    e.create_workitem(parent_decision="D-1", actor="caddy", work_type="IMPLEMENT", title="no")
    res = e._check_sla_alerts()
    assert res["has_alerts"] is False
    assert res["overdue"] == []
    assert res["approaching"] == []


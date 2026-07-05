import pytest
from tools.governance.area_2_vps_autoguard import VPSAutoGuard, AutoGuardError

def _guard(tmp_path):
    return VPSAutoGuard(log_dir=tmp_path)

def test_autoiso_backward_compatible(tmp_path):
    g = _guard(tmp_path)
    ev = g.record_security_event("service_down", "HIGH", "bridge down", "tcp://bridge")
    alert = g.generate_security_alert(event_ref=ev["id"], description="d", priority="HIGH")
    assert alert["auto_isolation"] is None
    assert alert["status"] == "pending_review"

def test_autoiso_optin_not_triggered_high(tmp_path):
    g = _guard(tmp_path)
    alert = g.generate_security_alert(event_ref="SE-x", description="d", priority="HIGH", auto_request_isolation=True, isolation_service="bridge")
    assert alert["auto_isolation"] is None

def test_autoiso_optin_triggered_critical(tmp_path):
    g = _guard(tmp_path)
    alert = g.generate_security_alert(event_ref="SE-x", description="crit", priority="CRITICAL", auto_request_isolation=True, isolation_service="exec")
    assert alert["auto_isolation"] is not None
    assert alert["auto_isolation"].startswith("ISO-")

def test_autoiso_invalid_service_isolated(tmp_path):
    g = _guard(tmp_path)
    alert = g.generate_security_alert(event_ref="SE-x", description="d", priority="CRITICAL", auto_request_isolation=True, isolation_service="invalid_svc")
    assert alert["auto_isolation"] is None
    assert alert["status"] == "pending_review"

def test_autoiso_no_service(tmp_path):
    g = _guard(tmp_path)
    alert = g.generate_security_alert(event_ref="SE-x", description="d", priority="CRITICAL", auto_request_isolation=True)
    assert alert["auto_isolation"] is None

def test_autoiso_creates_iso_log(tmp_path):
    g = _guard(tmp_path)
    g.generate_security_alert(event_ref="SE-x", description="d", priority="CRITICAL", auto_request_isolation=True, isolation_service="domi")
    iso_log = tmp_path / "isolation_request_log.jsonl"
    assert iso_log.exists()
    lines = [l for l in iso_log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1

def test_should_auto_request_isolation(tmp_path):
    g = _guard(tmp_path)
    assert g._should_auto_request_isolation("CRITICAL") is True
    assert g._should_auto_request_isolation("HIGH") is False


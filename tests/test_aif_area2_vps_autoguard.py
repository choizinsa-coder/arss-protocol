#!/usr/bin/env python3
"""
test_aif_area2_vps_autoguard.py
AIF Area 2: VPS AutoGuard test suite (12 tests)
EAG: EAG-S324-AIF-AREA2-001
"""
import pytest
from unittest.mock import patch

import tools.governance.area_2_vps_autoguard as m2
from tools.governance.area_2_vps_autoguard import (
    AutoGuardError,
    VPSAutoGuard,
    VERSION,
    EAG_ID,
    EAG_ID_P2,
    AIBA_PORTS,
    VALID_SERVICES,
)


# 01: record_security_event basic
def test_01_record_security_event_basic(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    ev = guard.record_security_event(
        event_type="service_down",
        severity="HIGH",
        description="Port 8443 bridge unreachable",
        source="tcp://127.0.0.1:8443",
    )
    assert ev["id"].startswith("SE-")
    assert ev["schema"] == "security_event_v1"
    assert ev["version"] == VERSION
    assert ev["event_type"] == "service_down"
    assert ev["severity"] == "HIGH"
    assert ev["eag"] == EAG_ID
    assert "recorded_at" in ev


# 02: record_security_event invalid event_type
def test_02_record_security_event_invalid_event_type(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with pytest.raises(AutoGuardError, match="event_type"):
        guard.record_security_event(
            event_type="INVALID",
            severity="HIGH",
            description="test",
            source="test",
        )


# 03: record_security_event invalid severity
def test_03_record_security_event_invalid_severity(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with pytest.raises(AutoGuardError, match="severity"):
        guard.record_security_event(
            event_type="service_down",
            severity="EXTREME",
            description="test",
            source="test",
        )


# 04: record_security_event empty description
def test_04_record_security_event_empty_description(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with pytest.raises(AutoGuardError, match="description"):
        guard.record_security_event(
            event_type="unknown",
            severity="LOW",
            description="   ",
            source="test",
        )


# 05: check_service_health port down records event
def test_05_check_service_health_port_down_records_event(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with patch.object(m2, "_check_port", return_value=False):
        result = guard.check_service_health()
    assert all(not v["actual"] for v in result.values())
    events = guard._load_events()
    assert len(events) == len(AIBA_PORTS)
    assert all(e["event_type"] == "service_down" for e in events)
    assert all(e["severity"] == "HIGH" for e in events)


# 06: check_service_health port up no event
def test_06_check_service_health_port_up_no_event(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with patch.object(m2, "_check_port", return_value=True):
        result = guard.check_service_health()
    assert all(v["actual"] for v in result.values())
    assert len(guard._load_events()) == 0


# 07: check_file_integrity existing file
def test_07_check_file_integrity_existing_file(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"AIBA test content for integrity check")
    result = guard.check_file_integrity([str(test_file)])
    assert str(test_file) in result
    assert result[str(test_file)] is not None
    assert len(result[str(test_file)]) == 64  # SHA-256 hex length


# 08: check_file_integrity missing file
def test_08_check_file_integrity_missing_file(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    missing = str(tmp_path / "nonexistent.py")
    result = guard.check_file_integrity([missing])
    assert result[missing] is None


# 09: detect_rc_pattern_threat no threats
def test_09_detect_rc_pattern_threat_no_threats(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    no_alert = {"has_alert": False, "consecutive_repeat": [], "frequency_burst": [], "cross_component": []}
    with patch.object(m2, "_get_failure_patterns", return_value=no_alert):
        with patch.object(m2, "_get_failures_by_rc", return_value=[]):
            result = guard.detect_rc_pattern_threat()
    assert result == []
    assert len(guard._load_events()) == 0


# 10: detect_rc_pattern_threat with RC-3 patterns
def test_10_detect_rc_pattern_threat_with_rc_patterns(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    alert_patterns = {
        "has_alert": True,
        "consecutive_repeat": [{"component": "caddy", "error_code": "CB-001", "count": 3}],
        "frequency_burst": [],
        "cross_component": [],
    }
    fake_rc3 = [{"rc": "RC-3", "component": "caddy", "error_code": "CB-001", "description": "critical"}]
    with patch.object(m2, "_get_failure_patterns", return_value=alert_patterns):
        with patch.object(m2, "_get_failures_by_rc", side_effect=[fake_rc3, []]):
            result = guard.detect_rc_pattern_threat()
    assert len(result) == 1
    assert result[0]["rc"] == "RC-3/RC-4"
    assert result[0]["count"] == 1
    events = guard._load_events()
    assert len(events) == 1
    assert events[0]["event_type"] == "rc_pattern"
    assert events[0]["severity"] == "CRITICAL"


# 11: generate_security_alert basic
def test_11_generate_security_alert_basic(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    ev = guard.record_security_event("service_down", "HIGH", "bridge down", "tcp://bridge")
    alert = guard.generate_security_alert(
        event_ref=ev["id"],
        description="Bridge service unreachable for 5 minutes",
        priority="HIGH",
    )
    assert alert["id"].startswith("SA-")
    assert alert["schema"] == "security_alert_v1"
    assert alert["status"] == "pending_review"
    assert alert["auto_isolation"] is None
    assert alert["priority"] == "HIGH"
    assert alert["event_ref"] == ev["id"]


# 12: get_security_summary
def test_12_get_security_summary(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    guard.record_security_event("service_down", "HIGH",     "bridge down",    "tcp://bridge")
    guard.record_security_event("rc_pattern",   "CRITICAL", "RC-3 detected",  "area_15")
    guard.record_security_event("service_down", "HIGH",     "jeni down",      "tcp://jeni")
    summary = guard.get_security_summary()
    assert summary["schema"] == "security_summary_v1"
    assert summary["total_events"] == 3
    assert summary["by_severity"]["HIGH"] == 2
    assert summary["by_severity"]["CRITICAL"] == 1
    assert summary["by_event_type"]["service_down"] == 2
    assert summary["by_event_type"]["rc_pattern"] == 1
    assert len(summary["recent_5"]) == 3

# ===== Phase 2 Tests (EAG-S327-AIF-AREA2-P2-001) =====

# 13: request_isolation basic
def test_13_request_isolation_basic(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    result = guard.request_isolation(
        service_name="bridge",
        reason="Unexpected file change detected",
        priority="CRITICAL",
    )
    assert result["id"].startswith("ISO-")
    assert result["schema"] == "isolation_request_v1"
    assert result["service_name"] == "bridge"
    assert result["priority"] == "CRITICAL"
    assert result["status"] == "pending_eag"
    assert result["eag"] == EAG_ID_P2
    iso_log = tmp_path / "isolation_request_log.jsonl"
    assert iso_log.exists()
    lines = [l for l in iso_log.read_text().splitlines() if l.strip()]
    assert len(lines) == 1

# 14: request_isolation invalid service_name
def test_14_request_isolation_invalid_service(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with pytest.raises(AutoGuardError, match="service_name"):
        guard.request_isolation(
            service_name="INVALID",
            reason="test reason",
            priority="HIGH",
        )

# 15: request_isolation empty reason
def test_15_request_isolation_empty_reason(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    with pytest.raises(AutoGuardError, match="reason"):
        guard.request_isolation(
            service_name="domi",
            reason="   ",
            priority="MEDIUM",
        )

# 16: request_isolation all valid services
def test_16_request_isolation_all_services(tmp_path):
    guard = VPSAutoGuard(log_dir=tmp_path)
    for svc in sorted(VALID_SERVICES):
        r = guard.request_isolation(service_name=svc, reason=f"{svc} test", priority="LOW")
        assert r["service_name"] == svc
        assert r["status"] == "pending_eag"

"""test_model_probe.py — 모델 폐기 자동 감시 테스트.
EAG-S363-MODEL-PROBE-IMPL-001
대상: tools/monitor/model_probe.py + aiba_monitor._check_model_availability_trigger."""
import json

from tools.monitor.model_probe import (
    classify, ModelProbeEngine, ProbeResult, _is_preview,
    STATUS_OK, STATUS_DEPRECATED, STATUS_TRANSIENT, STATUS_AUTH_ERROR,
    STATUS_RATE_LIMITED, STATUS_UNKNOWN, STATUS_PROBE_UNREACHABLE,
)

_NOW = "2026-07-10T00:00:00+00:00"


def test_classify_ok():
    assert classify(200, "") == STATUS_OK
    assert classify(201, "") == STATUS_OK


def test_classify_gemini_404_deprecated():
    assert classify(404, "model gemini-2.5-flash not found") == STATUS_DEPRECATED


def test_classify_deepseek_400_deprecated():
    assert classify(400, "Model Not Exist") == STATUS_DEPRECATED
    assert classify(400, "model foo does not exist") == STATUS_DEPRECATED
    assert classify(400, "invalid model: bar") == STATUS_DEPRECATED


def test_classify_404_transient():
    assert classify(404, "temporary routing error") == STATUS_TRANSIENT


def test_classify_400_unknown():
    assert classify(400, "malformed json body") == STATUS_UNKNOWN


def test_classify_auth():
    assert classify(401, "invalid key") == STATUS_AUTH_ERROR
    assert classify(403, "forbidden") == STATUS_AUTH_ERROR


def test_classify_rate_limited():
    assert classify(429, "too many requests") == STATUS_RATE_LIMITED


def test_classify_transient_5xx_timeout():
    assert classify(503, "unavailable") == STATUS_TRANSIENT
    assert classify(500, "internal") == STATUS_TRANSIENT
    assert classify(0, "timeout") == STATUS_TRANSIENT


def test_classify_unknown_code():
    assert classify(418, "teapot") == STATUS_UNKNOWN


def test_deprecations_filter():
    results = [
        ProbeResult("jeni", "primary", "g", STATUS_OK, 200, "", _NOW),
        ProbeResult("jeni", "escalate", "g2", STATUS_DEPRECATED, 404, "not found", _NOW),
        ProbeResult("domi", "primary", "d", STATUS_AUTH_ERROR, 401, "bad key", _NOW),
        ProbeResult("domi", "escalate", "d2", STATUS_TRANSIENT, 503, "busy", _NOW),
        ProbeResult("domi", "primary", "d3", STATUS_RATE_LIMITED, 429, "rl", _NOW),
    ]
    alerting = ModelProbeEngine.deprecations(results)
    assert len(alerting) == 2
    assert {r.status for r in alerting} == {STATUS_DEPRECATED, STATUS_AUTH_ERROR}


def test_probe_unreachable_not_alerting():
    results = [ProbeResult("jeni", "unknown", "", STATUS_PROBE_UNREACHABLE, 0, "down", _NOW)]
    assert ModelProbeEngine.deprecations(results) == []


def test_build_alert_detail_schema_and_priority():
    alerting = [
        ProbeResult("domi", "primary", "d", STATUS_DEPRECATED, 400, "Model Not Exist", _NOW),
        ProbeResult("jeni", "escalate_preview", "gp", STATUS_DEPRECATED, 404, "not found", _NOW),
    ]
    detail = json.loads(ModelProbeEngine.build_alert_detail(alerting))
    assert detail["source"] == "Model_Deprecation"
    assert "probed_at" in detail
    assert len(detail["agents"]) == 2
    for k in ("agent", "model_name", "model_type", "http_status", "status", "reason", "priority"):
        assert k in detail["agents"][0]
    prios = {a["model_type"]: a["priority"] for a in detail["agents"]}
    assert prios["primary"] == "high"
    assert prios["escalate_preview"] == "normal"


def test_is_preview():
    assert _is_preview("gemini-3.1-pro-preview") is True
    assert _is_preview("gemini-3.1-flash-lite") is False


def test_probe_agent_unreachable_failsafe():
    eng = ModelProbeEngine(timeout=1)
    res = eng._probe_agent("jeni", "http://127.0.0.1:1/probe")
    assert len(res) == 1
    assert res[0].status == STATUS_PROBE_UNREACHABLE
    assert ModelProbeEngine.deprecations(res) == []


def test_monitor_trigger_fired_and_throttle(tmp_path, monkeypatch):
    import tools.monitor.aiba_monitor as mon_mod
    from tools.monitor import model_probe as mp
    state = tmp_path / "state.json"
    monkeypatch.setattr(mon_mod, "MODEL_PROBE_STATE_PATH", state)

    def fake_probe_all(self):
        return [ProbeResult("domi", "primary", "dead", STATUS_DEPRECATED,
                            400, "Model Not Exist", _NOW)]
    monkeypatch.setattr(mp.ModelProbeEngine, "probe_all", fake_probe_all)

    m = mon_mod.GovernanceMonitor()
    t1 = m._check_model_availability_trigger()
    assert t1["fired"] is True
    assert t1["trigger"] == "Model_Deprecation"
    detail = json.loads(t1["detail"])
    assert detail["agents"][0]["agent"] == "domi"

    t2 = m._check_model_availability_trigger()
    assert t2["fired"] is False
    assert t2["detail"] == "throttled"


def test_monitor_trigger_all_ok_no_fire(tmp_path, monkeypatch):
    import tools.monitor.aiba_monitor as mon_mod
    from tools.monitor import model_probe as mp
    state = tmp_path / "state2.json"
    monkeypatch.setattr(mon_mod, "MODEL_PROBE_STATE_PATH", state)

    def fake_ok(self):
        return [ProbeResult("jeni", "primary", "g", STATUS_OK, 200, "", _NOW)]
    monkeypatch.setattr(mp.ModelProbeEngine, "probe_all", fake_ok)

    m = mon_mod.GovernanceMonitor()
    t = m._check_model_availability_trigger()
    assert t["fired"] is False

import importlib
import sys

sys.path.insert(0, "/opt/arss/engine/arss-protocol")


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("AIBA_GCB_NO_PROGRESS_N", "5")
    monkeypatch.setenv("AIBA_GCB_CASCADE_WINDOW", "60")
    monkeypatch.setenv("AIBA_GCB_CASCADE_MIN", "2")
    import tools.governance.global_circuit_breaker as gcb
    importlib.reload(gcb)
    gcb.GCB_STATE_PATH = str(tmp_path / "gcb_state.json")
    return gcb


def test_default_state_closed(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    assert gcb.is_tripped() is False
    assert gcb.gcb_check() is False


def test_no_progress_trips_at_threshold(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    for _ in range(4):
        gcb.report_no_progress("domi")
    assert gcb.is_tripped() is False
    gcb.report_no_progress("domi")
    assert gcb.is_tripped() is True
    assert gcb.get_state()["reason"] == "NO_PROGRESS_REPETITION"


def test_progress_resets_counter(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    for _ in range(4):
        gcb.report_no_progress("domi")
    gcb.report_progress("domi")
    for _ in range(4):
        gcb.report_no_progress("domi")
    assert gcb.is_tripped() is False


def test_cascade_trips_two_components(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    gcb.report_failure("domi")
    assert gcb.is_tripped() is False
    gcb.report_failure("jeni")
    assert gcb.is_tripped() is True
    assert gcb.get_state()["reason"] == "CASCADING_FAILURE_NO_RECOVERY"


def test_single_component_failure_no_trip(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    gcb.report_failure("domi")
    gcb.report_failure("domi")
    gcb.report_failure("domi")
    assert gcb.is_tripped() is False


def test_reset_requires_eag(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    gcb.report_failure("domi")
    gcb.report_failure("jeni")
    assert gcb.is_tripped() is True
    raised = False
    try:
        gcb.gcb_reset("not-an-eag")
    except ValueError:
        raised = True
    assert raised is True
    assert gcb.is_tripped() is True


def test_reset_with_eag_clears(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    gcb.report_failure("domi")
    gcb.report_failure("jeni")
    assert gcb.is_tripped() is True
    gcb.gcb_reset("EAG-S335-GCB-RESET-TEST")
    assert gcb.is_tripped() is False
    assert gcb.get_state()["reset_by"] == "EAG-S335-GCB-RESET-TEST"


def test_no_autoresume_after_trip(tmp_path, monkeypatch):
    gcb = _fresh(tmp_path, monkeypatch)
    gcb.report_failure("domi")
    gcb.report_failure("jeni")
    assert gcb.is_tripped() is True
    gcb.report_progress("domi")
    gcb.report_no_progress("domi")
    assert gcb.is_tripped() is True

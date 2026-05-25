import pytest
from tools.session_context_gen.state_events_normalizer import (
    normalize_events, StateEventsNormalizerError
)


def test_T6_normalization_zero_data_loss():
    """T6: state_events normalization — zero data loss verified."""
    events = [
        {
            "event_id": "evt-001",
            "event_type": "RPU_CREATED",
            "event_time": "2026-04-21T00:00:00Z",
            "actor": "caddy",
            "source": "test",
            "status": "PASS",
            "payload_ref": "/path/to/payload",
            "execution_receipt_ref": "EX-001",
            "verification_receipt_ref": "VR-001",
            "notes": {"existing_note": "value"},
            "custom_field": "custom_value",
            "extra_data": {"nested": True},
        }
    ]
    result = normalize_events(events)
    assert len(result) == 1
    e = result[0]

    assert e["event_id"] == "evt-001"
    assert e["event_type"] == "RPU_CREATED"
    assert e["event_time"] == "2026-04-21T00:00:00Z"
    assert e["actor"] == "caddy"
    assert e["source"] == "test"
    assert e["status"] == "PASS"
    assert e["payload_ref"] == "/path/to/payload"
    assert e["execution_receipt_ref"] == "EX-001"
    assert e["verification_receipt_ref"] == "VR-001"
    assert e["notes"]["existing_note"] == "value"

    assert "raw_payload" in e["notes"]
    assert e["notes"]["raw_payload"]["custom_field"] == "custom_value"
    assert e["notes"]["raw_payload"]["extra_data"] == {"nested": True}


def test_normalization_empty_list():
    result = normalize_events([])
    assert result == []


def test_normalization_none_raises():
    with pytest.raises(StateEventsNormalizerError):
        normalize_events(None)


def test_normalization_non_dict_event_raises():
    with pytest.raises(StateEventsNormalizerError):
        normalize_events(["not_a_dict"])


def test_normalization_no_unmapped_fields():
    events = [{"event_id": "e1", "event_type": "TEST", "notes": {"k": "v"}}]
    result = normalize_events(events)
    assert result[0]["event_id"] == "e1"
    assert "raw_payload" not in result[0]["notes"]


def test_normalization_none_notes_becomes_dict():
    events = [{"event_id": "e1", "event_type": "TEST"}]
    result = normalize_events(events)
    assert isinstance(result[0]["notes"], dict)

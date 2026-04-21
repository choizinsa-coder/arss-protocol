from typing import Any, Dict, List


class StateEventsNormalizerError(Exception):
    pass


_CANONICAL_FIELDS = frozenset({
    "event_id", "event_type", "event_time", "actor", "source",
    "status", "payload_ref", "execution_receipt_ref",
    "verification_receipt_ref", "notes",
})


def normalize_events(events_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize events to canonical schema.
    Existing data MUST NOT be deleted.
    Unmapped fields preserved in notes.raw_payload.
    Raises StateEventsNormalizerError on failure (FAIL-CLOSED).
    """
    if events_list is None:
        raise StateEventsNormalizerError("events_list is None")

    normalized = []
    for i, event in enumerate(events_list):
        if not isinstance(event, dict):
            raise StateEventsNormalizerError(
                f"Event at index {i} is not a dict: {type(event).__name__}"
            )
        try:
            existing_notes = event.get("notes")
            if existing_notes is None:
                existing_notes = {}
            elif not isinstance(existing_notes, dict):
                existing_notes = {"_original": existing_notes}
            else:
                existing_notes = dict(existing_notes)

            unmapped = {k: v for k, v in event.items() if k not in _CANONICAL_FIELDS}
            if unmapped:
                existing_notes["raw_payload"] = unmapped

            canonical = {
                "event_id": event.get("event_id"),
                "event_type": event.get("event_type"),
                "event_time": event.get("event_time"),
                "actor": event.get("actor"),
                "source": event.get("source"),
                "status": event.get("status"),
                "payload_ref": event.get("payload_ref"),
                "execution_receipt_ref": event.get("execution_receipt_ref"),
                "verification_receipt_ref": event.get("verification_receipt_ref"),
                "notes": existing_notes,
            }
            normalized.append(canonical)
        except StateEventsNormalizerError:
            raise
        except Exception as e:
            raise StateEventsNormalizerError(
                f"Normalization failed at index {i}: {e}"
            )

    return normalized

"""EventEnvelope foundation contract tests."""

from nous_runtime.core.events import EventEnvelope
from nous_runtime.events import EventEnvelope as PublicEventEnvelope


def test_event_envelope_generates_identity_and_utc_timestamp():
    event = EventEnvelope(
        event_type="task.completed",
        source="executor",
        payload={"id": "123"},
    )

    assert event.event_id.startswith("evt_")
    assert event.timestamp.endswith("Z")
    assert event.event_type == "task.completed"
    assert event.source == "executor"


def test_event_envelope_round_trip_preserves_all_fields():
    event = EventEnvelope(
        event_id="evt-fixed",
        event_type="decision.recorded",
        source="intelligence",
        timestamp="2026-07-21T00:00:00.000Z",
        payload={"decision_id": "decision-1"},
        metadata={"trace_id": "trace-1"},
    )

    restored = EventEnvelope.from_dict(event.to_dict())

    assert restored == event
    assert restored.payload is not event.payload
    assert restored.metadata is not event.metadata


def test_event_envelope_accepts_legacy_aliases():
    event = EventEnvelope.from_dict(
        {
            "id": "legacy-event",
            "type": "memory.updated",
            "actor": "memory",
            "payload": {"id": "memory-1"},
        }
    )

    assert event.event_id == "legacy-event"
    assert event.event_type == "memory.updated"
    assert event.source == "memory"
    assert event.metadata == {}


def test_event_package_exports_foundation_envelope_without_replacing_run_event():
    assert PublicEventEnvelope is EventEnvelope

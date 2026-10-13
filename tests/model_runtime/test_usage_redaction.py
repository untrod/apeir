"""Usage evidence survives the existing redactor without a string escape hatch."""

import json
import uuid

import pytest

from nous_runtime.core.redaction import (
    REDACTED,
    redact_sensitive_data,
    register_sensitive_value,
)
from nous_runtime.events import EventStream, RunEvent


COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_miss_input_tokens",
    "reasoning_tokens",
    "total_tokens",
    "cache_creation_input_tokens",
)


def test_nullable_usage_and_bounded_measurements_survive_real_jsonl_reload(tmp_path):
    values = {counter: None for counter in COUNTERS}
    values["input_tokens"] = 0
    values["counter_measurements"] = {
        counter: "reported" if counter == "input_tokens" else "unknown"
        for counter in COUNTERS
    }
    original = EventStream(str(tmp_path))
    original.emit(
        RunEvent(
            run_id="usage-evidence",
            task_id="task",
            event_type="model.invocation.completed",
            payload={"usage": values},
        )
    )
    reopened = EventStream(str(tmp_path))
    event = reopened.load_events("usage-evidence")[0]
    assert event.payload["usage"] == values
    persisted = tmp_path / ".nous" / "events" / "usage-evidence.jsonl"
    assert json.loads(persisted.read_text())["payload"]["usage"] == values


@pytest.mark.parametrize("label", ["reported", "derived", "estimated", "unknown"])
def test_only_normalized_usage_measurement_labels_are_preserved(label):
    value = {"counter_measurements": {counter: label for counter in COUNTERS}}
    assert redact_sensitive_data(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"input_tokens": None},
        {"input_tokens": 0},
        {"input_tokens": "invalid-label"},
        {"input_tokens": "reported", "unknown_counter": "unknown"},
        {"secretlike_token": "reported"},
    ],
)
def test_malformed_measurements_are_redacted_as_a_whole(value):
    assert redact_sensitive_data({"counter_measurements": value}) == {
        "counter_measurements": REDACTED
    }


def test_counter_names_cannot_carry_fake_secret_strings_or_unknown_null_fields(
    tmp_path,
):
    fake_material = "apeir-fake-usage-material-" + uuid.uuid4().hex
    register_sensitive_value(fake_material)
    value = {
        **{counter: fake_material for counter in COUNTERS},
        "secretlike_token": fake_material,
        "unrecognized_tokens": None,
        "counter_measurements": {"input_tokens": fake_material},
        "diagnostic": fake_material,
    }
    assert all(item == REDACTED for item in redact_sensitive_data(value).values())
    EventStream(str(tmp_path)).emit(
        RunEvent(
            run_id="bad-usage",
            task_id="task",
            event_type="model.invocation.completed",
            payload=value,
        )
    )
    persisted = tmp_path / ".nous" / "events" / "bad-usage.jsonl"
    assert fake_material not in persisted.read_text()
    event = EventStream(str(tmp_path)).load_events("bad-usage")[0]
    assert all(item == REDACTED for item in event.payload.values())

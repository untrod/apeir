from __future__ import annotations

import json
import time

import pytest

from nous_runtime.events import EventStream, EventStreamError, RunEvent
from nous_runtime.locking import DomainLockManager, LockTimeoutError


def test_event_stream_rejects_run_id_path_escape(tmp_path):
    stream = EventStream(str(tmp_path))

    with pytest.raises(EventStreamError, match="Invalid run_id"):
        stream.emit(RunEvent(run_id="../escape", event_type="run.started"))

    assert not (tmp_path / ".nous" / "escape.jsonl").exists()


def test_event_stream_restores_sequence_after_restart(tmp_path):
    first = EventStream(str(tmp_path))
    first.emit(RunEvent(run_id="run_1", event_type="run.started"))

    restarted = EventStream(str(tmp_path))
    event = restarted.emit(RunEvent(run_id="run_1", event_type="run.completed"))

    assert event.sequence == 2
    assert [item.sequence for item in restarted.load_events("run_1")] == [1, 2]


def test_event_stream_reuses_duplicate_event_after_restart(tmp_path):
    original = RunEvent(
        event_id="event-fixed",
        run_id="run_1",
        event_type="command.output",
        payload={"value": "original"},
    )
    first = EventStream(str(tmp_path)).emit(original)

    duplicate = EventStream(str(tmp_path)).emit(
        RunEvent(
            event_id="event-fixed",
            run_id="run_1",
            event_type="command.output",
            payload={"value": "duplicate"},
        )
    )

    events = EventStream(str(tmp_path)).load_events("run_1")
    assert duplicate.to_dict() == first.to_dict()
    assert len(events) == 1
    assert events[0].payload == {"value": "original"}


def test_event_stream_redacts_nested_list_values(tmp_path):
    stream = EventStream(str(tmp_path))
    stream.emit(
        RunEvent(
            run_id="run_1",
            event_type="command.output",
            payload={"items": [{"api_token": "private-value"}]},
        )
    )

    path = tmp_path / ".nous" / "events" / "run_1.jsonl"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["payload"]["items"][0]["api_token"] == "<REDACTED>"

def _emit_many_events(workspace: str, worker_id: int, count: int) -> None:
    stream = EventStream(workspace)
    for index in range(count):
        stream.emit(
            RunEvent(
                run_id="shared_run",
                event_type="command.output",
                payload={"worker": worker_id, "index": index},
            )
        )


def test_event_stream_is_process_safe(tmp_path):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_emit_many_events, args=(str(tmp_path), worker_id, 10))
        for worker_id in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        try:
            process.join(timeout=10)
            assert not process.is_alive(), "event writer process did not terminate"
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)

    events = EventStream(str(tmp_path)).load_events("shared_run")
    sequences = sorted(event.sequence for event in events)
    assert len(events) == 40
    assert sequences == list(range(1, 41))


def test_persistence_failure_does_not_consume_sequence(tmp_path, monkeypatch):
    stream = EventStream(str(tmp_path))
    original = stream._persist_event_unlocked

    def fail_once(event):
        raise EventStreamError("disk unavailable")

    monkeypatch.setattr(stream, "_persist_event_unlocked", fail_once)
    with pytest.raises(EventStreamError, match="disk unavailable"):
        stream.emit(RunEvent(run_id="run_1", event_type="run.started"))

    monkeypatch.setattr(stream, "_persist_event_unlocked", original)
    event = stream.emit(RunEvent(run_id="run_1", event_type="run.started"))

    assert event.sequence == 1
    assert [item.sequence for item in stream.load_events("run_1")] == [1]


def test_event_stream_coalesces_only_progress_and_preserves_critical_events(tmp_path):
    stream = EventStream(str(tmp_path), buffer_size=3, max_persisted=3)
    for index in range(4):
        stream.emit(
            RunEvent(
                run_id="run_1",
                event_type="step.progress",
                payload={"step_id": "step", "percent": index * 25},
            )
        )
    stream.emit(RunEvent(run_id="run_1", event_type="approval.requested"))
    stream.emit(RunEvent(run_id="run_1", event_type="run.completed"))

    expected_types = [
        "step.progress",
        "approval.requested",
        "run.completed",
    ]
    assert [event.event_type for event in stream.get_events("run_1")] == expected_types
    assert [event.event_type for event in stream.load_events("run_1")] == expected_types
    assert stream.get_stats()["metrics"]["coalesced_progress_count"] == 3


def test_event_stream_chunks_unicode_without_data_loss(tmp_path):
    stream = EventStream(str(tmp_path), chunk_bytes=256)
    content = "标准输出🙂" * 100

    chunks = stream.emit_chunked(
        RunEvent(
            run_id="run_1",
            event_type="command.output",
            payload={"stream": "stdout", "text": content},
        )
    )

    assert len(chunks) > 1
    assert "".join(chunk.payload["text"] for chunk in chunks) == content
    assert all(
        len(chunk.payload["text"].encode("utf-8")) <= 256
        for chunk in chunks
    )


def test_event_stream_listener_bounds_backpressure_and_failure_metrics(tmp_path):
    stream = EventStream(
        str(tmp_path),
        max_listeners_per_run=1,
        slow_consumer_seconds=0.001,
    )

    def slow_failure(event):
        time.sleep(0.005)
        raise RuntimeError("consumer failed")

    stream.subscribe("run_1", slow_failure)
    stream.subscribe("run_1", slow_failure)
    with pytest.raises(EventStreamError, match="Listener limit"):
        stream.subscribe("run_1", lambda event: None)

    stream.emit(RunEvent(run_id="run_1", event_type="run.started"))
    metrics = stream.get_stats()["metrics"]

    assert metrics["listener_failure_count"] == 1
    assert metrics["slow_consumer_count"] == 1
    assert metrics["queue_depth"] == 1


def test_event_index_snapshot_and_replay_metrics(tmp_path):
    stream = EventStream(str(tmp_path))
    for event_type in ("run.started", "step.progress", "run.completed"):
        stream.emit(RunEvent(run_id="run_1", event_type=event_type))

    index = stream.event_index("run_1")
    snapshot = stream.create_snapshot("run_1")
    replay = stream.replay_from("run_1", 1)

    assert [record["sequence"] for record in index] == [1, 2, 3]
    assert snapshot["event_count"] == 3
    assert snapshot["last_sequence"] == 3
    assert len(snapshot["sha256"]) == 64
    assert [event.sequence for event in replay] == [2, 3]
    assert stream.get_stats()["metrics"]["replay_lag_events"] == 2


def test_runtime_lock_domains_expose_timeout_evidence():
    manager = DomainLockManager()

    with manager.acquire("workspace:one", owner="writer", timeout=0.1):
        with pytest.raises(LockTimeoutError):
            with manager.acquire(
                "workspace:one", owner="contender", timeout=0.01
            ):
                pass

    evidence = manager.snapshot()["workspace:one"]
    assert evidence["owner"] == "contender"
    assert evidence["timeout"] == 0.01
    assert evidence["wait_time"] >= 0.0
    assert evidence["failure_reason"] == "timeout"

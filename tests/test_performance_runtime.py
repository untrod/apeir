from __future__ import annotations

from nous_runtime.context.builder import CONTEXT_CLASSES, DEFAULT_TOKEN_BUDGETS
from nous_runtime.conversation.stream import ConversationStream, StreamChunk
from nous_runtime.events.models import RunEvent
from nous_runtime.events.stream import EventStream
from nous_runtime.intelligence.cache import SchedulerCache


def test_event_replay_is_streamed_bounded_and_indexed(tmp_path):
    stream = EventStream(str(tmp_path), buffer_size=8)
    for index in range(25):
        stream.emit(
            RunEvent(
                run_id="run_perf",
                event_type="step.progress",
                payload={"index": index},
            )
        )
    replay = list(stream.iter_persisted_events("run_perf", after_sequence=5, limit=7))
    assert [event.sequence for event in replay] == list(range(6, 13))
    assert len(stream.event_index("run_perf")) == 25
    metrics = stream.get_stats()["metrics"]
    assert metrics["streaming_reads"] == 1
    assert metrics["streamed_events"] == 7
    assert stream.get_stats()["total_buffered_events"] <= 8


def test_streaming_ui_and_scheduler_cache_have_hard_memory_bounds():
    visible = ConversationStream(max_visible_chars=12, dedup_window=3)
    for index in range(10):
        visible.accept(StreamChunk(str(index), "abcd"))
    assert len(visible.render()) <= 12
    assert visible.accept(StreamChunk("9", "duplicate")) is False

    cache = SchedulerCache(max_size=3, default_ttl_seconds=60)
    for index in range(10):
        cache.set(str(index), {"value": index})
    assert cache.stats["size"] == 3
    assert cache.stats["max_size"] == 3


def test_context_resource_classes_have_explicit_positive_budgets():
    assert set(CONTEXT_CLASSES) == set(DEFAULT_TOKEN_BUDGETS)
    assert all(value > 0 for value in DEFAULT_TOKEN_BUDGETS.values())

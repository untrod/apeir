from __future__ import annotations

import pytest

from nous_runtime.events.models import RunEvent
from nous_runtime.events.stream import EventStream
from nous_runtime.sdk.developer import RuntimeProfiler, RuntimeReplay, render_template


def test_templates_are_safe_reviewable_and_do_not_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = render_template("capability", "hello_world")
    assert sorted(files) == ["hello_world.py", "test_hello_world.py"]
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ValueError):
        render_template("agent", "../escape")
    with pytest.raises(ValueError):
        render_template("unknown", "safe_name")


def test_replay_is_deterministic_and_terminal_evidence_is_visible(tmp_path):
    stream = EventStream(str(tmp_path))
    stream.emit(RunEvent(run_id="run_sdk", event_type="run.started"))
    stream.emit(RunEvent(run_id="run_sdk", event_type="run.completed"))
    replay = RuntimeReplay(tmp_path)
    first = replay.inspect("run_sdk")
    second = replay.inspect("run_sdk")
    assert first.event_count == 2
    assert first.monotonic is True
    assert first.terminal_events == ("run.completed",)
    assert first.checksum == second.checksum
    assert first.truncated is False


def test_replay_limit_is_explicit(tmp_path):
    stream = EventStream(str(tmp_path))
    for index in range(3):
        stream.emit(
            RunEvent(run_id="run_limit", event_type="step.progress", payload={"index": index})
        )
    report = RuntimeReplay(tmp_path).inspect("run_limit", limit=2)
    assert report.event_count == 2
    assert report.truncated is True
    with pytest.raises(ValueError):
        RuntimeReplay(tmp_path).inspect("run_limit", limit=0)


def test_profiler_reports_latency_memory_and_failures():
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("expected")
        return bytearray(1024)

    report = RuntimeProfiler().profile("smoke", operation, iterations=3)
    assert report.iterations == 3
    assert report.successes == 2
    assert report.failures == 1
    assert report.peak_memory_bytes > 0
    assert report.latency_p99_ms >= 0
    assert report.errors == ("expected",)


def test_profiler_bounds_are_fail_closed():
    with pytest.raises(ValueError):
        RuntimeProfiler().profile("unbounded", lambda: None, iterations=1001)
    with pytest.raises(ValueError):
        RuntimeProfiler().profile("warmup", lambda: None, warmup=21)

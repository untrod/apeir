"""Every test-owned child is reaped even when an earlier writer fails."""

import multiprocessing

import pytest

from tests.test_events_runtime import (
    test_event_stream_is_process_safe as run_writer_probe,
)


def test_writer_probe_failure_cleans_all_started_children(tmp_path, monkeypatch):
    processes = []

    class Process:
        def __init__(self, **kwargs):
            self.alive = False
            self.exitcode = None
            self.pid = len(processes) + 1
            processes.append(self)

        def start(self):
            self.alive = True

        def join(self, timeout):
            assert timeout in {10, 2}

        def is_alive(self):
            return self.alive

        def terminate(self):
            self.alive = False
            self.exitcode = -1

    class Context:
        pass

    Context.Process = Process
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: Context())
    with pytest.raises(AssertionError, match="event writer process did not terminate"):
        run_writer_probe(tmp_path)
    assert len(processes) == 4
    assert all(not process.is_alive() for process in processes)

"""Control observation must not replay a submitted process operation."""

from pathlib import Path

import pytest

from nous_runtime.tools import process_session
from nous_runtime.tools.process_session import ProcessSessionStore
from tests.tools.test_process_session import _start, _wait_state


@pytest.mark.parametrize("read_error", [PermissionError, FileNotFoundError])
def test_control_reobserves_original_ack_after_transient_read_failure(
    tmp_path, monkeypatch, read_error
):
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    directory = store.root / session_id
    original_read = Path.read_text
    failures = []

    def read(path, *args, **kwargs):
        if path.parent == directory / "ack" and path.is_file() and len(failures) < 2:
            failures.append(path.name)
            raise read_error("ack publication is temporarily unreadable")
        return original_read(path, *args, **kwargs)

    try:
        assert started["state"] == "RUNNING", started
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "read_text", read)
            accepted = store.kill(session_id)
        assert accepted["ok"] is True
        assert len(failures) == 2
        assert len(set(failures)) == 1
    finally:
        # Once submitted, observe the original effect instead of sending cleanup
        # signals which could conceal a replay of the operation under test.
        terminal = _wait_state(store, session_id, {"KILLED"})
        assert terminal["state"] == "KILLED", terminal
    requests = list((directory / "control").glob("*.json"))
    assert len(requests) == 1
    assert list((directory / "ack").glob("*.json")) == [
        directory / "ack" / requests[0].name
    ]


def test_unreadable_ack_keeps_original_control_and_requires_observation(
    tmp_path, monkeypatch
):
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    directory = store.root / session_id
    original_read = Path.read_text

    def read(path, *args, **kwargs):
        if path.parent == directory / "ack":
            raise PermissionError("ack remains unreadable")
        return original_read(path, *args, **kwargs)

    try:
        assert started["state"] == "RUNNING", started
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "read_text", read)
            with pytest.raises(
                RuntimeError, match="did not acknowledge the control request"
            ):
                store.kill(session_id)
    finally:
        terminal = _wait_state(store, session_id, {"KILLED"})
        assert terminal["state"] == "KILLED", terminal
    recovered = ProcessSessionStore(tmp_path).recover(session_id=session_id)
    assert recovered["state"] == "KILLED"
    assert recovered["automatic_replay"] is False
    assert recovered["process_identity"] == started["process_identity"]
    assert len(list((directory / "control").glob("*.json"))) == 1

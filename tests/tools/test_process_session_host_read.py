"""Fresh process observations tolerate a publication read gap without replay."""

import errno
import json
import sys

import pytest

from nous_runtime.tools import process_session
from nous_runtime.tools.process_session import ProcessSession, ProcessSessionStore
from tests.tools.test_process_session import _start
from tests.tools.test_process_session_startup import _cleanup_original_session


@pytest.mark.parametrize(
    ("failure", "message", "control_reason", "attempts"),
    [
        ("missing", "missing", "unavailable", 1),
        ("denied", "unreadable", "unreadable", 3),
        ("io", "read failed", "read_failed", 1),
        ("json", "invalid", "invalid", 1),
        ("encoding", "invalid", "invalid", 1),
        ("array", "invalid", "invalid", 1),
        ("empty", "invalid", "invalid", 1),
    ],
)
def test_unavailable_host_reports_safe_reason_without_authorizing_control(
    tmp_path, monkeypatch, failure, message, control_reason, attempts
):
    store = ProcessSessionStore(tmp_path)
    session_id = "ps_" + "a" * 32
    session = ProcessSession(
        session_id=session_id,
        work_id="work-original",
        tool_call_id="call-original",
        command=["not-launched"],
        cwd=str(tmp_path),
        environment_ref="sha256:" + "b" * 64,
        command_digest=process_session._digest(["not-launched"]),
        state="RUNNING",
        stdin_available=True,
    )
    store._save(session)
    path = store.root / session_id / "host.json"
    original = process_session.Path.read_text
    reads, pauses = [], []

    def read(current, *args, **kwargs):
        if current != path:
            return original(current, *args, **kwargs)
        reads.append(True)
        if failure == "missing":
            raise FileNotFoundError(errno.ENOENT, "private host path")
        if failure == "denied":
            raise PermissionError(errno.EACCES, "private host path")
        if failure == "io":
            raise OSError(errno.EIO, "private host path")
        if failure == "encoding":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "private host payload")
        return {"json": "private invalid payload", "array": "[]", "empty": "{}"}[
            failure
        ]

    monkeypatch.setattr(process_session.Path, "read_text", read)
    monkeypatch.setattr(process_session.time, "sleep", pauses.append)
    attached = store.attach(session_id)
    assert attached["state"] == "RECOVERY_REQUIRED"
    assert attached["stdin_available"] is False
    expected = (
        "process host state read failed"
        if message == "read failed"
        else f"process host state is {message}"
    )
    assert attached["error"].startswith(expected)
    assert "private" not in attached["error"]
    assert str(tmp_path) not in attached["error"]
    assert len(reads) == attempts
    assert pauses == ([0.01, 0.01] if failure == "denied" else [])
    with pytest.raises(ValueError, match=f"reason=host_record_{control_reason}"):
        store.write_stdin(session_id, "must not dispatch\n")
    assert not list(path.parent.rglob("control/*.json"))
    persisted = store.require(session_id)
    assert persisted.work_id == "work-original"
    assert persisted.tool_call_id == "call-original"
    assert persisted.action_sequence == 0


@pytest.mark.parametrize("misses", [1, 2])
def test_attach_reobserves_fresh_host_after_transient_permission_denial(
    tmp_path, monkeypatch, misses
):
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    path = store.root / session_id / "host.json"
    read_text = process_session.Path.read_text
    failed = []
    observations = []

    def read(current, *args, **kwargs):
        if current != path:
            return read_text(current, *args, **kwargs)
        if len(failed) < misses:
            failed.append(True)
            raise PermissionError("host publication is temporarily unreadable")
        try:
            text = read_text(current, *args, **kwargs)
        except OSError as error:
            observation = {
                "error_type": type(error).__name__,
                "errno": error.errno,
                "winerror": getattr(error, "winerror", None),
            }
            if sys.platform == "win32":
                # Reuse the Relay's read-only native access probe: the CRT can
                # discard GetLastError. This later sample cannot certify the
                # failed read or replace it with a successful host observation.
                from nous_runtime.node_runtime.relay import _read_failure_winerror

                try:
                    observation["observed_winerror"] = _read_failure_winerror(
                        current, error
                    )
                except OSError as probe_error:
                    observation["probe_errno"] = probe_error.errno
                    observation["probe_winerror"] = getattr(
                        probe_error, "winerror", None
                    )
            observations.append(observation)
            raise
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            observations.append({"json_valid": False, "characters": len(text)})
        else:
            observations.append(
                {
                    "json_valid": True,
                    "object": isinstance(value, dict),
                    "session_matches": isinstance(value, dict)
                    and value.get("session_id") == session_id,
                    "helper_matches": isinstance(value, dict)
                    and value.get("helper_identity") == started["helper_identity"],
                    "process_matches": isinstance(value, dict)
                    and value.get("process_identity") == started["process_identity"],
                }
            )
        return text

    try:
        assert started["state"] == "RUNNING", started
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "read_text", read)
            attached = ProcessSessionStore(tmp_path).attach(session_id)
        assert attached["state"] == "RUNNING", {
            "state": attached.get("state"),
            "error": attached.get("error"),
            "injected_read_denials": len(failed),
            "fresh_reads": observations,
        }
        assert len(failed) == misses
        assert attached["process_identity"] == started["process_identity"]
        assert attached["helper_identity"] == started["helper_identity"]
        assert not list((path.parent / "control").glob("*.json"))
    finally:
        _cleanup_original_session(store, session_id)


def test_reobserved_host_cannot_reuse_a_prior_valid_binding(tmp_path, monkeypatch):
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    path = store.root / session_id / "host.json"
    read_text = process_session.Path.read_text
    reads = []

    def read(current, *args, **kwargs):
        if current != path:
            return read_text(current, *args, **kwargs)
        reads.append(True)
        if len(reads) == 1:
            raise PermissionError("publication read denied")
        value = json.loads(read_text(current, *args, **kwargs))
        value["helper_identity"]["command_digest"] = "sha256:" + "0" * 64
        return json.dumps(value)

    try:
        assert started["state"] == "RUNNING", started
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "read_text", read)
            attached = ProcessSessionStore(tmp_path).attach(session_id)
            assert attached["state"] == "RECOVERY_REQUIRED"
            assert attached["error"] == "process helper identity changed"
            assert len(reads) == 2
            with pytest.raises(ValueError, match="process session is not running"):
                store.write_stdin(session_id, "not authorized\n")
            assert not list((path.parent / "control").glob("*.json"))
    finally:
        _cleanup_original_session(store, session_id)

"""Fresh process observations tolerate a publication read gap without replay."""

import json

import pytest

from nous_runtime.tools import process_session
from nous_runtime.tools.process_session import ProcessSessionStore
from tests.tools.test_process_session import _start
from tests.tools.test_process_session_startup import _cleanup_original_session


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
            observations.append(
                {
                    "error_type": type(error).__name__,
                    "errno": error.errno,
                    "winerror": getattr(error, "winerror", None),
                }
            )
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

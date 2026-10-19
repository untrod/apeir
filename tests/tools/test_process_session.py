from __future__ import annotations

import json
import hashlib
import os
import sys
import time
from pathlib import Path

import pytest

from nous_runtime.artifact import ContentAddressedArtifactStore
from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.kernel.process_session_host import process_creation_token
from nous_runtime.tools.process_session import (
    ProcessSession,
    ProcessSessionState,
    ProcessSessionStore,
    ProcessSessionToolRuntime,
)


def _start(store: ProcessSessionStore, code: str) -> dict:
    return store.start(
        [sys.executable, "-u", "-c", code],
        cwd=store.workspace,
        environment=dict(os.environ),
        work_id="work-process-test",
        tool_call_id="call-process-test",
        action_sequence=7,
    )


def _wait_state(
    store: ProcessSessionStore,
    session_id: str,
    states: set[str],
    timeout: float = 10.0,
) -> dict:
    deadline = time.monotonic() + timeout
    result = store.status(session_id)
    while result["state"] not in states and time.monotonic() < deadline:
        time.sleep(0.05)
        result = store.status(session_id)
    return result


def _wait_output(
    store: ProcessSessionStore,
    session_id: str,
    stream: str,
    expected: str,
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    result = store.read_output(session_id, stream, cursor=0)
    while expected not in result["text"] and time.monotonic() < deadline:
        time.sleep(0.05)
        result = store.read_output(session_id, stream, cursor=0)
    return result


def test_session_survives_runtime_recreation_and_streams_by_cursor(
    tmp_path: Path,
) -> None:
    first = ProcessSessionStore(tmp_path)
    started = _start(
        first,
        "import sys,time; print('ready', flush=True); "
        "print('warning', file=sys.stderr, flush=True); "
        "line=sys.stdin.readline(); print('received:'+line.strip(), flush=True); "
        "time.sleep(.1)",
    )
    session_id = started["session_id"]
    assert started["state"] == "RUNNING", started

    initial = _wait_output(first, session_id, "stdout", "ready")
    assert initial["next_cursor"] > 0
    assert "warning" in _wait_output(first, session_id, "stderr", "warning")["text"]

    restarted_runtime = ProcessSessionStore(tmp_path)
    attached = restarted_runtime.attach(session_id)
    assert attached["state"] == "RUNNING"
    assert attached["stdin_available"] is True
    assert restarted_runtime.write_stdin(session_id, "hello\n")["ok"] is True

    terminal = _wait_state(restarted_runtime, session_id, {"EXITED"})
    assert terminal["exit_code"] == 0
    assert set(terminal["artifacts"]) == {"stdout", "stderr"}
    remainder = restarted_runtime.read_output(
        session_id, "stdout", cursor=initial["next_cursor"]
    )
    assert "received:hello" in remainder["text"]
    store = ContentAddressedArtifactStore(tmp_path / ".nous" / "artifacts")
    assert store.verify(terminal["artifacts"]["stdout"])
    assert store.verify(terminal["artifacts"]["stderr"])


def test_detach_does_not_stop_process(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import time; print('live', flush=True); time.sleep(30)")
    session_id = started["session_id"]
    try:
        assert store.detach(session_id)["state"] == "RUNNING"
        assert ProcessSessionStore(tmp_path).attach(session_id)["state"] == "RUNNING"
    finally:
        store.kill(session_id)
        assert _wait_state(store, session_id, {"KILLED"})["state"] == "KILLED"


@pytest.mark.parametrize(
    ("operation", "terminal"),
    (("terminate", "TERMINATED"), ("kill", "KILLED")),
)
def test_process_control_has_distinct_terminal_state(
    tmp_path: Path, operation: str, terminal: str
) -> None:
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import time; time.sleep(30)")
    getattr(store, operation)(started["session_id"])
    result = _wait_state(store, started["session_id"], {terminal})
    assert result["state"] == terminal


def test_interrupt_targets_process_group(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import time; time.sleep(30)")
    store.interrupt(started["session_id"])
    result = _wait_state(store, started["session_id"], {"INTERRUPTED"})
    assert result["state"] == "INTERRUPTED"


def test_child_process_is_cleaned_up_with_parent(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    child_code = "import time; time.sleep(30)"
    parent_code = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "print(p.pid, flush=True); time.sleep(30)"
    )
    started = _start(store, parent_code)
    session_id = started["session_id"]
    output = _wait_output(store, session_id, "stdout", "\n")
    child_pid = int(output["text"].strip().splitlines()[0])
    child_creation = process_creation_token(child_pid)
    assert child_creation
    store.terminate(session_id)
    assert _wait_state(store, session_id, {"TERMINATED"})["state"] == "TERMINATED"
    deadline = time.monotonic() + 5.0
    while (
        process_creation_token(child_pid) == child_creation
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert process_creation_token(child_pid) != child_creation


def test_natural_parent_exit_does_not_leave_child(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    child_code = "import time; time.sleep(30)"
    parent_code = (
        "import subprocess,sys; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "print(p.pid, flush=True)"
    )
    started = _start(store, parent_code)
    session_id = started["session_id"]
    output = _wait_output(store, session_id, "stdout", "\n")
    child_pid = int(output["text"].strip().splitlines()[0])
    child_creation = process_creation_token(child_pid)
    terminal = _wait_state(store, session_id, {"EXITED"})
    assert terminal["exit_code"] == 0
    if not child_creation:
        assert process_creation_token(child_pid) == ""
        return
    deadline = time.monotonic() + 5.0
    while (
        process_creation_token(child_pid) == child_creation
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert process_creation_token(child_pid) != child_creation


def test_pid_identity_change_fails_closed(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import time; time.sleep(30)")
    session_id = started["session_id"]
    path = tmp_path / ".nous" / "process-sessions" / session_id / "session.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    tampered = dict(original)
    tampered["process_identity"] = {
        **dict(original["process_identity"]),
        "creation_time": "reused-pid",
    }
    path.write_text(json.dumps(tampered), encoding="utf-8")
    assert store.status(session_id)["state"] == "RECOVERY_REQUIRED"
    path.write_text(json.dumps(original), encoding="utf-8")
    store.kill(session_id)
    _wait_state(store, session_id, {"KILLED"})


def test_recovery_binds_host_after_crash_between_spawn_and_running_fact(
    tmp_path: Path,
) -> None:
    from tests.tools.test_process_session_startup import _cleanup_original_session

    store = ProcessSessionStore(tmp_path)
    # The test owns the process lifetime instead of assuming that recovery and
    # durable I/O complete before a fixed sleep expires on every platform.
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    control_may_have_been_submitted = False
    try:
        assert started["state"] == "RUNNING"
        path = tmp_path / ".nous" / "process-sessions" / session_id / "session.json"
        interrupted = json.loads(path.read_text(encoding="utf-8"))
        interrupted.update(
            state="STARTING",
            process_identity={},
            helper_identity={},
            started_at="",
            stdin_available=False,
        )
        path.write_text(json.dumps(interrupted), encoding="utf-8")

        recovered = ProcessSessionStore(tmp_path).recover(session_id=session_id)
        assert recovered["state"] == "RUNNING"
        assert recovered["recovery_required"] is False
        assert recovered["automatic_replay"] is False
        assert (
            recovered["process_identity"]["pid"] == started["process_identity"]["pid"]
        )
        control_may_have_been_submitted = True
        try:
            store.kill(session_id)
        except ValueError as exc:
            if str(exc).startswith(
                "process session is not running: RECOVERY_REQUIRED"
            ) and not list((path.parent / "control").glob("*.json")):
                # This exact rejection precedes writing any control request.
                # Keep it as a test failure, while allowing verified cleanup.
                control_may_have_been_submitted = False
            raise
        assert _wait_state(store, session_id, {"KILLED"})["state"] == "KILLED"
    finally:
        if control_may_have_been_submitted:
            # A lost acknowledgement is not permission to submit another kill.
            assert _wait_state(
                store, session_id, {"EXITED", "INTERRUPTED", "TERMINATED", "KILLED"}
            )["state"] in {"EXITED", "INTERRUPTED", "TERMINATED", "KILLED"}
        else:
            _cleanup_original_session(store, session_id)


def test_unverified_control_denies_then_recovers_only_original_host(
    tmp_path: Path, monkeypatch
) -> None:
    from nous_runtime.tools import process_session
    from tests.tools.test_process_session_startup import _cleanup_original_session

    original_launch = process_session.ProcessSandboxHost.launch
    launches = []

    def launch(spec):
        launches.append(spec)
        return original_launch(spec)

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch)
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import sys; sys.stdin.readline()")
    session_id = started["session_id"]
    control_directory = store.root / session_id / "control"
    control_may_have_been_submitted = False
    try:
        assert started["state"] == "RUNNING"
        assert len(launches) == 1
        with monkeypatch.context() as fault:
            fault.setattr(process_session, "process_identity_matches", lambda _: False)
            with pytest.raises(ValueError, match="process session is not running"):
                store.kill(session_id)
            current = store.status(session_id)
            assert current["state"] == "RECOVERY_REQUIRED"
            assert current["stdin_available"] is False
            assert not list(control_directory.glob("*.json"))
            assert len(launches) == 1
        recovered = ProcessSessionStore(tmp_path).recover(session_id=session_id)
        assert recovered["state"] == "RUNNING"
        assert recovered["recovery_required"] is False
        assert recovered["automatic_replay"] is False
        assert recovered["process_identity"] == started["process_identity"]
        assert recovered["helper_identity"] == started["helper_identity"]
        assert len(launches) == 1
        control_may_have_been_submitted = True
        try:
            store.kill(session_id)
        except ValueError as exc:
            if str(exc).startswith(
                "process session is not running: RECOVERY_REQUIRED"
            ) and not list(control_directory.glob("*.json")):
                control_may_have_been_submitted = False
            raise
        assert _wait_state(store, session_id, {"KILLED"})["state"] == "KILLED"
        requests = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in control_directory.glob("*.json")
        ]
        assert len(requests) == 1
        assert requests[0]["action"] == "kill"
        assert requests[0]["session_id"] == session_id
        assert len(launches) == 1
    finally:
        if control_may_have_been_submitted:
            assert _wait_state(
                store, session_id, {"EXITED", "INTERRUPTED", "TERMINATED", "KILLED"}
            )["state"] in {"EXITED", "INTERRUPTED", "TERMINATED", "KILLED"}
        else:
            _cleanup_original_session(store, session_id)


def test_unknown_start_outcome_requires_recovery(tmp_path: Path) -> None:
    store = ProcessSessionStore(tmp_path)
    session = ProcessSession(
        session_id="ps_unknown",
        work_id="work-process-test",
        tool_call_id="call-process-test",
        command=[sys.executable, "-c", "pass"],
        cwd=str(tmp_path),
        environment_ref="sha256:" + "0" * 64,
        command_digest="sha256:"
        + hashlib.sha256(
            json.dumps(
                [sys.executable, "-c", "pass"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        state=ProcessSessionState.STARTING.value,
        action_sequence=7,
    )
    store._save(session)
    recovered = store.recover(work_id="work-process-test", action_sequence=7)
    assert recovered["recovery_required"] is True
    assert recovered["state"] == "RECOVERY_REQUIRED"
    assert recovered["automatic_replay"] is False


def test_tool_runtime_reuses_governed_command_allowlist(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    runtime = ProcessSessionToolRuntime(workspace)
    monkeypatch.setattr(
        runtime.store,
        "start",
        lambda *args, **kwargs: pytest.fail(
            "Model cannot start a process without durable authority"
        ),
    )
    denied = runtime.execute("shell_start", {"command": [sys.executable, "-c", "pass"]})
    assert denied["ok"] is False
    assert denied["error_code"] == "NOUS_UNSUPPORTED_GOVERNED_OPERATION"
    names = {item["function"]["name"] for item in runtime.specifications()}
    assert {"shell_status", "shell_stdout", "shell_stderr", "shell_recover"} <= names
    assert not names.intersection(
        {
            "shell_start",
            "shell_stdin",
            "shell_close_stdin",
            "shell_interrupt",
            "shell_terminate",
            "shell_kill",
        }
    )
    assert not runtime.execute(
        "_unqualified_legacy_shell_start", {"command": [sys.executable, "-c", "pass"]}
    )["ok"]
    assert not list((tmp_path / ".nous" / "process-sessions").glob("*.json"))

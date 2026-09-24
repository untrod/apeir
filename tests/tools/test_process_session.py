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
    assert started["state"] == "RUNNING"

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
    store = ProcessSessionStore(tmp_path)
    started = _start(store, "import time; time.sleep(30)")
    session_id = started["session_id"]
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
    assert recovered["process_identity"]["pid"] == started["process_identity"]["pid"]
    store.kill(session_id)
    _wait_state(store, session_id, {"KILLED"})


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


def test_tool_runtime_reuses_governed_command_allowlist(tmp_path: Path) -> None:
    workspace = WorkspaceToolRuntime(str(tmp_path), allow_mutations=True)
    runtime = ProcessSessionToolRuntime(workspace)
    denied = runtime.execute("shell_start", {"command": [sys.executable, "-c", "pass"]})
    assert denied["ok"] is False
    assert "allowlist" in denied["error"]
    names = {item["function"]["name"] for item in runtime.specifications()}
    assert {
        "shell_start",
        "shell_status",
        "shell_stdout",
        "shell_stderr",
        "shell_stdin",
        "shell_interrupt",
        "shell_terminate",
        "shell_kill",
        "shell_recover",
    } <= names

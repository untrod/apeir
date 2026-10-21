"""The existing process host reaps only its original workload descendants."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys

import pytest

from nous_runtime.kernel import process_session_host as host
from nous_runtime.tools.process_session import ProcessSessionStore
from tests.tools.test_process_session import _start, _wait_output, _wait_state
from tests.tools.test_process_session_startup import _cleanup_original_session


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper")
@pytest.mark.parametrize("control", ["exit", "terminate", "kill"])
def test_orphaned_grandchild_is_reaped_before_terminal_publication(tmp_path, control):
    store = ProcessSessionStore(tmp_path)
    grandchild = "import time; time.sleep(30)"
    child = (
        "import subprocess,sys; "
        f"p=subprocess.Popen([sys.executable,'-u','-c',{grandchild!r}]); "
        "print(p.pid,flush=True)"
    )
    parent = (
        "import subprocess,sys; "
        f"p=subprocess.Popen([sys.executable,'-u','-c',{child!r}]); "
        "p.wait(); sys.stdin.readline()"
    )
    started = _start(store, parent)
    session_id = started["session_id"]
    control_submitted = False
    terminal = {"exit": "EXITED", "terminate": "TERMINATED", "kill": "KILLED"}[control]
    try:
        output = _wait_output(store, session_id, "stdout", "\n")
        pid = int(output["text"].strip())
        assert host.process_creation_token(pid)
        control_submitted = True
        if control == "exit":
            store.write_stdin(session_id, "done\n")
        else:
            getattr(store, control)(session_id)
        assert _wait_state(store, session_id, {terminal})["state"] == terminal
        # A dead-but-unreaped zombie retains /proc identity. Terminal state
        # proves actual reaping here, not merely successful signalling.
        assert host.process_creation_token(pid) == ""
    finally:
        if control_submitted:
            # An uncertain acknowledgement cannot authorize another control.
            assert _wait_state(store, session_id, {terminal})["state"] == terminal
        else:
            _cleanup_original_session(store, session_id)


def test_subreaper_failure_prevents_workload_spawn(tmp_path, monkeypatch):
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "session_id": "original-session",
                "command": [sys.executable, "-c", "pass"],
                "command_digest": "sha256:original",
                "cwd": str(tmp_path),
                "env": {},
            }
        )
    )

    def unavailable():
        raise OSError("subreaper refused")

    monkeypatch.setattr(host, "_enable_linux_child_subreaper", unavailable)
    monkeypatch.setattr(
        host.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned without reaper")
    )
    assert host.ProcessSandboxHost.serve(spec) == 1
    state = json.loads((tmp_path / "host.json").read_text())
    assert state["state"] == "RECOVERY_REQUIRED"
    assert state["error"] == "subreaper refused"
    assert "process_identity" not in state


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper")
def test_host_error_reaps_original_process_tree_before_recovery_record(tmp_path):
    child = "import time; time.sleep(30)"
    parent = (
        "import subprocess,sys,time; "
        f"p=subprocess.Popen([sys.executable,'-u','-c',{child!r}]); "
        "print(p.pid,flush=True); time.sleep(30)"
    )
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "session_id": "original-faulted-session",
                "command": [sys.executable, "-u", "-c", parent],
                "command_digest": "sha256:original",
                "cwd": str(tmp_path),
                "env": dict(os.environ),
            }
        )
    )
    # Fault only after the actual child exists; execute the host in its own
    # process so its subreaper setting cannot alter the test runner's lifetime.
    script = """
import sys,time
from pathlib import Path
from nous_runtime.kernel import process_session_host as h
original=h._atomic_json
def write(path,state):
    if state.get('state') == 'RUNNING':
        deadline=time.monotonic()+5
        output=path.parent/'stdout.log'
        while '\\n' not in output.read_text() and time.monotonic()<deadline:
            time.sleep(.01)
        if '\\n' not in output.read_text():
            raise RuntimeError('child never started')
        raise OSError('injected host persistence failure')
    return original(path,state)
h._atomic_json=write
sys.exit(h.ProcessSandboxHost.serve(Path(sys.argv[1])))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(spec)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    state = json.loads((tmp_path / "host.json").read_text())
    assert state["state"] == "RECOVERY_REQUIRED"
    assert state["error"] == "injected host persistence failure"
    assert "cleanup_error" not in state
    assert host.process_creation_token(state["process_identity"]["pid"]) == ""
    child_pid = int((tmp_path / "stdout.log").read_text().strip())
    assert host.process_creation_token(child_pid) == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX waitpid process-group scope")
def test_reaping_never_waits_for_unrelated_children(monkeypatch):
    calls = []
    outcomes = iter([(234, 0), ChildProcessError()])

    def waitpid(pid, flags):
        calls.append((pid, flags))
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(host.os, "waitpid", waitpid)
    host.ProcessSandboxHost._reap_process_group(123)
    assert calls == [(-123, os.WNOHANG), (-123, os.WNOHANG)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX waitpid process-group scope")
def test_unreaped_live_child_does_not_report_cleanup_success(monkeypatch):
    monkeypatch.setattr(host.os, "waitpid", lambda *a: (0, 0))
    with pytest.raises(RuntimeError, match="cleanup could not be confirmed"):
        host.ProcessSandboxHost._reap_process_group(123, timeout=0)


@pytest.mark.skipif(os.name == "nt", reason="POSIX waitpid process-group scope")
def test_waitpid_failure_does_not_report_cleanup_success(monkeypatch):
    def refused(*args):
        raise OSError(errno.EPERM, "wait refused")

    monkeypatch.setattr(host.os, "waitpid", refused)
    with pytest.raises(OSError) as exc:
        host.ProcessSandboxHost._reap_process_group(123)
    assert exc.value.errno == errno.EPERM

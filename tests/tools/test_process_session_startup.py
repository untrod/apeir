"""Startup reconciles only its original host within the existing deadline."""

import os
import sys
import time

import pytest

from nous_runtime.tools import process_session
from nous_runtime.kernel import process_session_host
from nous_runtime.tools.process_session import ProcessSessionStore


@pytest.mark.parametrize("missed_probe", [1, 2])
@pytest.mark.parametrize("missed_cleanup_probe", [False, True])
def test_startup_reobserves_original_identity_without_spawning_again(
    tmp_path, monkeypatch, missed_probe, missed_cleanup_probe
):
    original_launch = process_session.ProcessSandboxHost.launch
    original_matches = process_session.process_identity_matches
    original_write = process_session._atomic_json
    launches, probes = [], []
    controls = []
    identity_reads = []
    host_read_failures = []
    creation_token = process_session_host.process_creation_token
    read_text = process_session.Path.read_text
    cleanup_miss_pending = False

    def token(pid):
        value = creation_token(pid)
        identity_reads.append({"pid": pid, "creation_time": value})
        return value

    def text(path, *args, **kwargs):
        try:
            return read_text(path, *args, **kwargs)
        except OSError as error:
            if path.name == "host.json":
                host_read_failures.append(
                    {
                        "type": type(error).__name__,
                        "errno": error.errno,
                        "winerror": getattr(error, "winerror", None),
                    }
                )
            raise

    def launch(spec):
        launches.append(spec)
        return original_launch(spec)

    def matches(identity):
        nonlocal cleanup_miss_pending
        probes.append(dict(identity))
        if cleanup_miss_pending:
            cleanup_miss_pending = False
            return False
        if len(probes) == missed_probe:
            return False
        return original_matches(identity)

    def write(path, value):
        original_write(path, value)
        if path.parent.name == "control":
            controls.append(dict(value))

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch)
    monkeypatch.setattr(process_session, "process_identity_matches", matches)
    monkeypatch.setattr(process_session, "_atomic_json", write)
    monkeypatch.setattr(process_session_host, "process_creation_token", token)
    monkeypatch.setattr(process_session.Path, "read_text", text)
    store = ProcessSessionStore(tmp_path)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-startup-reconciliation",
        tool_call_id="call-startup-reconciliation",
    )
    try:
        assert result["state"] == "RUNNING", result
        assert len(launches) == 1
        assert len(probes) >= 4
        assert probes[0] == probes[2]
        assert probes[1] == probes[3]
        assert result["process_identity"] == probes[0]
        assert result["helper_identity"] == probes[1]
        attached = ProcessSessionStore(tmp_path).attach(result["session_id"])
        assert attached["state"] == "RUNNING", {
            "attached_state": attached["state"],
            "attached_error": attached.get("error"),
            "host_read_failure_count": len(host_read_failures),
            "last_host_read_failure": host_read_failures[-1:] or None,
            "last_identity_reads": identity_reads[-2:],
        }
    finally:
        # A failed assertion must not leave a verified original test process.
        # Unknown identities remain non-controllable; never kill a bare PID.
        cleanup_miss_pending = missed_cleanup_probe
        _cleanup_original_session(store, result["session_id"])
        assert len(launches) == 1
        assert len(controls) == 1
        assert controls[0]["session_id"] == result["session_id"]
        assert controls[0]["action"] == "kill"


@pytest.mark.parametrize("unknown", ["identity-query", "host-binding"])
def test_startup_never_controls_or_replays_an_unproven_original_host(
    tmp_path, monkeypatch, unknown
):
    store = ProcessSessionStore(tmp_path)
    original_launch = process_session.ProcessSandboxHost.launch
    original_host = store._host_state
    launches = []

    def launch(spec):
        launches.append(spec)
        return original_launch(spec)

    def host(session_id):
        observation = original_host(session_id)
        if observation.get("state") == "RUNNING":
            observation["helper_identity"] = {
                **observation["helper_identity"],
                "command_digest": "sha256:" + "0" * 64,
            }
        return observation

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch)
    if unknown == "identity-query":
        monkeypatch.setattr(
            process_session, "process_identity_matches", lambda _: False
        )
    else:
        monkeypatch.setattr(store, "_host_state", host)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-unproven-startup",
        tool_call_id="call-unproven-startup",
    )
    try:
        assert result["state"] == "RECOVERY_REQUIRED"
        assert result["stdin_available"] is False
        assert len(launches) == 1
        if unknown == "identity-query":
            assert result["process_identity"]
            assert result["helper_identity"]
            assert result["error"] == "running process host identity cannot be verified"
        else:
            assert result["error"] == "process helper identity changed"
        with pytest.raises(ValueError, match="process session is not running"):
            store.write_stdin(result["session_id"], "not authorized\n")
        assert len(launches) == 1
    finally:
        monkeypatch.undo()
        _cleanup_original_session(store, result["session_id"])


def _cleanup_original_session(store, session_id):
    """Reobserve a rejected control; never repeat an accepted/uncertain one."""
    deadline = time.monotonic() + 5.0
    accepted = False
    while time.monotonic() < deadline:
        if not accepted:
            try:
                store.kill(session_id)
            except ValueError as exc:
                current = store.status(session_id)
                if current["state"] in process_session._TERMINAL_STATES:
                    return current
                # A diagnostic suffix must not change the refusal contract.
                # Recheck the original journal before another admission attempt;
                # an accepted or ambiguous control must never be repeated.
                if not str(exc).startswith(
                    "process session is not running: RECOVERY_REQUIRED"
                ) or any((store.root / session_id / "control").glob("*.json")):
                    raise
            else:
                accepted = True
        current = store.status(session_id)
        if current["state"] in process_session._TERMINAL_STATES:
            return current
        time.sleep(0.025)
    raise AssertionError("Original process cleanup did not obtain terminal evidence")


def test_cleanup_does_not_control_a_persistently_unverified_original(
    tmp_path, monkeypatch
):
    original_launch = process_session.ProcessSandboxHost.launch
    launches = []

    def launch(spec):
        launches.append(spec)
        return original_launch(spec)

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch)
    store = ProcessSessionStore(tmp_path)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-cleanup-identity-denial",
        tool_call_id="call-cleanup-identity-denial",
    )
    try:
        assert result["state"] == "RUNNING"
        with monkeypatch.context() as fault:
            fault.setattr(process_session, "process_identity_matches", lambda _: False)
            with pytest.raises(AssertionError, match="terminal evidence"):
                _cleanup_original_session(store, result["session_id"])
            assert store.status(result["session_id"])["state"] == "RECOVERY_REQUIRED"
            assert not list(
                (store.root / result["session_id"] / "control").glob("*.json")
            )
            assert len(launches) == 1
    finally:
        _cleanup_original_session(store, result["session_id"])


@pytest.mark.parametrize("failure", [RuntimeError, OSError])
def test_cleanup_never_repeats_an_accepted_control_after_response_loss(
    tmp_path, monkeypatch, failure
):
    store = ProcessSessionStore(tmp_path)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-cleanup-control-response-loss",
        tool_call_id="call-cleanup-control-response-loss",
    )
    controls = []
    original_kill = store.kill

    def kill_then_lose_response(session_id):
        controls.append(session_id)
        original_kill(session_id)
        raise failure("controlled loss after original control acceptance")

    try:
        assert result["state"] == "RUNNING"
        with monkeypatch.context() as fault:
            fault.setattr(store, "kill", kill_then_lose_response)
            with pytest.raises(failure, match="after original control acceptance"):
                _cleanup_original_session(store, result["session_id"])
        assert controls == [result["session_id"]]
    finally:
        # If terminal publication lags, observe it; do not submit a new control.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if (
                store.status(result["session_id"])["state"]
                in process_session._TERMINAL_STATES
            ):
                break
            time.sleep(0.025)
        else:
            pytest.fail("Accepted original control has no terminal evidence")


def test_startup_binding_rejection_uses_one_observed_host_sample(tmp_path, monkeypatch):
    read_host = ProcessSessionStore._host_state
    running_reads = []

    def missing_second_sample(self, session_id):
        observation = read_host(self, session_id)
        if observation.get("state") == "RUNNING":
            running_reads.append(session_id)
            if len(running_reads) == 2:
                return {}
        return observation

    monkeypatch.setattr(ProcessSessionStore, "_host_state", missing_second_sample)
    # Reuse the original exact identity-denial, stdin and single-launch checks.
    test_startup_never_controls_or_replays_an_unproven_original_host(
        tmp_path, monkeypatch, "host-binding"
    )
    assert running_reads


def test_startup_snapshot_does_not_authorize_later_unreadable_host(
    tmp_path, monkeypatch
):
    store = ProcessSessionStore(tmp_path)
    read_host = store._host_state
    launches = []
    launch = process_session.ProcessSandboxHost.launch
    first_running = False
    missing = True

    def launch_once(spec):
        launches.append(spec)
        return launch(spec)

    def one_running_sample(session_id):
        nonlocal first_running
        observation = read_host(session_id)
        if observation.get("state") == "RUNNING":
            if first_running and missing:
                return {}
            first_running = True
        return observation

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch_once)
    monkeypatch.setattr(store, "_host_state", one_running_sample)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-one-host-snapshot",
        tool_call_id="call-one-host-snapshot",
    )
    try:
        assert first_running
        assert result["state"] == "RUNNING", result
        assert len(launches) == 1
        current = store.status(result["session_id"])
        assert current["state"] == "RECOVERY_REQUIRED"
        assert current["error"] == "process host state is missing"
        assert current["stdin_available"] is False
        with pytest.raises(ValueError, match="process session is not running"):
            store.write_stdin(result["session_id"], "not authorized\n")
        assert not list((store.root / result["session_id"] / "control").glob("*.json"))
        assert len(launches) == 1
    finally:
        missing = False
        monkeypatch.undo()
        _cleanup_original_session(store, result["session_id"])


def test_attachment_uses_original_record_read_not_a_separate_path_probe(
    tmp_path, monkeypatch
):
    """A negative pathname sample is not the outcome of opening the bound record."""
    store = ProcessSessionStore(tmp_path)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-direct-original-record",
        tool_call_id="call-direct-original-record",
    )
    host_path = store.root / result["session_id"] / "host.json"
    is_file = process_session.Path.is_file

    def negative_path_probe(path):
        return False if path == host_path else is_file(path)

    try:
        assert result["state"] == "RUNNING", result
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "is_file", negative_path_probe)
            attached = ProcessSessionStore(tmp_path).attach(result["session_id"])
            assert attached["state"] == "RUNNING", attached
            assert attached["process_identity"] == result["process_identity"]
            assert attached["helper_identity"] == result["helper_identity"]
            assert not list((host_path.parent / "control").glob("*.json"))
    finally:
        _cleanup_original_session(store, result["session_id"])


@pytest.mark.parametrize("failure", [PermissionError, FileNotFoundError])
def test_direct_original_record_read_failure_remains_uncontrollable(
    tmp_path, monkeypatch, failure
):
    store = ProcessSessionStore(tmp_path)
    result = store.start(
        [sys.executable, "-u", "-c", "import sys; sys.stdin.readline()"],
        cwd=tmp_path,
        environment={
            "PATH": os.defpath,
            **({"SystemRoot": os.environ["SystemRoot"]} if os.name == "nt" else {}),
        },
        work_id="work-unreadable-direct-record",
        tool_call_id="call-unreadable-direct-record",
    )
    host_path = store.root / result["session_id"] / "host.json"
    read_text = process_session.Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == host_path:
            raise failure("owned qualification read unavailable")
        return read_text(path, *args, **kwargs)

    try:
        assert result["state"] == "RUNNING", result
        with monkeypatch.context() as fault:
            fault.setattr(process_session.Path, "read_text", unreadable)
            current = ProcessSessionStore(tmp_path).attach(result["session_id"])
            assert current["state"] == "RECOVERY_REQUIRED"
            assert current["stdin_available"] is False
            with pytest.raises(ValueError, match="process session is not running"):
                store.write_stdin(result["session_id"], "not authorized\n")
            assert not list((host_path.parent / "control").glob("*.json"))
    finally:
        _cleanup_original_session(store, result["session_id"])

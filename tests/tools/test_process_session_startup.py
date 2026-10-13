"""Startup reconciles only its original host within the existing deadline."""

import os
import sys

import pytest

from nous_runtime.tools import process_session
from nous_runtime.tools.process_session import ProcessSessionStore


@pytest.mark.parametrize("missed_probe", [1, 2])
def test_startup_reobserves_original_identity_without_spawning_again(
    tmp_path, monkeypatch, missed_probe
):
    original_launch = process_session.ProcessSandboxHost.launch
    original_matches = process_session.process_identity_matches
    launches, probes = [], []

    def launch(spec):
        launches.append(spec)
        return original_launch(spec)

    def matches(identity):
        probes.append(dict(identity))
        if len(probes) == missed_probe:
            return False
        return original_matches(identity)

    monkeypatch.setattr(process_session.ProcessSandboxHost, "launch", launch)
    monkeypatch.setattr(process_session, "process_identity_matches", matches)
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
        assert (
            ProcessSessionStore(tmp_path).attach(result["session_id"])["state"]
            == "RUNNING"
        )
    finally:
        # A failed assertion must not leave a verified original test process.
        # Unknown identities remain non-controllable; never kill a bare PID.
        current = store.status(result["session_id"])
        if current["state"] == "RUNNING":
            store.kill(result["session_id"])


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
        current = store.status(result["session_id"])
        if current["state"] == "RUNNING":
            store.kill(result["session_id"])

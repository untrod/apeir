"""Canonical fake process evidence without launching or controlling a host."""

import hashlib

import pytest

from nous_runtime.chat.agent_tools import WorkspaceToolRuntime
from nous_runtime.tools import ToolCatalog
from nous_runtime.tools import process_session


@pytest.fixture
def bound_process_recovery(monkeypatch):
    def prepare(harness, snapshot, action_sequence=1):
        work_id = snapshot.run_id
        runtime = process_session.ProcessSessionToolRuntime(
            WorkspaceToolRuntime(str(harness.root), source_work_id=work_id)
        )
        store = runtime.store
        monkeypatch.setattr(
            process_session.ProcessSandboxHost,
            "launch",
            lambda *_args, **_kwargs: pytest.fail("recovery must not launch a host"),
        )
        monkeypatch.setattr(
            store,
            "_control",
            lambda *_args, **_kwargs: pytest.fail("recovery must not control a host"),
        )
        arguments = {"command": ["python", "-m", "pytest", "-q"], "cwd": "."}
        command = runtime.workspace_runtime.prepare_development_command(
            arguments["command"]
        )
        environment = runtime.workspace_runtime.safe_process_environment()
        session_id = "ps_fixture"
        directory = store._directory(session_id)
        spec_path = directory / "spec.json"
        command_digest = process_session._digest(command)
        identity = {
            "pid": 1313,
            "start_time": "fixture-target",
            "command_digest": command_digest,
        }
        helper = {
            "pid": 1314,
            "start_time": "fixture-helper",
            "command_digest": "sha256:"
            + hashlib.sha256(str(spec_path.resolve()).encode()).hexdigest(),
        }
        session = process_session.ProcessSession(
            session_id,
            work_id,
            "invoke_fixture",
            command,
            str(harness.root),
            process_session._digest(environment),
            command_digest,
            state="RUNNING",
            process_identity=identity,
            helper_identity=helper,
            action_sequence=action_sequence,
        )
        from nous_runtime.work.loop import AgentLoop

        snapshot.pending_action["arguments_digest"] = AgentLoop._arguments_digest(
            arguments
        )
        snapshot.pending_action["process_binding"] = {
            "schema": "nous.work-process-binding/v1",
            "arguments_digest": snapshot.pending_action["arguments_digest"],
            "work_id": work_id,
            "action_sequence": action_sequence,
            "tool_call_id": session.tool_call_id,
            "command_digest": command_digest,
            "cwd": session.cwd,
            "environment_ref": session.environment_ref,
        }
        harness.persist_progress(snapshot, "work.progress", {})
        store._save(session)
        spec = {
            "schema": "nous.process-host/v1",
            "session_id": session_id,
            "command": command,
            "command_digest": command_digest,
            "cwd": str(harness.root),
            "env": environment,
        }
        host = {
            "session_id": session_id,
            "command_digest": command_digest,
            "state": "RUNNING",
            "process_identity": identity,
            "helper_identity": helper,
        }
        process_session._atomic_json(spec_path, spec)
        process_session._atomic_json(directory / "host.json", host)
        monkeypatch.setattr(
            process_session,
            "process_identity_matches",
            lambda value: value in (identity, helper),
        )
        calls = []
        original_recover = store.recover

        def recover(**arguments):
            calls.append(dict(arguments))
            return original_recover(**arguments)

        store.recover = recover
        tools = ToolCatalog()
        tools.register_runtime(runtime, provider_id="process-session")
        return tools, store, session, spec, host, calls

    return prepare

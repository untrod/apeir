# -*- coding: utf-8 -*-
"""Tests for external agent adapter components."""

import os

import pytest

from nous_runtime.agents.adapters.artifact_collector import ArtifactCollector
from nous_runtime.agents.adapters.command_adapter import CommandAgentAdapter
from nous_runtime.agents.adapters.environment_filter import EnvironmentFilter
from nous_runtime.agents.adapters.event_parser import StructuredEventParser
from nous_runtime.agents.adapters.output_limiter import OutputLimiter
from nous_runtime.agents.adapters.policy_evaluator import CommandPolicyEvaluator
from nous_runtime.agents.adapters.workspace_guard import WorkspaceGuard
from nous_runtime.agents.external.models import (
    AgentCapability,
    AgentCommandProposal,
    AgentDescriptor,
    AgentRunContext,
    AgentRunRequest,
)


class TestWorkspaceGuard:
    def test_validates_within_workspace(self, tmp_path):
        guard = WorkspaceGuard(str(tmp_path))
        (tmp_path / "test.txt").write_text("hello")
        resolved = guard.validate_path("test.txt")
        assert os.path.isfile(resolved)

    def test_rejects_path_traversal(self, tmp_path):
        guard = WorkspaceGuard(str(tmp_path))
        with pytest.raises(ValueError, match="traversal"):
            guard.validate_path("../etc/passwd")

    def test_rejects_absolute_escape(self, tmp_path):
        guard = WorkspaceGuard(str(tmp_path))
        with pytest.raises(ValueError, match="escapes"):
            guard.validate_path("/etc/passwd")

    def test_requires_existing_workspace(self):
        with pytest.raises(ValueError, match="does not exist"):
            WorkspaceGuard("/nonexistent/path/12345")


class TestEnvironmentFilter:
    def test_builds_sanitized_env(self):
        filt = EnvironmentFilter(allowlist=("LANG",))
        env = filt.build_env()
        assert "LANG" in env
        if os.name == "nt":
            assert "HOME" not in env
        else:
            assert env["HOME"] == "/tmp"
        assert "API_KEY" not in env

    def test_blocks_sensitive_keys(self):
        filt = EnvironmentFilter()
        env = filt.build_env(extra={"API_KEY": "secret123", "MY_VAR": "hello"})
        assert "MY_VAR" in env
        assert "API_KEY" not in env


class TestOutputLimiter:
    def test_writes_within_limit(self):
        limiter = OutputLimiter(limit_bytes=2048)
        limiter.write(b"Hello")
        assert limiter.bytes_written == 5
        assert not limiter.truncated

    def test_truncates_at_limit(self):
        limiter = OutputLimiter(limit_bytes=1024)
        limiter.write(b"X" * 2000)
        assert limiter.bytes_written == 1024
        assert limiter.truncated

    def test_requires_minimum_limit(self):
        with pytest.raises(ValueError):
            OutputLimiter(limit_bytes=500)


class TestStructuredEventParser:
    def test_parses_json_line(self):
        parser = StructuredEventParser()
        event = parser.parse_line('{"type": "step.started", "step": 1}')
        assert event is not None
        assert event["type"] == "step.started"

    def test_ignores_non_json(self):
        parser = StructuredEventParser()
        event = parser.parse_line("This is just text")
        assert event is None

    def test_parses_stream(self):
        parser = StructuredEventParser()
        text = '{"type": "start"}\nplain text\n{"type": "end"}\n'
        events = parser.parse_stream(text)
        assert len(events) == 2
        assert events[0]["type"] == "start"
        assert events[1]["type"] == "end"

    def test_extracts_progress(self):
        parser = StructuredEventParser()
        parser.parse_line('{"type": "progress", "step": 3, "percent": 75}')
        progress = parser.extract_progress(parser.events[0])
        assert progress is not None
        assert progress["step"] == 3


class TestArtifactCollector:
    def test_collects_declared_artifact(self, tmp_path):
        (tmp_path / "output.txt").write_text("result")
        collector = ArtifactCollector(str(tmp_path))
        artifacts = collector.collect("run_1", ("output.txt",))
        assert len(artifacts) == 1
        assert artifacts[0].name == "output.txt"
        assert len(artifacts[0].checksum) == 64

    def test_ignores_undeclared_files(self, tmp_path):
        (tmp_path / "secret.txt").write_text("secret")
        collector = ArtifactCollector(str(tmp_path))
        artifacts = collector.collect("run_1", ("output.txt",))
        assert len(artifacts) == 0

    def test_discovers_changed_files(self, tmp_path):
        collector = ArtifactCollector(str(tmp_path))
        before = collector.snapshot_workspace(str(tmp_path))
        assert before == {}
        (tmp_path / "new.txt").write_text("new")
        after = collector.snapshot_workspace(str(tmp_path))
        assert "new.txt" in after


class TestCommandPolicyEvaluator:
    def test_allow_read_only(self):
        evaluator = CommandPolicyEvaluator()
        assert evaluator.evaluate(AgentCommandProposal(command=("ls",))) == "allow"
        assert evaluator.evaluate(AgentCommandProposal(command=("cat", "file.txt"))) == "allow"
        assert evaluator.evaluate(AgentCommandProposal(command=("git", "status"))) == "allow"

    def test_ask_for_write_commands(self):
        evaluator = CommandPolicyEvaluator()
        assert evaluator.evaluate(AgentCommandProposal(command=("mkdir", "dir"))) == "ask"
        assert evaluator.evaluate(AgentCommandProposal(command=("git", "add", "."))) == "ask"

    def test_ask_for_install_commands(self):
        evaluator = CommandPolicyEvaluator()
        assert evaluator.evaluate(AgentCommandProposal(command=("pip", "install", "pkg"))) == "ask"
        assert evaluator.evaluate(AgentCommandProposal(command=("npm", "install"))) == "ask"
        assert evaluator.evaluate(AgentCommandProposal(command=("git", "push"))) == "ask"

    def test_deny_empty_command(self):
        evaluator = CommandPolicyEvaluator()
        assert evaluator.evaluate(AgentCommandProposal(command=())) == "deny"

    def test_is_destructive(self):
        assert CommandPolicyEvaluator.is_destructive(("rm", "-rf", "/")) is True
        assert CommandPolicyEvaluator.is_destructive(("ls",)) is False
        assert CommandPolicyEvaluator.is_destructive(()) is False


class TestCommandAgentAdapter:
    def test_requires_valid_descriptor(self):
        with pytest.raises(ValueError):
            CommandAgentAdapter(AgentDescriptor(agent_id="", executable_reference=""))

    def test_creates_with_valid_descriptor(self):
        desc = AgentDescriptor(
            agent_id="agent.test",
            executable_reference="echo",
            capabilities=(AgentCapability(capability_id="test.echo"),),
        )
        adapter = CommandAgentAdapter(desc)
        assert adapter.descriptor.agent_id == "agent.test"

    def test_evaluates_command(self):
        desc = AgentDescriptor(
            agent_id="agent.test",
            executable_reference="echo",
        )
        adapter = CommandAgentAdapter(desc)
        result = adapter.evaluate_command(
            AgentCommandProposal(command=("ls", "-la"))
        )
        assert result == "allow"

    def test_live_process_execution(self, tmp_path):
        """End-to-end test: run a mock agent through the adapter pipeline."""
        import sys
        mock_agent = tmp_path / "mock_agent.py"
        mock_agent.write_text("""\
import json, sys
if len(sys.argv) > 1:
    with open(sys.argv[1]) as f:
        request = json.load(f)
    print(json.dumps({"type": "run.started"}))
    print(json.dumps({"type": "step.completed"}))
sys.exit(0)
""")
        # Run: python mock_agent.py <json_request_file>
        desc = AgentDescriptor(
            agent_id="agent.mock",
            executable_reference=f"{sys.executable} {mock_agent}",
            default_timeout_ms=10000,
        )
        adapter = CommandAgentAdapter(desc)
        request = AgentRunRequest(
            objective="test",
            agent_id="agent.mock",
        )
        context = AgentRunContext(
            run_id=request.run_id,
            workspace_path=str(tmp_path),
        )
        result = adapter.execute(request, context)
        assert result.status == "COMPLETED"
        assert result.exit_code == 0
        assert list(tmp_path.glob(".nous_run_*.json")) == []

    def test_request_file_excludes_sensitive_environment(self, tmp_path):
        import json
        import sys

        mock_agent = tmp_path / "capture_request.py"
        captured = tmp_path / "captured.json"
        mock_agent.write_text(
            "import json, pathlib, sys\n"
            "data = json.load(open(sys.argv[1]))\n"
            f"pathlib.Path({str(captured)!r}).write_text(json.dumps(data['environment']))\n",
            encoding="utf-8",
        )
        descriptor = AgentDescriptor(
            agent_id="agent.environment",
            executable_reference=f"{sys.executable} {mock_agent}",
        )
        request = AgentRunRequest(agent_id="agent.environment")
        context = AgentRunContext(
            run_id=request.run_id,
            workspace_path=str(tmp_path),
            environment={"SAFE_VALUE": "visible", "API_TOKEN": "hidden"},
        )

        result = CommandAgentAdapter(descriptor).execute(request, context)
        environment = json.loads(captured.read_text(encoding="utf-8"))

        assert result.status == "COMPLETED"
        assert environment["SAFE_VALUE"] == "visible"
        assert "API_TOKEN" not in environment

    def test_rejects_input_file_outside_workspace(self, tmp_path):
        import sys

        descriptor = AgentDescriptor(
            agent_id="agent.input",
            executable_reference=sys.executable,
        )
        request = AgentRunRequest(agent_id="agent.input")
        context = AgentRunContext(
            run_id=request.run_id,
            workspace_path=str(tmp_path),
            input_files=(str(tmp_path.parent / "outside.txt"),),
        )

        with pytest.raises(ValueError, match="escapes workspace"):
            CommandAgentAdapter(descriptor).execute(request, context)
    def test_rejects_agent_id_mismatch(self, tmp_path):
        desc = AgentDescriptor(
            agent_id="agent.echo",
            executable_reference="echo",
        )
        adapter = CommandAgentAdapter(desc)
        request = AgentRunRequest(
            objective="test",
            agent_id="agent.other",
        )
        context = AgentRunContext(workspace_path=str(tmp_path))
        result = adapter.execute(request, context)
        assert result.status == "FAILED"
        assert "mismatch" in (result.errors[0] if result.errors else "").lower()

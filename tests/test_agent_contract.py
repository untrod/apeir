# -*- coding: utf-8 -*-
"""Tests for vendor-neutral agent execution contract."""

import json

from nous_runtime.agents.external.models import (
    AgentDescriptor,
    AgentCapability,
    AgentRunRequest,
    AgentRunContext,
    AgentRunResult,
    AgentArtifact,
    AgentCommandProposal,
    AgentResourceUsage,
    AgentApprovalRecord,
    SCHEMA_VERSION,
)


class TestAgentCapability:
    def test_create_minimal(self):
        cap = AgentCapability(capability_id="file.read")
        assert cap.capability_id == "file.read"
        assert cap.risk_level == "medium"
        assert cap.requires_approval is True

    def test_roundtrip_dict(self):
        cap = AgentCapability(
            capability_id="test.run_tests",
            description="Run the test suite",
            risk_level="low",
            requires_approval=False,
            allowed_side_effects=("read_only",),
        )
        data = cap.to_dict()
        restored = AgentCapability.from_dict(data)
        assert restored.capability_id == cap.capability_id
        assert restored.description == cap.description
        assert restored.risk_level == cap.risk_level
        assert restored.allowed_side_effects == ("read_only",)

    def test_serialize_json(self):
        cap = AgentCapability(capability_id="build.check")
        raw = json.dumps(cap.to_dict())
        data = json.loads(raw)
        assert data["capability_id"] == "build.check"


class TestAgentDescriptor:
    def test_create_minimal(self):
        desc = AgentDescriptor(
            agent_id="agent.coding",
            executable_reference="coding-agent",
        )
        assert desc.agent_id == "agent.coding"
        assert desc.adapter_type == "command"

    def test_validate_requires_agent_id(self):
        desc = AgentDescriptor(agent_id="", executable_reference="tool")
        errors = desc.validate()
        assert any("agent_id" in e for e in errors)

    def test_validate_requires_executable(self):
        desc = AgentDescriptor(agent_id="agent.x", executable_reference="")
        errors = desc.validate()
        assert any("executable_reference" in e for e in errors)

    def test_validate_timeout_minimum(self):
        desc = AgentDescriptor(agent_id="agent.x", executable_reference="tool", default_timeout_ms=500)
        errors = desc.validate()
        assert any("timeout" in e.lower() for e in errors)

    def test_with_capabilities(self):
        desc = AgentDescriptor(
            agent_id="agent.dev",
            executable_reference="dev-agent",
            capabilities=(
                AgentCapability(capability_id="file.read"),
                AgentCapability(capability_id="file.write", risk_level="high"),
            ),
        )
        assert len(desc.capabilities) == 2

    def test_roundtrip_dict(self):
        desc = AgentDescriptor(
            agent_id="agent.test",
            adapter_type="command",
            executable_reference="/usr/local/bin/test-agent",
            display_name="Test Agent",
            description="An agent for testing",
            version="2.0.0",
            workspace_policy="isolated",
            default_timeout_ms=60000,
            environment_allowlist=("LANG", "TMPDIR"),
        )
        data = desc.to_dict()
        restored = AgentDescriptor.from_dict(data)
        assert restored.agent_id == desc.agent_id
        assert restored.executable_reference == desc.executable_reference
        assert restored.workspace_policy == "isolated"
        assert restored.environment_allowlist == ("LANG", "TMPDIR")
        assert restored.schema_version == SCHEMA_VERSION

    def test_roundtrip_json(self):
        desc = AgentDescriptor(
            agent_id="agent.json",
            executable_reference="json-agent",
            capabilities=(AgentCapability(capability_id="json.parse"),),
        )
        raw = json.dumps(desc.to_dict())
        data = json.loads(raw)
        restored = AgentDescriptor.from_dict(data)
        assert restored.agent_id == "agent.json"


class TestAgentRunRequest:
    def test_create_with_defaults(self):
        req = AgentRunRequest(objective="Build the project")
        assert req.run_id.startswith("run_")
        assert req.objective == "Build the project"
        assert req.schema_version == SCHEMA_VERSION

    def test_full_request(self):
        req = AgentRunRequest(
            task_id="task_abc",
            workspace_id="ws_1",
            objective="Fix all lint errors",
            plan={"steps": ["lint", "fix", "verify"]},
            allowed_capabilities=("file.read", "file.write"),
            timeout_ms=120000,
            agent_id="agent.coding",
        )
        assert req.task_id == "task_abc"
        assert req.allowed_capabilities == ("file.read", "file.write")
        assert req.agent_id == "agent.coding"

    def test_roundtrip_dict(self):
        req = AgentRunRequest(
            task_id="t1",
            workspace_id="w1",
            objective="Run tests",
            expected_artifacts=("report.xml", "coverage.json"),
        )
        data = req.to_dict()
        restored = AgentRunRequest.from_dict(data)
        assert restored.run_id == req.run_id
        assert restored.expected_artifacts == ("report.xml", "coverage.json")


class TestAgentRunContext:
    def test_create(self):
        ctx = AgentRunContext(
            run_id="run_1",
            workspace_path="/tmp/ws",
            environment={"LANG": "en_US.UTF-8"},
        )
        assert ctx.context_id.startswith("ctx_")
        assert ctx.workspace_path == "/tmp/ws"

    def test_roundtrip_dict(self):
        ctx = AgentRunContext(
            run_id="run_2",
            workspace_path="/home/user/project",
            input_files=("main.py", "test_main.py"),
        )
        data = ctx.to_dict()
        restored = AgentRunContext.from_dict(data)
        assert restored.input_files == ("main.py", "test_main.py")


class TestAgentRunResult:
    def test_create_success(self):
        result = AgentRunResult(
            run_id="run_1",
            task_id="task_1",
            agent_id="agent.test",
            status="COMPLETED",
            exit_code=0,
            summary="All tests passed.",
            duration_ms=5000,
        )
        assert result.ok is True

    def test_create_failure(self):
        result = AgentRunResult(
            run_id="run_2",
            status="FAILED",
            exit_code=1,
            errors=("build error",),
        )
        assert result.ok is False

    def test_with_artifacts(self):
        art = AgentArtifact(name="output.txt", path="/tmp/output.txt", size_bytes=100)
        result = AgentRunResult(
            run_id="run_3",
            status="COMPLETED",
            exit_code=0,
            artifacts=(art,),
        )
        assert len(result.artifacts) == 1
        assert result.artifacts[0].name == "output.txt"

    def test_with_approval_records(self):
        rec = AgentApprovalRecord(
            run_id="run_4",
            proposal_id="cmd_1",
            decision="APPROVED",
            scope="once",
        )
        result = AgentRunResult(
            run_id="run_4",
            status="COMPLETED",
            exit_code=0,
            approval_records=(rec,),
        )
        assert len(result.approval_records) == 1
        assert result.approval_records[0].decision == "APPROVED"

    def test_roundtrip_dict(self):
        result = AgentRunResult(
            run_id="run_5",
            task_id="t5",
            agent_id="agent.build",
            status="COMPLETED",
            exit_code=0,
            duration_ms=30000,
            changed_files=("src/main.py",),
            commands_executed=3,
            tests_executed=10,
            tests_passed=9,
            tests_failed=1,
            warnings=("deprecated API used",),
            resource_usage=AgentResourceUsage(wall_time_ms=30000, max_memory_bytes=50000000),
        )
        data = result.to_dict()
        restored = AgentRunResult.from_dict(data)
        assert restored.run_id == "run_5"
        assert restored.tests_passed == 9
        assert restored.resource_usage.max_memory_bytes == 50000000
        assert restored.warnings == ("deprecated API used",)

    def test_roundtrip_json(self):
        result = AgentRunResult(
            run_id="run_j",
            status="COMPLETED",
            exit_code=0,
            artifacts=(AgentArtifact(name="build.log", size_bytes=1024),),
        )
        raw = json.dumps(result.to_dict())
        restored = AgentRunResult.from_dict(json.loads(raw))
        assert restored.artifacts[0].size_bytes == 1024


class TestAgentCommandProposal:
    def test_create(self):
        prop = AgentCommandProposal(
            run_id="run_1",
            command=("pytest", "--tb=short"),
            working_directory="/tmp/ws",
            description="Run tests with short traceback",
            risk_level="low",
            affected_files=("test_*.py",),
        )
        assert prop.proposal_id.startswith("cmd_")
        assert prop.command == ("pytest", "--tb=short")
        assert not prop.is_destructive

    def test_roundtrip_dict(self):
        prop = AgentCommandProposal(
            command=("rm", "-rf", "/tmp/build"),
            is_destructive=True,
            risk_level="critical",
        )
        data = prop.to_dict()
        restored = AgentCommandProposal.from_dict(data)
        assert restored.is_destructive is True
        assert restored.risk_level == "critical"


class TestAgentResourceUsage:
    def test_defaults(self):
        usage = AgentResourceUsage()
        assert usage.wall_time_ms == 0

    def test_roundtrip(self):
        usage = AgentResourceUsage(
            wall_time_ms=5000,
            max_memory_bytes=100_000_000,
            disk_write_bytes=1024,
        )
        data = usage.to_dict()
        restored = AgentResourceUsage.from_dict(data)
        assert restored.wall_time_ms == 5000
        assert restored.disk_write_bytes == 1024


class TestSchemaVersion:
    def test_version_defined(self):
        assert SCHEMA_VERSION == "1.0.0"

    def test_all_models_have_version(self):
        """Verify every contract model includes schema_version."""
        models = [
            AgentDescriptor(agent_id="a", executable_reference="e"),
            AgentRunRequest(),
            AgentRunResult(),
        ]
        for m in models:
            assert m.schema_version == SCHEMA_VERSION


class TestVendorNeutral:
    """Ensure no proprietary names leak into the public contract."""

    PROPRIETARY_TERMS: tuple[str, ...] = ()

    def test_capability_ids_are_generic(self):
        cap = AgentCapability(capability_id="file.read")
        assert "anthropic" not in cap.capability_id.lower()
        assert "openai" not in cap.capability_id.lower()

    def test_descriptor_fields_are_generic(self):
        desc = AgentDescriptor(agent_id="agent.generic", executable_reference="generic-agent")
        d = desc.to_dict()
        raw = json.dumps(d)
        for term in self.PROPRIETARY_TERMS:
            assert term.lower() not in raw.lower(), f"Proprietary term '{term}' found in serialized descriptor"

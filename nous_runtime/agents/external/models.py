# -*- coding: utf-8 -*-
"""
Vendor-neutral external agent execution contract.

All models are immutable (frozen dataclasses), versioned, and support
deterministic serialization. No proprietary executable names are embedded.
"""

from __future__ import annotations

import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.schema_registry import AGENT_SCHEMA_VERSION as SCHEMA_VERSION


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{_uuid.uuid4().hex[:12]}"


# Enumerations


class AgentProcessState(str, Enum):
    """States an external agent process can occupy."""
    CREATED = "CREATED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_FOR_INPUT = "WAITING_FOR_INPUT"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"
    TERMINATED = "TERMINATED"


class ApprovalPolicy(str, Enum):
    """Default approval behavior for an agent capability."""
    ALWAYS_ALLOW = "always_allow"
    ALWAYS_ASK = "always_ask"
    ASK_ONCE_PER_RUN = "ask_once_per_run"
    ASK_PER_COMMAND = "ask_per_command"
    POLICY_CONTROLLED = "policy_controlled"


# Models


@dataclass(frozen=True)
class AgentCapability:
    """A single capability declared by an external agent."""
    capability_id: str
    description: str = ""
    risk_level: str = "medium"  # low | medium | high | critical
    requires_approval: bool = True
    approval_policy: str = "ask_per_command"
    max_runtime_ms: int = 300000
    allowed_side_effects: tuple[str, ...] = ()  # read_only, local_write, external_write, destructive
    parameter_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "description": self.description,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "approval_policy": self.approval_policy,
            "max_runtime_ms": self.max_runtime_ms,
            "allowed_side_effects": list(self.allowed_side_effects),
            "parameter_schema": dict(self.parameter_schema),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentCapability":
        return cls(
            capability_id=str(data.get("capability_id") or ""),
            description=str(data.get("description") or ""),
            risk_level=str(data.get("risk_level") or "medium"),
            requires_approval=bool(data.get("requires_approval", True)),
            approval_policy=str(data.get("approval_policy") or "ask_per_command"),
            max_runtime_ms=int(data.get("max_runtime_ms") or 300000),
            allowed_side_effects=tuple(data.get("allowed_side_effects") or ()),
            parameter_schema=dict(data.get("parameter_schema") or {}),
        )


@dataclass(frozen=True)
class AgentDescriptor:
    """Describes an external agent that can be invoked by the Runtime.

    Required fields:
        agent_id — unique identifier
        adapter_type — the adapter class used to invoke this agent
        executable_reference — path or command to the agent executable
        capabilities — declared capabilities

    Optional fields provide workspace policy, timeout, output limits,
    environment allowlist, approval policy, health state, and version metadata.
    """

    agent_id: str
    adapter_type: str = "command"  # command | provider | custom
    executable_reference: str = ""
    display_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    capabilities: tuple[AgentCapability, ...] = ()
    workspace_policy: str = "isolated"  # isolated | shared | readonly
    default_timeout_ms: int = 300000
    output_limit_bytes: int = 1_048_576  # 1 MiB
    environment_allowlist: tuple[str, ...] = ()
    environment_blocklist: tuple[str, ...] = ("HOME", "USERPROFILE", "PATH")
    approval_policy: str = "ask_per_command"
    health_state: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.agent_id:
            errors.append("agent_id is required")
        if not self.executable_reference:
            errors.append("executable_reference is required")
        if self.workspace_policy not in {"isolated", "shared", "readonly"}:
            errors.append(f"invalid workspace_policy: {self.workspace_policy}")
        if self.default_timeout_ms < 1000:
            errors.append("default_timeout_ms must be >= 1000")
        if self.output_limit_bytes < 1024:
            errors.append("output_limit_bytes must be >= 1024")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "adapter_type": self.adapter_type,
            "executable_reference": self.executable_reference,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "workspace_policy": self.workspace_policy,
            "default_timeout_ms": self.default_timeout_ms,
            "output_limit_bytes": self.output_limit_bytes,
            "environment_allowlist": list(self.environment_allowlist),
            "environment_blocklist": list(self.environment_blocklist),
            "approval_policy": self.approval_policy,
            "health_state": self.health_state,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentDescriptor":
        return cls(
            agent_id=str(data.get("agent_id") or ""),
            adapter_type=str(data.get("adapter_type") or "command"),
            executable_reference=str(data.get("executable_reference") or ""),
            display_name=str(data.get("display_name") or ""),
            description=str(data.get("description") or ""),
            version=str(data.get("version") or "1.0.0"),
            capabilities=tuple(
                AgentCapability.from_dict(c) for c in (data.get("capabilities") or ())
            ),
            workspace_policy=str(data.get("workspace_policy") or "isolated"),
            default_timeout_ms=int(data.get("default_timeout_ms") or 300000),
            output_limit_bytes=int(data.get("output_limit_bytes") or 1_048_576),
            environment_allowlist=tuple(data.get("environment_allowlist") or ()),
            environment_blocklist=tuple(data.get("environment_blocklist") or ("HOME", "USERPROFILE", "PATH")),
            approval_policy=str(data.get("approval_policy") or "ask_per_command"),
            health_state=str(data.get("health_state") or "unknown"),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AgentRunRequest:
    """Request to execute an external agent.

    Contains the full specification of what the agent should do,
    including objective, plan, context, and constraints.
    """

    run_id: str = field(default_factory=lambda: _new_id("run"))
    task_id: str = ""
    workspace_id: str = ""
    objective: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    allowed_capabilities: tuple[str, ...] = ()
    context_references: tuple[str, ...] = ()
    timeout_ms: int = 300000
    environment_policy: dict[str, Any] = field(default_factory=dict)
    expected_artifacts: tuple[str, ...] = ()
    approval_policy: str = "ask_per_command"
    agent_id: str = ""
    created_at: str = field(default_factory=_utc_now)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "workspace_id": self.workspace_id,
            "objective": self.objective,
            "plan": dict(self.plan),
            "allowed_capabilities": list(self.allowed_capabilities),
            "context_references": list(self.context_references),
            "timeout_ms": self.timeout_ms,
            "environment_policy": dict(self.environment_policy),
            "expected_artifacts": list(self.expected_artifacts),
            "approval_policy": self.approval_policy,
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRunRequest":
        return cls(
            run_id=str(data.get("run_id") or _new_id("run")),
            task_id=str(data.get("task_id") or ""),
            workspace_id=str(data.get("workspace_id") or ""),
            objective=str(data.get("objective") or ""),
            plan=dict(data.get("plan") or {}),
            allowed_capabilities=tuple(data.get("allowed_capabilities") or ()),
            context_references=tuple(data.get("context_references") or ()),
            timeout_ms=int(data.get("timeout_ms") or 300000),
            environment_policy=dict(data.get("environment_policy") or {}),
            expected_artifacts=tuple(data.get("expected_artifacts") or ()),
            approval_policy=str(data.get("approval_policy") or "ask_per_command"),
            agent_id=str(data.get("agent_id") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AgentRunContext:
    """Runtime context established before agent execution."""
    context_id: str = field(default_factory=lambda: _new_id("ctx"))
    run_id: str = ""
    workspace_path: str = ""
    environment: dict[str, str] = field(default_factory=dict)
    input_files: tuple[str, ...] = ()
    memory_snapshot_id: str = ""
    session_id: str = ""
    node_id: str = ""
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "run_id": self.run_id,
            "workspace_path": self.workspace_path,
            "environment": dict(self.environment),
            "input_files": list(self.input_files),
            "memory_snapshot_id": self.memory_snapshot_id,
            "session_id": self.session_id,
            "node_id": self.node_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRunContext":
        return cls(
            context_id=str(data.get("context_id") or _new_id("ctx")),
            run_id=str(data.get("run_id") or ""),
            workspace_path=str(data.get("workspace_path") or ""),
            environment={str(k): str(v) for k, v in (data.get("environment") or {}).items()},
            input_files=tuple(data.get("input_files") or ()),
            memory_snapshot_id=str(data.get("memory_snapshot_id") or ""),
            session_id=str(data.get("session_id") or ""),
            node_id=str(data.get("node_id") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
        )


@dataclass(frozen=True)
class AgentArtifact:
    """An artifact produced by an agent run."""
    artifact_id: str = field(default_factory=lambda: _new_id("art"))
    run_id: str = ""
    name: str = ""
    path: str = ""
    content_type: str = ""
    size_bytes: int = 0
    checksum: str = ""
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "name": self.name,
            "path": self.path,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentArtifact":
        return cls(
            artifact_id=str(data.get("artifact_id") or _new_id("art")),
            run_id=str(data.get("run_id") or ""),
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            content_type=str(data.get("content_type") or ""),
            size_bytes=int(data.get("size_bytes") or 0),
            checksum=str(data.get("checksum") or ""),
            created_at=str(data.get("created_at") or _utc_now()),
        )


@dataclass(frozen=True)
class AgentCommandProposal:
    """A command proposed by the agent for approval before execution."""
    proposal_id: str = field(default_factory=lambda: _new_id("cmd"))
    run_id: str = ""
    command: tuple[str, ...] = ()
    working_directory: str = ""
    description: str = ""
    risk_level: str = "medium"
    affected_files: tuple[str, ...] = ()
    is_destructive: bool = False
    estimated_runtime_ms: int = 0
    proposed_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "run_id": self.run_id,
            "command": list(self.command),
            "working_directory": self.working_directory,
            "description": self.description,
            "risk_level": self.risk_level,
            "affected_files": list(self.affected_files),
            "is_destructive": self.is_destructive,
            "estimated_runtime_ms": self.estimated_runtime_ms,
            "proposed_at": self.proposed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentCommandProposal":
        return cls(
            proposal_id=str(data.get("proposal_id") or _new_id("cmd")),
            run_id=str(data.get("run_id") or ""),
            command=tuple(data.get("command") or ()),
            working_directory=str(data.get("working_directory") or ""),
            description=str(data.get("description") or ""),
            risk_level=str(data.get("risk_level") or "medium"),
            affected_files=tuple(data.get("affected_files") or ()),
            is_destructive=bool(data.get("is_destructive", False)),
            estimated_runtime_ms=int(data.get("estimated_runtime_ms") or 0),
            proposed_at=str(data.get("proposed_at") or _utc_now()),
        )


@dataclass(frozen=True)
class AgentResourceUsage:
    """Resource consumption of an agent run."""
    wall_time_ms: int = 0
    cpu_time_ms: int = 0
    max_memory_bytes: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "wall_time_ms": self.wall_time_ms,
            "cpu_time_ms": self.cpu_time_ms,
            "max_memory_bytes": self.max_memory_bytes,
            "disk_read_bytes": self.disk_read_bytes,
            "disk_write_bytes": self.disk_write_bytes,
            "network_rx_bytes": self.network_rx_bytes,
            "network_tx_bytes": self.network_tx_bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentResourceUsage":
        return cls(
            wall_time_ms=int(data.get("wall_time_ms") or 0),
            cpu_time_ms=int(data.get("cpu_time_ms") or 0),
            max_memory_bytes=int(data.get("max_memory_bytes") or 0),
            disk_read_bytes=int(data.get("disk_read_bytes") or 0),
            disk_write_bytes=int(data.get("disk_write_bytes") or 0),
            network_rx_bytes=int(data.get("network_rx_bytes") or 0),
            network_tx_bytes=int(data.get("network_tx_bytes") or 0),
        )


@dataclass(frozen=True)
class AgentApprovalRecord:
    """A record of an approval decision made during an agent run."""
    approval_id: str = field(default_factory=lambda: _new_id("apro"))
    run_id: str = ""
    proposal_id: str = ""
    decision: str = ""  # APPROVED | DENIED | MODIFIED
    scope: str = "once"  # once | current_run | persistent
    approver: str = ""
    reason: str = ""
    decided_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "proposal_id": self.proposal_id,
            "decision": self.decision,
            "scope": self.scope,
            "approver": self.approver,
            "reason": self.reason,
            "decided_at": self.decided_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentApprovalRecord":
        return cls(
            approval_id=str(data.get("approval_id") or _new_id("apro")),
            run_id=str(data.get("run_id") or ""),
            proposal_id=str(data.get("proposal_id") or ""),
            decision=str(data.get("decision") or ""),
            scope=str(data.get("scope") or "once"),
            approver=str(data.get("approver") or ""),
            reason=str(data.get("reason") or ""),
            decided_at=str(data.get("decided_at") or _utc_now()),
        )


@dataclass(frozen=True)
class AgentRunResult:
    """Result of a completed agent run.

    Contains all information about what happened during the run:
    status, timing, exit code, summary, changed files, commands executed,
    tests executed, approval records, artifacts, warnings, errors, resource usage.
    """

    run_id: str = ""
    task_id: str = ""
    agent_id: str = ""
    status: str = ""  # COMPLETED | FAILED | CANCELLED | TIMED_OUT
    exit_code: int = -1
    summary: str = ""
    started_at: str = ""
    completed_at: str = field(default_factory=_utc_now)
    duration_ms: int = 0
    changed_files: tuple[str, ...] = ()
    diff_summary: str = ""
    commands_executed: int = 0
    tests_executed: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    approval_records: tuple[AgentApprovalRecord, ...] = ()
    artifacts: tuple[AgentArtifact, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    resource_usage: AgentResourceUsage = field(default_factory=AgentResourceUsage)
    raw_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.status == "COMPLETED" and self.exit_code == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "changed_files": list(self.changed_files),
            "diff_summary": self.diff_summary,
            "commands_executed": self.commands_executed,
            "tests_executed": self.tests_executed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed,
            "approval_records": [a.to_dict() for a in self.approval_records],
            "artifacts": [a.to_dict() for a in self.artifacts],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "resource_usage": self.resource_usage.to_dict(),
            "raw_output": self.raw_output,
            "metadata": dict(self.metadata),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentRunResult":
        return cls(
            run_id=str(data.get("run_id") or ""),
            task_id=str(data.get("task_id") or ""),
            agent_id=str(data.get("agent_id") or ""),
            status=str(data.get("status") or ""),
            exit_code=int(data.get("exit_code") or -1),
            summary=str(data.get("summary") or ""),
            started_at=str(data.get("started_at") or ""),
            completed_at=str(data.get("completed_at") or _utc_now()),
            duration_ms=int(data.get("duration_ms") or 0),
            changed_files=tuple(data.get("changed_files") or ()),
            diff_summary=str(data.get("diff_summary") or ""),
            commands_executed=int(data.get("commands_executed") or 0),
            tests_executed=int(data.get("tests_executed") or 0),
            tests_passed=int(data.get("tests_passed") or 0),
            tests_failed=int(data.get("tests_failed") or 0),
            approval_records=tuple(
                AgentApprovalRecord.from_dict(a) for a in (data.get("approval_records") or ())
            ),
            artifacts=tuple(AgentArtifact.from_dict(a) for a in (data.get("artifacts") or ())),
            warnings=tuple(data.get("warnings") or ()),
            errors=tuple(data.get("errors") or ()),
            resource_usage=AgentResourceUsage.from_dict(data.get("resource_usage") or {}),
            raw_output=str(data.get("raw_output") or ""),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )

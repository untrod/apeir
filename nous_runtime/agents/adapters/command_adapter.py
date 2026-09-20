# -*- coding: utf-8 -*-
"""CommandAgentAdapter — unified entry point for external agent execution.

This adapter integrates ProcessSupervisor, WorkspaceGuard, EnvironmentFilter,
OutputLimiter, StructuredEventParser, ArtifactCollector, and CommandPolicyEvaluator
into a single callable interface that the Runtime can use to execute external
coding agents.

Usage:
    from nous_runtime.agents.adapters.command_adapter import CommandAgentAdapter
    from nous_runtime.agents.external.models import AgentDescriptor

    desc = AgentDescriptor(
        agent_id="agent.coding",
        executable_reference="/usr/local/bin/coding-agent",
    )
    adapter = CommandAgentAdapter(desc)
    result = adapter.execute(request, context)
"""

from __future__ import annotations

import logging

from nous_runtime.agents.adapters.policy_evaluator import CommandPolicyEvaluator
from nous_runtime.agents.adapters.supervisor import ProcessSupervisor
from nous_runtime.agents.external.models import (
    AgentCommandProposal,
    AgentDescriptor,
    AgentProcessState,
    AgentRunContext,
    AgentRunRequest,
    AgentRunResult,
)

_log = logging.getLogger("nous.agents.adapter")


class CommandAgentAdapter:
    """Vendor-neutral adapter for executing external coding agents.

    This adapter does not depend on any specific external tool name.
    The executable is configured via AgentDescriptor.executable_reference.
    """

    def __init__(self, descriptor: AgentDescriptor):
        errors = descriptor.validate()
        if errors:
            raise ValueError(f"Invalid agent descriptor: {'; '.join(errors)}")
        self._descriptor = descriptor
        self._supervisor = ProcessSupervisor(descriptor)

    @property
    def descriptor(self) -> AgentDescriptor:
        return self._descriptor

    def execute(
        self, request: AgentRunRequest, context: AgentRunContext
    ) -> AgentRunResult:
        """Execute the agent with the given request and context.

        This is the primary entry point for the Runtime.
        """
        if request.agent_id and request.agent_id != self._descriptor.agent_id:
            return AgentRunResult(
                run_id=request.run_id,
                task_id=request.task_id,
                agent_id=request.agent_id,
                status="FAILED",
                exit_code=-1,
                errors=(f"Agent ID mismatch: {request.agent_id} != {self._descriptor.agent_id}",),
            )

        # Override request fields from descriptor
        request = AgentRunRequest(
            run_id=request.run_id,
            task_id=request.task_id,
            workspace_id=request.workspace_id,
            objective=request.objective,
            plan=request.plan,
            allowed_capabilities=request.allowed_capabilities,
            context_references=request.context_references,
            timeout_ms=request.timeout_ms or self._descriptor.default_timeout_ms,
            environment_policy=request.environment_policy,
            expected_artifacts=request.expected_artifacts,
            approval_policy=request.approval_policy or self._descriptor.approval_policy,
            agent_id=self._descriptor.agent_id,
        )

        return self._supervisor.run(request, context)

    def evaluate_command(self, command: AgentCommandProposal) -> str:
        """Evaluate a proposed command against policy.

        Returns: "allow", "ask", or "deny"
        """
        evaluator = CommandPolicyEvaluator(descriptor=self._descriptor)
        return evaluator.evaluate(command)

    def cancel(self) -> None:
        """Cancel the currently running agent process."""
        self._supervisor.cancel()

    @property
    def state(self) -> AgentProcessState:
        return self._supervisor.state

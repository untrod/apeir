"""Agent Execution Runtime facade.

This service manages execution state and injected invocation handlers.  It
does not call real tools or models by itself.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from typing import Any, Callable, Mapping

from nous_runtime.agent.budget import AgentBudgetLedger
from nous_runtime.agent.checkpoint import AgentCheckpointManager
from nous_runtime.agent.errors import (
    AgentBoundaryError,
    AgentBudgetError,
    AgentLifecycleError,
)
from nous_runtime.agent.execution_state import (
    AgentExecutionRecord,
    AgentExecutionState,
    InvocationKind,
    transition_execution,
)
from nous_runtime.agent.invocation import (
    InvocationRequest,
    ModelInvocationBoundary,
    ToolInvocationBoundary,
)
from nous_runtime.agent.models import AgentProfile, AgentState
from nous_runtime.agent.termination import (
    TerminationController,
    TerminationPolicy,
    TerminationReason,
)
from nous_runtime.core.events import EventEnvelope
from nous_runtime.execution import ExecutionContext


InvocationHandler = Callable[[InvocationRequest], Any]


class AgentExecutionRuntime:
    def __init__(
        self,
        *,
        checkpoints: AgentCheckpointManager | None = None,
    ) -> None:
        self.checkpoints = checkpoints or AgentCheckpointManager()
        self.termination = TerminationController()
        self._executions: dict[str, AgentExecutionRecord] = {}
        self._profiles: dict[str, AgentProfile] = {}
        self._contexts: dict[str, ExecutionContext] = {}
        self._ledgers: dict[str, AgentBudgetLedger] = {}
        self._policies: dict[str, TerminationPolicy] = {}
        self._lock = threading.RLock()

    def create(
        self,
        *,
        task_id: str,
        profile: AgentProfile,
        context: ExecutionContext | None = None,
        termination_policy: TerminationPolicy | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> AgentExecutionRecord:
        if profile.state not in {
            AgentState.REGISTERED,
            AgentState.READY,
            AgentState.RUNNING,
            AgentState.WAITING,
        }:
            raise AgentLifecycleError(
                f"agent profile is not executable: {profile.state.value}",
                context={"agent_id": profile.agent_id},
            )
        if context is not None and context.task_id != task_id:
            raise AgentLifecycleError(
                "execution context task_id mismatch",
                context={"task_id": task_id},
            )
        execution = AgentExecutionRecord.create(
            task_id=task_id,
            agent_id=profile.agent_id,
            metadata=metadata,
        )
        policy = termination_policy or TerminationPolicy(
            max_steps=profile.manifest.budget.max_steps,
            max_runtime_ms=profile.manifest.budget.max_runtime_ms,
        )
        with self._lock:
            self._executions[execution.run_id] = execution
            self._profiles[execution.run_id] = profile
            self._contexts[execution.run_id] = context or ExecutionContext(
                task_id=task_id,
                agent_id=profile.agent_id,
            )
            self._ledgers[execution.run_id] = AgentBudgetLedger(
                profile.manifest.budget
            )
            self._policies[execution.run_id] = policy
        self._emit(execution.run_id, "agent.execution.created")
        return execution

    def start(self, run_id: str) -> AgentExecutionRecord:
        execution = self.require(run_id)
        execution = transition_execution(
            execution, AgentExecutionState.STARTING
        )
        execution = transition_execution(execution, AgentExecutionState.RUNNING)
        self._set(execution)
        self._emit(run_id, "agent.execution.started")
        return execution

    def wait(self, run_id: str, *, message: str = "") -> AgentExecutionRecord:
        execution = transition_execution(
            self.require(run_id),
            AgentExecutionState.WAITING,
            message=message,
        )
        self._set(execution)
        self._emit(run_id, "agent.execution.waiting", {"message": message})
        return execution

    def invoke_tool(
        self,
        run_id: str,
        *,
        tool_id: str,
        capability_id: str,
        handler: InvocationHandler,
        parameters: Mapping[str, Any] | None = None,
        estimated_cost_usd: float = 0.0,
        estimated_tokens: int = 0,
        estimated_runtime_ms: int = 0,
    ):
        execution = self._require_running(run_id)
        profile = self._profiles[run_id]
        capabilities = {
            item.capability_id for item in profile.manifest.capabilities
        }
        boundary = ToolInvocationBoundary(
            allowed_tools=capabilities,
            allowed_capabilities=capabilities,
            ledger=self._ledgers[run_id],
        )
        request = InvocationRequest(
            run_id=run_id,
            agent_id=execution.agent_id,
            kind=InvocationKind.TOOL,
            target=tool_id,
            capability_id=capability_id,
            parameters=dict(parameters or {}),
            estimated_cost_usd=estimated_cost_usd,
            estimated_tokens=estimated_tokens,
            estimated_runtime_ms=estimated_runtime_ms,
        )
        return self._invoke(run_id, boundary, request, handler)

    def invoke_model(
        self,
        run_id: str,
        *,
        model_id: str,
        capability_id: str,
        handler: InvocationHandler,
        parameters: Mapping[str, Any] | None = None,
        estimated_cost_usd: float = 0.0,
        estimated_tokens: int = 0,
        estimated_runtime_ms: int = 0,
    ):
        execution = self._require_running(run_id)
        profile = self._profiles[run_id]
        capabilities = {
            item.capability_id for item in profile.manifest.capabilities
        }
        models = {
            item.model_id
            for item in profile.manifest.capabilities
            if item.model_id
        }
        boundary = ModelInvocationBoundary(
            allowed_models=models,
            allowed_capabilities=capabilities,
            ledger=self._ledgers[run_id],
        )
        request = InvocationRequest(
            run_id=run_id,
            agent_id=execution.agent_id,
            kind=InvocationKind.MODEL,
            target=model_id,
            capability_id=capability_id,
            parameters=dict(parameters or {}),
            estimated_cost_usd=estimated_cost_usd,
            estimated_tokens=estimated_tokens,
            estimated_runtime_ms=estimated_runtime_ms,
        )
        return self._invoke(run_id, boundary, request, handler)

    def checkpoint(self, run_id: str):
        execution = self.require(run_id)
        if execution.state not in {
            AgentExecutionState.RUNNING,
            AgentExecutionState.WAITING,
        }:
            raise AgentLifecycleError(
                "only running or waiting executions can be checkpointed"
            )
        ledger = self._ledgers[run_id]
        ledger.consume(checkpoints=1)
        execution = transition_execution(
            execution,
            AgentExecutionState.CHECKPOINTED,
        )
        checkpoint = self.checkpoints.save(
            execution,
            ledger.usage,
            self._policies[run_id],
        )
        execution = replace(
            execution,
            checkpoint_id=checkpoint.checkpoint_id,
        )
        self._set(execution)
        self._emit(
            run_id,
            "agent.execution.checkpointed",
            {"checkpoint_id": checkpoint.checkpoint_id},
        )
        return checkpoint

    def resume(self, run_id: str) -> AgentExecutionRecord:
        execution = transition_execution(
            self.require(run_id),
            AgentExecutionState.RUNNING,
        )
        self._set(execution)
        self._emit(run_id, "agent.execution.resumed")
        return execution

    def restore(
        self,
        checkpoint_id: str,
        *,
        profile: AgentProfile,
        context: ExecutionContext | None = None,
    ) -> AgentExecutionRecord:
        snapshot = self.checkpoints.restore(checkpoint_id)
        execution = snapshot.execution
        if execution.agent_id != profile.agent_id:
            raise AgentLifecycleError(
                "checkpoint agent identity mismatch",
                context={"checkpoint_id": checkpoint_id},
            )
        with self._lock:
            self._executions[execution.run_id] = execution
            self._profiles[execution.run_id] = profile
            self._contexts[execution.run_id] = context or ExecutionContext(
                task_id=execution.task_id,
                agent_id=profile.agent_id,
            )
            self._ledgers[execution.run_id] = AgentBudgetLedger(
                profile.manifest.budget,
                snapshot.usage,
            )
            self._policies[execution.run_id] = snapshot.termination_policy
        return execution

    def complete(
        self,
        run_id: str,
        *,
        message: str = "",
    ) -> AgentExecutionRecord:
        execution = transition_execution(
            self.require(run_id),
            AgentExecutionState.COMPLETED,
            reason=TerminationReason.COMPLETED.value,
            message=message,
        )
        self._set(execution)
        self._emit(run_id, "agent.execution.completed")
        return execution

    def fail(
        self,
        run_id: str,
        *,
        message: str = "",
    ) -> AgentExecutionRecord:
        """Finish a running execution with an explicit failure outcome."""
        execution = transition_execution(
            self.require(run_id),
            AgentExecutionState.FAILED,
            reason=TerminationReason.ERROR.value,
            message=message,
        )
        self._set(execution)
        self._emit(
            run_id,
            "agent.execution.failed",
            {"message": message},
        )
        return execution

    def cancel(
        self,
        run_id: str,
        *,
        message: str = "",
    ) -> AgentExecutionRecord:
        execution = transition_execution(
            self.require(run_id),
            AgentExecutionState.CANCELLED,
            reason=TerminationReason.CANCELLED.value,
            message=message,
        )
        self._set(execution)
        self._emit(run_id, "agent.execution.cancelled")
        return execution

    def require(self, run_id: str) -> AgentExecutionRecord:
        with self._lock:
            execution = self._executions.get(str(run_id))
        if execution is None:
            raise AgentLifecycleError(
                f"agent execution not found: {run_id}",
                context={"run_id": str(run_id)},
            )
        return execution

    def context_for(self, run_id: str) -> ExecutionContext:
        self.require(run_id)
        return self._contexts[run_id]

    def budget_for(self, run_id: str) -> AgentBudgetLedger:
        self.require(run_id)
        return self._ledgers[run_id]

    def list(self) -> list[AgentExecutionRecord]:
        with self._lock:
            return sorted(
                self._executions.values(),
                key=lambda item: (item.created_at, item.run_id),
            )

    def _invoke(self, run_id, boundary, request, handler):
        try:
            invocation = boundary.invoke(request, handler)
        except (AgentBoundaryError, AgentBudgetError) as exc:
            invocation = boundary.denied_record(request, exc)
            execution = self.require(run_id).with_invocation(invocation)
            if isinstance(exc, AgentBudgetError):
                execution = transition_execution(
                    execution,
                    AgentExecutionState.TERMINATED,
                    reason=TerminationReason.BUDGET_EXHAUSTED.value,
                    message=str(exc),
                )
            self._set(execution)
            self._emit(
                run_id,
                "agent.invocation.denied",
                {"invocation_id": invocation.invocation_id},
            )
            return invocation
        execution = self.require(run_id).with_invocation(invocation)
        self._set(execution)
        self._emit(
            run_id,
            "agent.invocation.completed",
            {
                "invocation_id": invocation.invocation_id,
                "status": invocation.status.value,
            },
        )
        decision = self.termination.evaluate(
            execution,
            self._policies[run_id],
            self._ledgers[run_id],
        )
        if decision.terminate:
            target = (
                AgentExecutionState.FAILED
                if decision.reason is TerminationReason.ERROR
                else AgentExecutionState.TIMED_OUT
                if decision.reason is TerminationReason.TIMEOUT
                else AgentExecutionState.TERMINATED
            )
            execution = transition_execution(
                execution,
                target,
                reason=decision.reason.value if decision.reason else "",
                message=decision.message,
            )
            self._set(execution)
        return invocation

    def _require_running(self, run_id: str) -> AgentExecutionRecord:
        execution = self.require(run_id)
        if execution.state is not AgentExecutionState.RUNNING:
            raise AgentLifecycleError(
                f"agent execution is not running: {execution.state.value}",
                context={"run_id": run_id},
            )
        return execution

    def _set(self, execution: AgentExecutionRecord) -> None:
        with self._lock:
            self._executions[execution.run_id] = execution

    def _emit(
        self,
        run_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        context = self._contexts.get(run_id)
        if context is None:
            return
        context.add_event(
            EventEnvelope(
                event_type=event_type,
                source="agent.execution_runtime",
                payload={"run_id": run_id, **dict(payload or {})},
            )
        )


__all__ = ["AgentExecutionRuntime", "InvocationHandler"]

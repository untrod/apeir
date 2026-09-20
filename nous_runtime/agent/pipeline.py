"""Adapter that executes Runtime pipeline work through Agent lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from nous_runtime.agent.execution_state import (
    AgentExecutionState,
    InvocationStatus,
)
from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import AgentProfile, AgentState
from nous_runtime.agent.runtime import AgentExecutionRuntime
from nous_runtime.execution import ExecutionContext


AgentWorkHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class RuntimeAgentResult:
    ok: bool
    output: Any
    run_id: str
    agent_id: str
    state: str
    invocation: dict[str, Any]
    budget: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "state": self.state,
            "invocation": dict(self.invocation),
            "budget": dict(self.budget),
            "events": [dict(item) for item in self.events],
            "error": self.error,
        }


class RuntimeAgentExecutor:
    """Use AgentExecutionRuntime without changing capability ownership."""

    def __init__(
        self,
        runtime: AgentExecutionRuntime | None = None,
    ) -> None:
        self.runtime = runtime or AgentExecutionRuntime()

    def execute(
        self,
        *,
        task_id: str,
        capability_id: str,
        handler: AgentWorkHandler,
        parameters: dict[str, Any] | None = None,
        agent_id: str = "agent.runtime_worker",
        estimated_cost_usd: float = 0.0,
        estimated_tokens: int = 0,
        estimated_runtime_ms: int = 0,
    ) -> RuntimeAgentResult:
        manifest = build_agent_manifest(
            "Runtime Worker",
            agent_id=agent_id,
            description="Built-in governed Runtime execution worker",
            capabilities=(capability_id,),
            permissions=("runtime.execute",),
            budget={
                "max_cost_usd": max(1.0, estimated_cost_usd),
                "max_tokens": max(10_000, estimated_tokens),
                "max_runtime_ms": max(60_000, estimated_runtime_ms),
                "max_invocations": 10,
                "max_tool_invocations": 10,
                "max_model_invocations": 10,
                "max_checkpoints": 3,
                "max_steps": 10,
            },
        )
        profile = AgentProfile(
            manifest=manifest,
            state=AgentState.READY,
        )
        execution = self.runtime.create(
            task_id=task_id,
            profile=profile,
            context=ExecutionContext(
                task_id=task_id,
                agent_id=agent_id,
            ),
            metadata={"source": "runtime.pipeline"},
        )
        execution = self.runtime.start(execution.run_id)
        captured: dict[str, Any] = {}

        def invoke(parameters_request) -> Any:
            output = handler(dict(parameters_request.parameters))
            captured["output"] = output
            return output

        invocation = self.runtime.invoke_tool(
            execution.run_id,
            tool_id=capability_id,
            capability_id=capability_id,
            handler=invoke,
            parameters=dict(parameters or {}),
            estimated_cost_usd=estimated_cost_usd,
            estimated_tokens=estimated_tokens,
            estimated_runtime_ms=estimated_runtime_ms,
        )
        current = self.runtime.require(execution.run_id)
        if (
            invocation.status is InvocationStatus.COMPLETED
            and current.state is AgentExecutionState.RUNNING
        ):
            current = self.runtime.complete(
                execution.run_id,
                message="Runtime capability completed",
            )
        context = self.runtime.context_for(execution.run_id)
        budget = self.runtime.budget_for(execution.run_id)
        ok = (
            invocation.status is InvocationStatus.COMPLETED
            and current.state is AgentExecutionState.COMPLETED
        )
        return RuntimeAgentResult(
            ok=ok,
            output=captured.get("output"),
            run_id=execution.run_id,
            agent_id=agent_id,
            state=current.state.value,
            invocation=invocation.to_dict(),
            budget=budget.usage.to_dict(),
            events=tuple(event.to_dict() for event in context.events),
            error="" if ok else invocation.message,
        )


__all__ = [
    "AgentWorkHandler",
    "RuntimeAgentExecutor",
    "RuntimeAgentResult",
]

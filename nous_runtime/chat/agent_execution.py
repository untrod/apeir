"""Agent lifecycle ownership for one provider-neutral chat execution."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

from nous_runtime.agent.execution_state import (
    AgentExecutionState,
    InvocationStatus,
)
from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import (
    AgentBudget,
    AgentCapabilityBinding,
    AgentProfile,
    AgentState,
)
from nous_runtime.agent.runtime import AgentExecutionRuntime
from nous_runtime.execution import ExecutionContext


class ChatAgentExecution:
    """Register chat model and tool calls in one Agent execution record."""

    MODEL_CAPABILITY = "model.chat"
    MODEL_TARGET = "model-router"

    def __init__(
        self,
        *,
        task_id: str,
        workspace_id: str,
        session_id: str,
        tool_names: set[str] | frozenset[str],
        max_model_invocations: int,
        runtime: AgentExecutionRuntime | None = None,
    ) -> None:
        self.runtime = runtime or AgentExecutionRuntime()
        model_limit = max(1, int(max_model_invocations))
        tool_limit = max(1, model_limit * 8)
        bindings = [
            AgentCapabilityBinding(
                capability_id=self.MODEL_CAPABILITY,
                model_id=self.MODEL_TARGET,
            )
        ]
        bindings.extend(
            AgentCapabilityBinding(capability_id=name)
            for name in sorted(tool_names)
            if name
        )
        base = build_agent_manifest(
            "Workspace Agent",
            agent_id="agent.nous.workspace",
            description="Provider-neutral governed workspace execution",
            permissions=("runtime.execute", "workspace.read", "workspace.effect"),
        )
        manifest = replace(
            base,
            capabilities=tuple(bindings),
            budget=AgentBudget(
                max_tokens=1_000_000,
                max_runtime_ms=30 * 60 * 1000,
                max_invocations=model_limit + tool_limit,
                max_tool_invocations=tool_limit,
                max_model_invocations=model_limit,
                max_checkpoints=1,
                max_steps=model_limit + tool_limit,
            ),
        )
        execution = self.runtime.create(
            task_id=task_id,
            profile=AgentProfile(manifest=manifest, state=AgentState.READY),
            context=ExecutionContext(
                task_id=task_id,
                agent_id=manifest.identity.agent_id,
                metadata={
                    "workspace_id": workspace_id,
                    "session_id": session_id,
                    "source": "chat.gateway",
                },
            ),
            metadata={"source": "chat.gateway"},
        )
        self.run_id = execution.run_id
        self.runtime.start(self.run_id)

    def invoke_model(self, handler: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
        captured: dict[str, Any] = {}

        def invoke(_request: Any) -> Any:
            value = handler()
            captured["value"] = value
            return value

        record = self.runtime.invoke_model(
            self.run_id,
            model_id=self.MODEL_TARGET,
            capability_id=self.MODEL_CAPABILITY,
            handler=invoke,
        )
        return captured.get("value"), record.to_dict()

    def invoke_tool(
        self,
        name: str,
        arguments: Mapping[str, Any],
        handler: Callable[[], Any],
    ) -> tuple[Any, dict[str, Any]]:
        captured: dict[str, Any] = {}

        def invoke(_request: Any) -> Any:
            value = handler()
            captured["value"] = value
            return value

        record = self.runtime.invoke_tool(
            self.run_id,
            tool_id=name,
            capability_id=name,
            handler=invoke,
            parameters=dict(arguments),
        )
        value = captured.get("value")
        if record.status is not InvocationStatus.COMPLETED and value is None:
            value = {
                "ok": False,
                "error": record.message or "Agent invocation was not completed.",
                "error_code": record.error_code,
            }
        return value, record.to_dict()

    def finish(self, *, ok: bool, paused: bool = False, message: str = "") -> dict[str, Any]:
        current = self.runtime.require(self.run_id)
        if current.state is AgentExecutionState.RUNNING:
            if paused:
                checkpoint = self.runtime.checkpoint(self.run_id)
                current = self.runtime.require(self.run_id)
                checkpoint_id = checkpoint.checkpoint_id
            elif ok:
                current = self.runtime.complete(self.run_id, message=message)
                checkpoint_id = ""
            else:
                current = self.runtime.fail(self.run_id, message=message)
                checkpoint_id = ""
        else:
            checkpoint_id = current.checkpoint_id
        context = self.runtime.context_for(self.run_id)
        budget = self.runtime.budget_for(self.run_id)
        return {
            "run_id": self.run_id,
            "agent_id": current.agent_id,
            "state": current.state.value,
            "checkpoint_id": checkpoint_id or current.checkpoint_id,
            "budget": budget.usage.to_dict(),
            "invocations": [item.to_dict() for item in current.invocations],
            "events": [item.to_dict() for item in context.events],
        }


__all__ = ["ChatAgentExecution"]

"""Production component assembly for durable Work execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from nous_runtime.work.models import WorkContext, WorkSnapshot


@dataclass(frozen=True)
class WorkExecutionComponents:
    """One execution-bound set of adapters; none of them own Work state."""

    tools: Any
    deliberator: Callable[[WorkContext], Any]
    verifier: Callable[[WorkContext], Any] | None


def build_work_components(
    root: str | Path,
    snapshot: WorkSnapshot,
) -> WorkExecutionComponents:
    """Assemble existing governed runtimes for one Work checkpoint."""
    from nous_runtime.chat.agent_tools import WorkspaceToolRuntime, mutation_is_explicit
    from nous_runtime.model_runtime import get_gateway_facade
    from nous_runtime.skills import SkillToolRuntime
    from nous_runtime.tools import ArtifactToolRuntime, GitToolRuntime, ToolCatalog
    from nous_runtime.web import WebToolRuntime
    from nous_runtime.work.deliberation import (
        ModelWorkDeliberator,
        verify_recorded_work,
    )

    workspace = Path(root).resolve()
    options = dict(snapshot.execution_options)
    read_only = bool(options.get("read_only", False))
    allow_mutations = not read_only and mutation_is_explicit(snapshot.goal.objective)

    tools = ToolCatalog()
    tools.register_runtime(
        WorkspaceToolRuntime(str(workspace), allow_mutations=allow_mutations)
    )
    tools.register_runtime(GitToolRuntime(workspace), provider_id="git-sandbox")
    tools.register_runtime(
        ArtifactToolRuntime(workspace, allow_mutations=allow_mutations),
        provider_id="artifact-runtime",
    )
    tools.register_runtime(
        SkillToolRuntime(workspace, allow_mutations=allow_mutations),
        provider_id="skill-registry",
    )
    tools.register_runtime(WebToolRuntime(workspace), provider_id="web-runtime")

    facade = get_gateway_facade(required=True)
    deliberator = ModelWorkDeliberator(
        facade,
        tool_specifications=tools.prompt_specifications(),
        tool_capabilities=tools.categories(),
        preferred_model=str(options.get("preferred_model") or ""),
    )
    return WorkExecutionComponents(
        tools=tools,
        deliberator=deliberator,
        verifier=verify_recorded_work,
    )


__all__ = ["WorkExecutionComponents", "build_work_components"]

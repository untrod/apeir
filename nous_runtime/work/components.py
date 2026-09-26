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
    from nous_runtime.cli.provider_setup import load_providers_from_config
    from nous_runtime.model_runtime import get_gateway_facade
    from nous_runtime.model_runtime.factory import gateway_service
    from nous_runtime.skills import SkillToolRuntime
    from nous_runtime.tools import (
        ArtifactToolRuntime,
        GitToolRuntime,
        ProcessSessionToolRuntime,
        ToolCatalog,
    )
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
    workspace_tools = WorkspaceToolRuntime(
        str(workspace), allow_mutations=allow_mutations
    )
    tools.register_runtime(workspace_tools, excluded_tool_ids={"run_command"})
    if allow_mutations:
        tools.register_runtime(
            ProcessSessionToolRuntime(workspace_tools),
            provider_id="process-session",
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

    provider_count = load_providers_from_config(workspace)
    if not provider_count:
        provider_count = load_providers_from_config()
    facade = get_gateway_facade(required=False)
    if facade is None and provider_count:
        gateway_service.configure_from_providers()
        facade = get_gateway_facade(required=True)
    elif facade is None:
        facade = get_gateway_facade(required=True)
    deliberator = ModelWorkDeliberator(
        facade,
        tool_specifications=tools.prompt_specifications(),
        tool_capabilities=tools.categories(),
        preferred_model=str(options.get("preferred_model") or ""),
        timeout_s=float(options.get("model_timeout_s") or 180.0),
        max_output_tokens=int(options.get("decision_max_output_tokens") or 1024),
    )
    return WorkExecutionComponents(
        tools=tools,
        deliberator=deliberator,
        verifier=verify_recorded_work,
    )


__all__ = ["WorkExecutionComponents", "build_work_components"]

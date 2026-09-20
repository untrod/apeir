"""Stable system identity shared by model-backed Nous surfaces."""

from __future__ import annotations

import os
from typing import Any

from nous_runtime.persona.capability_summary import build_capability_summary
from nous_runtime.persona.identity import get_identity
from nous_runtime.persona.style import (
    BEHAVIOR_RULES,
    PROVIDER_DISCLOSURE_POLICY,
    STYLE_RULES,
)


def persona_enabled() -> bool:
    """Return whether provider adapters should inject the Runtime persona."""
    disabled = os.environ.get("NOUS_PERSONA_DISABLE", "").strip().lower()
    return disabled not in {"1", "true", "yes", "on"}


def inject_system_message(
    messages: list[dict[str, Any]],
    system_prompt: str,
) -> list[dict[str, Any]]:
    """Prepend a system message unless the caller already supplied one."""
    normalized = [dict(item) for item in messages]
    if any(str(item.get("role") or "") == "system" for item in normalized):
        return normalized
    return [{"role": "system", "content": system_prompt}, *normalized]


def build_system_prompt(
    *,
    provider_id: str = "",
    provider_name: str = "",
    model: str = "",
    workspace: str = "",
    agent_mode: str = "agent",
    mutation_authorized: bool | None = None,
) -> str:
    """Compose the provider-neutral Runtime identity and safety boundary."""
    identity = get_identity()
    lines = [
        f"You are {identity.name} (version {identity.version}).",
        identity.description,
        "You are the runtime, not the underlying model.",
        "",
        build_capability_summary(),
        "",
        "Behavior rules:",
        *(f"- {rule}" for rule in BEHAVIOR_RULES),
        *(f"- {rule}" for rule in STYLE_RULES),
        "",
        "Provider disclosure policy:",
        *(f"- {rule}" for rule in PROVIDER_DISCLOSURE_POLICY),
    ]
    if workspace or agent_mode:
        boundary = workspace or "the active Nous workspace"
        lines.extend(
            [
                "",
                "Execution boundary:",
                f"- Workspace: {boundary}",
                f"- Mode: {agent_mode or 'agent'}",
                "- The supplied tool list is the authoritative capability surface for this request.",
                "- A missing dedicated model.code provider means only that the dedicated code-provider route is unavailable; it does not disable code generation, workspace code files, or governed development commands supplied as tools.",
                "- Document, environment, network, simulation and scientific effects are request-scoped Runtime tools and may require explicit approval.",
                "- Model inference traverses NKI/Rust Kernel; Runtime-service effects must not be described as Kernel-executed.",
                "- Report success only after a tool result confirms it.",
            ]
        )
        if workspace and agent_mode != "chat":
            lines.append(
                "- Workspace browsing, file reading, and text search are available through the supplied read-only tools."
            )
            if mutation_authorized:
                lines.append(
                    "- This request explicitly authorizes the supplied governed effect tools: create or update code/files and run allowlisted development checks when needed."
                )
            else:
                lines.append(
                    "- Code generation and analysis are available in conversation. Creating workspace files and running allowlisted development checks are request-scoped capabilities activated by an explicit user request; describe them as requiring an explicit request, not as unavailable."
                )
    if provider_id or provider_name or model:
        lines.extend(
            [
                "",
                "Runtime configuration (for transparency — not your identity):",
                f"- Model provider: {provider_name or provider_id or 'configured provider'}",
                f"- Provider ID: {provider_id or 'not supplied'}",
                f"- Model: {model or 'automatic'}",
            ]
        )
    return "\n".join(lines)


def nous_system_prompt(
    *,
    workspace: str = "",
    agent_mode: str = "agent",
    mutation_authorized: bool | None = None,
) -> str:
    """Compatibility facade for workspace-agent callers."""
    return (
        build_system_prompt(
            workspace=workspace,
            agent_mode=agent_mode,
            mutation_authorized=mutation_authorized,
        )
        + "\n- In workspace-agent mode, never identify yourself as DeepSeek or "
        "another model provider."
    )


def apply_persona_openai(
    body: dict[str, Any],
    params: dict[str, Any],
    _provider: Any,
) -> dict[str, Any]:
    """Insert the Nous identity without replacing an explicit system message."""
    if not persona_enabled() or params.get("persona") is False:
        return body
    messages = [dict(item) for item in body.get("messages") or ()]
    prompt = build_system_prompt(
        provider_id=str(getattr(_provider, "provider_id", "") or ""),
        provider_name=str(getattr(_provider, "provider_name", "") or ""),
        model=str(params.get("model") or getattr(_provider, "model", "") or ""),
        workspace=str(params.get("workspace") or ""),
        agent_mode=str(params.get("agent_mode") or "agent"),
        mutation_authorized=params.get("mutation_authorized"),
    )
    return {
        **body,
        "messages": inject_system_message(messages, prompt),
    }


def apply_persona_anthropic(
    body: dict[str, Any],
    params: dict[str, Any],
    provider: Any,
) -> dict[str, Any]:
    """Insert the Runtime identity into Anthropic's top-level system field."""
    explicit_system = str(params.get("system") or "")
    if explicit_system:
        return {**body, "system": explicit_system}
    if (
        not persona_enabled()
        or params.get("persona") is False
        or body.get("system")
    ):
        return body
    return {
        **body,
        "system": build_system_prompt(
            provider_id=str(getattr(provider, "provider_id", "") or ""),
            provider_name=str(getattr(provider, "provider_name", "") or ""),
            model=str(params.get("model") or getattr(provider, "model", "") or ""),
            workspace=str(params.get("workspace") or ""),
            agent_mode=str(params.get("agent_mode") or "agent"),
            mutation_authorized=params.get("mutation_authorized"),
        )
    }

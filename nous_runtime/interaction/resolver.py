"""Intent-to-runtime resolution helpers."""

from __future__ import annotations

from dataclasses import replace

from nous_runtime.interaction.models import IntentDecision
from nous_runtime.interaction.router import route_intent


def resolve_intent(decision: IntentDecision) -> IntentDecision:
    """Attach route and workspace resolution without mutating the decision."""
    workspace_id = decision.workspace
    if not workspace_id:
        try:
            from nous_runtime.workspace.resolver import resolve_workspace

            resolved = resolve_workspace("")
            workspace_id = resolved.workspace_id
        except Exception:
            workspace_id = "default"
    return replace(decision, workspace=workspace_id, route=route_intent(decision))

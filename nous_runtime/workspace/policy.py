"""Workspace isolation policy helpers."""

from __future__ import annotations

from nous_runtime.workspace.models import Workspace


def can_access_context(requesting: Workspace, target: Workspace) -> bool:
    if requesting.id == target.id:
        return True
    return requesting.context_policy == "shared" and target.context_policy == "shared"


def can_share_experience(requesting: Workspace, target: Workspace) -> bool:
    if requesting.id == target.id:
        return True
    return requesting.memory_policy == "shared" and target.memory_policy == "shared"

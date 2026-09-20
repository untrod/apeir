# -*- coding: utf-8 -*-
"""ProjectProvider — reads context from the project workspace and plan state."""

from __future__ import annotations

import logging

from nous_runtime.context.models import ContextItem
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.providers.project")


class ProjectProvider:
    """Collects context items from the project workspace.

    Reads project configuration, current phase, checkpoints, and plans.
    """

    source_type: str = ContextSource.PROJECT.value

    def __init__(self, workspace_path: str = ""):
        self._workspace = workspace_path

    def _get_workspace(self) -> str | None:
        if self._workspace:
            return self._workspace
        try:
            from nous_runtime.project.workspace import find_workspace
            return find_workspace()
        except Exception:
            return None



    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect project context items."""
        items: list[ContextItem] = []
        ws = self._get_workspace()
        if ws is None:
            return items

        try:
            from nous_runtime.project.workspace import read_project_config

            config = read_project_config(workspace=ws) or {}
            project_name = config.get("name", config.get("project_name", ""))
            project_id = config.get("project_id", config.get("id", ""))

            if project_name:
                items.append(ContextItem(
                    content=f"Project: {project_name}",
                    source_type=ContextSource.PROJECT.value,
                    source_id=project_id or "project_config",
                    importance=0.9,
                    confidence=1.0,
                    permission="read",
                    tags=("project", "identity"),
                ))

            # Current phase / status
            phase = config.get("phase", config.get("current_phase", ""))
            if phase:
                items.append(ContextItem(
                    content=f"Current phase: {phase}",
                    source_type=ContextSource.PROJECT.value,
                    source_id=project_id or "project_config",
                    importance=0.8,
                    confidence=1.0,
                    permission="read",
                    tags=("project", "phase"),
                ))

            # Next step
            next_step = config.get("next_step", config.get("next", ""))
            if next_step:
                items.append(ContextItem(
                    content=f"Next: {next_step}",
                    source_type=ContextSource.PROJECT.value,
                    source_id=project_id or "project_config",
                    importance=0.7,
                    confidence=0.9,
                    permission="read",
                    tags=("project", "planning"),
                ))

            # Description
            desc = config.get("description", "")
            if desc:
                items.append(ContextItem(
                    content=f"Description: {desc}",
                    source_type=ContextSource.PROJECT.value,
                    source_id=project_id or "project_config",
                    importance=0.6,
                    confidence=1.0,
                    permission="read",
                    tags=("project", "description"),
                ))

            # Checkpoints
            checkpoints = config.get("checkpoints", [])
            for cp in checkpoints[-5:]:
                cp_name = cp.get("name", cp.get("label", str(cp)))
                items.append(ContextItem(
                    content=f"Checkpoint: {cp_name}",
                    source_type=ContextSource.PROJECT.value,
                    source_id=project_id or "project_config",
                    importance=0.5,
                    confidence=0.9,
                    permission="read",
                    tags=("project", "checkpoint"),
                ))

        except Exception as exc:
            _log.warning("ProjectProvider.collect failed: %s", exc)

        return items[:limit]



    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: f"Project context item {iid} — sourced from workspace configuration." for iid in item_ids}

    def health(self) -> ProviderHealth:
        ws = self._get_workspace()
        available = ws is not None
        item_count = 0
        last = ""
        error = ""
        if available:
            try:
                from nous_runtime.project.workspace import read_project_config
                config = read_project_config(workspace=ws) or {}
                item_count = 1 if config else 0
            except Exception as exc:
                error = str(exc)
                available = False
        return ProviderHealth(
            source=ContextSource.PROJECT.value,
            available=available,
            item_count=item_count,
            last_collected_at=last,
            error=error,
        )

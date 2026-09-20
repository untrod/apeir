"""OpenClaw Workspace → Nous Namespace / Workspace adapter.

Maps OpenClaw workspace isolation to Nous namespace and workspace primitives,
providing stronger isolation, state persistence, and cross-session sharing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("nous.integrations.openclaw.session")


@dataclass
class WorkspaceMapping:
    """Maps an OpenClaw workspace to a Nous namespace + workspace."""
    openclaw_workspace_id: str
    nous_namespace: str
    nous_workspace_root: str | None = None
    isolation_level: str = "full"  # full, shared-read, shared-readwrite
    allowed_sessions: list[str] = field(default_factory=list)
    context_pages: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class SessionWorkspaceAdapter:
    """Adapts OpenClaw workspaces to Nous namespaces.

    Provides:
      - Namespace isolation per workspace
      - Cross-session context sharing (explicit grant)
      - Workspace state persistence
      - Context page management
    """

    ISOLATION_LEVELS = {
        "full": "No sharing — each session isolated",
        "shared-read": "Sessions can read but not write shared context",
        "shared-readwrite": "Sessions can read and write shared context",
    }

    def __init__(self):
        self._workspaces: dict[str, WorkspaceMapping] = {}

    def create_workspace(
        self,
        openclaw_workspace_id: str,
        isolation: str = "full",
    ) -> WorkspaceMapping:
        """Create a Nous namespace for an OpenClaw workspace."""
        mapping = WorkspaceMapping(
            openclaw_workspace_id=openclaw_workspace_id,
            nous_namespace=f"openclaw-ws-{openclaw_workspace_id}",
            isolation_level=isolation,
        )
        self._workspaces[openclaw_workspace_id] = mapping
        log.info(
            "Workspace %s → namespace %s (isolation=%s)",
            openclaw_workspace_id,
            mapping.nous_namespace,
            isolation,
        )
        return mapping

    def share_context(
        self,
        source_workspace_id: str,
        target_workspace_id: str,
        page_keys: list[str],
        permission: str = "shared-read",
    ) -> None:
        """Grant cross-workspace context page access."""
        source = self._workspaces.get(source_workspace_id)
        target = self._workspaces.get(target_workspace_id)

        if not source or not target:
            raise ValueError("Workspace not found")

        for key in page_keys:
            target.context_pages[key] = permission
            log.info(
                "Context page %s shared: %s → %s (%s)",
                key, source_workspace_id, target_workspace_id, permission,
            )

    def revoke_context(
        self,
        target_workspace_id: str,
        page_keys: list[str],
    ) -> None:
        """Revoke cross-workspace context access."""
        target = self._workspaces.get(target_workspace_id)
        if not target:
            return

        for key in page_keys:
            target.context_pages.pop(key, None)

    def get_namespace(self, openclaw_workspace_id: str) -> str | None:
        mapping = self._workspaces.get(openclaw_workspace_id)
        return mapping.nous_namespace if mapping else None

    def get_isolation(self, openclaw_workspace_id: str) -> str | None:
        mapping = self._workspaces.get(openclaw_workspace_id)
        return mapping.isolation_level if mapping else None

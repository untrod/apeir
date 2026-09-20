# -*- coding: utf-8 -*-
"""AgentProvider — reads context from the Agent Runtime registry."""

from __future__ import annotations

import logging

from nous_runtime.context.models import ContextItem
from nous_runtime.context.schema import ContextSource
from nous_runtime.context.types import ProviderHealth

_log = logging.getLogger("nous.context.providers.agent")


class AgentProvider:
    """Collects context items from the Agent Registry.

    Reads agent identities, manifests, and health status.
    """

    source_type: str = ContextSource.AGENT.value

    def __init__(self, workspace_path: str = ""):
        self._workspace = workspace_path



    def collect(self, request_hint: str = "", limit: int = 100) -> list[ContextItem]:
        """Collect agent context items."""
        items: list[ContextItem] = []
        try:
            from nous_runtime.agent.registry import AgentRegistry

            registry = AgentRegistry()
            agents = registry.list()

            for agent_info in agents[:limit]:
                agent_id = agent_info.get("agent_id", agent_info.get("id", ""))
                agent_name = agent_info.get("name", agent_id)
                agent_state = agent_info.get("state", agent_info.get("status", "unknown"))
                agent_role = agent_info.get("role", agent_info.get("kind", ""))

                content_parts = [f"Agent: {agent_name}"]
                if agent_state:
                    content_parts.append(f"[{agent_state}]")
                if agent_role:
                    content_parts.append(f"role={agent_role}")

                items.append(ContextItem(
                    content=" ".join(content_parts),
                    source_type=ContextSource.AGENT.value,
                    source_id=agent_id,
                    importance=0.6,
                    confidence=0.9,
                    permission="read",
                    tags=("agent", agent_state),
                ))

        except Exception as exc:
            _log.warning("AgentProvider.collect failed: %s", exc)

        return items[:limit]



    def explain(self, item_ids: list[str]) -> dict[str, str]:
        return {iid: f"Agent context item {iid} — sourced from agent registry." for iid in item_ids}

    def health(self) -> ProviderHealth:
        available = False
        item_count = 0
        error = ""
        try:
            from nous_runtime.agent.registry import AgentRegistry
            agents = AgentRegistry().list()
            available = True
            item_count = len(agents)
        except Exception as exc:
            error = str(exc)
        return ProviderHealth(
            source=ContextSource.AGENT.value,
            available=available,
            item_count=item_count,
            last_collected_at="",
            error=error,
        )

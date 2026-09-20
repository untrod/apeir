# -*- coding: utf-8 -*-
"""SDK Agent — base class for third-party agents."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("nous.sdk.agent")


@dataclass
class Agent:
    """Base Agent class for the Nous SDK.

    Usage:
        class RobotAgent(Agent):
            def __init__(self):
                super().__init__(
                    name="robot_agent",
                    capabilities=["camera", "motor", "navigation"],
                )

        agent = RobotAgent()
        agent.register()
    """

    name: str = ""
    version: str = "1.0.0"
    capabilities: tuple[str, ...] = ()
    description: str = ""
    owner: str = ""
    trust_level: str = "community"
    permissions: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    _agent_id: str = ""
    _registered: bool = False

    def __post_init__(self):
        import uuid
        if not self._agent_id:
            self._agent_id = f"agent.sdk.{self.name.lower().replace(' ', '_')}.{uuid.uuid4().hex[:8]}"

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def register(self, workspace: str = "") -> bool:
        """Register this agent with the Nous Runtime."""
        try:
            from nous_runtime.agent.registry import AgentRegistry
            from nous_runtime.agent.models import AgentIdentity, AgentManifest, AgentCapabilityBinding

            identity = AgentIdentity(
                agent_id=self._agent_id, name=self.name, version=self.version,
                owner=self.owner, trust_level=self.trust_level,
            )
            bindings = tuple(
                AgentCapabilityBinding(capability_id=c, permissions=self.permissions)
                for c in self.capabilities
            )
            manifest = AgentManifest(
                identity=identity, description=self.description,
                capabilities=bindings, metadata=self.metadata,
            )
            registry = AgentRegistry()
            registry.register(manifest)

            # Also register in network
            try:
                from nous_runtime.network.registry import NetworkRegistry
                from nous_runtime.network.models import AgentNode
                node = AgentNode(
                    id=self._agent_id, name=self.name, node_type=self.capabilities[0] if self.capabilities else "general",
                    status="online", capabilities=self.capabilities, trust_level=self.trust_level,
                )
                net = NetworkRegistry(workspace)
                net.register(node)
            except Exception:
                pass

            self._registered = True
            _log.info("Agent registered: %s", self._agent_id)
            return True
        except Exception as exc:
            _log.error("Failed to register agent: %s", exc)
            return False

    def execute(self, capability: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a capability. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement execute()")

    def status(self) -> dict[str, Any]:
        return {
            "agent_id": self._agent_id, "name": self.name,
            "registered": self._registered, "capabilities": list(self.capabilities),
        }

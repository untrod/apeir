# -*- coding: utf-8 -*-
"""Persistent Agent registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nous_runtime.agent.models import AgentManifest, AgentProfile, AgentState, utc_now


class AgentRegistryError(RuntimeError):
    """Raised when an Agent registry operation cannot be completed."""


class AgentRegistry:
    """JSON-backed registry for local Agent profiles."""

    def __init__(self, workspace_path: str | Path | None = None):
        base = Path(workspace_path or ".nous")
        self.workspace_path = base
        self.path = base / "agents.json"

    def register(self, manifest: AgentManifest) -> AgentProfile:
        errors = manifest.validate()
        if errors:
            raise AgentRegistryError("; ".join(errors))

        data = self._load()
        agent_id = manifest.identity.agent_id
        if agent_id in data:
            raise AgentRegistryError(f"agent already registered: {agent_id}")

        profile = AgentProfile(
            manifest=manifest,
            state=AgentState.REGISTERED,
            registered_at=utc_now(),
        )
        data[agent_id] = profile.to_dict()
        self._save(data)
        return profile

    def list(self) -> list[AgentProfile]:
        return [AgentProfile.from_dict(item) for item in self._load().values()]

    def get(self, agent_id: str) -> AgentProfile | None:
        item = self._load().get(agent_id)
        return AgentProfile.from_dict(item) if item else None

    def require(self, agent_id: str) -> AgentProfile:
        profile = self.get(agent_id)
        if profile is None:
            raise AgentRegistryError(f"agent not found: {agent_id}")
        return profile

    def save_profile(self, profile: AgentProfile) -> AgentProfile:
        errors = profile.manifest.validate()
        if errors:
            raise AgentRegistryError("; ".join(errors))
        data = self._load()
        data[profile.agent_id] = profile.to_dict()
        self._save(data)
        return profile

    def update_state(self, agent_id: str, state: AgentState, *, error: str = "") -> AgentProfile:
        profile = self.require(agent_id).with_state(state, error=error)
        return self.save_profile(profile)

    def remove(self, agent_id: str) -> bool:
        data = self._load()
        if agent_id not in data:
            return False
        del data[agent_id]
        self._save(data)
        return True

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AgentRegistryError(f"invalid agent registry: {self.path}") from exc
        agents = raw.get("agents", raw)
        if not isinstance(agents, dict):
            raise AgentRegistryError("agent registry must contain an object")
        return agents

    def _save(self, agents: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": "1.0.0", "agents": agents}
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

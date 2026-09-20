# -*- coding: utf-8 -*-
"""Agent Runtime domain models."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.schema_registry import AGENT_SCHEMA_VERSION as SCHEMA_VERSION
_AGENT_ID_RE = re.compile(r"^agent\.[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_agent_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", ".", name.lower()).strip(".") or uuid.uuid4().hex[:8]
    if not slug.startswith("agent."):
        slug = f"agent.{slug}"
    return slug


class AgentState(str, Enum):
    CREATED = "CREATED"
    REGISTERED = "REGISTERED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    TERMINATED = "TERMINATED"


@dataclass(frozen=True)
class AgentCapabilityBinding:
    capability_id: str
    provider_id: str = ""
    model_id: str = ""
    permissions: tuple[str, ...] = ()
    risk_level: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "permissions": list(self.permissions),
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentCapabilityBinding":
        return cls(
            capability_id=str(data.get("capability_id") or ""),
            provider_id=str(data.get("provider_id") or ""),
            model_id=str(data.get("model_id") or ""),
            permissions=tuple(str(v) for v in (data.get("permissions") or ())),
            risk_level=str(data.get("risk_level") or "low"),
        )


@dataclass(frozen=True)
class AgentBudget:
    max_cost_usd: float = 0.0
    max_tokens: int = 0
    max_runtime_ms: int = 30000
    max_invocations: int = 1
    max_tool_invocations: int = 0
    max_model_invocations: int = 0
    max_checkpoints: int = 0
    max_steps: int = 0

    def allows(self, *, cost_usd: float = 0.0, tokens: int = 0, runtime_ms: int = 0, invocations: int = 1) -> bool:
        if self.max_cost_usd and cost_usd > self.max_cost_usd:
            return False
        if self.max_tokens and tokens > self.max_tokens:
            return False
        if self.max_runtime_ms and runtime_ms > self.max_runtime_ms:
            return False
        if self.max_invocations and invocations > self.max_invocations:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "max_tokens": self.max_tokens,
            "max_runtime_ms": self.max_runtime_ms,
            "max_invocations": self.max_invocations,
            "max_tool_invocations": self.max_tool_invocations,
            "max_model_invocations": self.max_model_invocations,
            "max_checkpoints": self.max_checkpoints,
            "max_steps": self.max_steps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentBudget":
        data = data or {}
        return cls(
            max_cost_usd=float(data.get("max_cost_usd") or 0.0),
            max_tokens=int(data.get("max_tokens") or 0),
            max_runtime_ms=int(data.get("max_runtime_ms") or 30000),
            max_invocations=int(data.get("max_invocations") or 1),
            max_tool_invocations=int(data.get("max_tool_invocations") or 0),
            max_model_invocations=int(data.get("max_model_invocations") or 0),
            max_checkpoints=int(data.get("max_checkpoints") or 0),
            max_steps=int(data.get("max_steps") or 0),
        )


@dataclass(frozen=True)
class AgentHealth:
    status: str = "unknown"
    last_seen_at: str = ""
    failure_count: int = 0
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_seen_at": self.last_seen_at,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "AgentHealth":
        data = data or {}
        return cls(
            status=str(data.get("status") or "unknown"),
            last_seen_at=str(data.get("last_seen_at") or ""),
            failure_count=int(data.get("failure_count") or 0),
            last_error=str(data.get("last_error") or ""),
        )


@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    name: str
    version: str = "1.0.0"
    owner: str = "local"
    trust_level: str = "local"
    created_at: str = field(default_factory=utc_now)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not _AGENT_ID_RE.match(self.agent_id):
            errors.append(f"invalid agent_id: {self.agent_id}")
        if not self.name.strip():
            errors.append("name is required")
        if self.trust_level not in {"local", "trusted", "delegated", "untrusted"}:
            errors.append(f"invalid trust_level: {self.trust_level}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "version": self.version,
            "owner": self.owner,
            "trust_level": self.trust_level,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentIdentity":
        return cls(
            agent_id=str(data.get("agent_id") or ""),
            name=str(data.get("name") or ""),
            version=str(data.get("version") or "1.0.0"),
            owner=str(data.get("owner") or "local"),
            trust_level=str(data.get("trust_level") or "local"),
            created_at=str(data.get("created_at") or utc_now()),
        )


@dataclass(frozen=True)
class AgentManifest:
    identity: AgentIdentity
    description: str = ""
    capabilities: tuple[AgentCapabilityBinding, ...] = ()
    permissions: tuple[str, ...] = ()
    budget: AgentBudget = field(default_factory=AgentBudget)
    policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def validate(self) -> list[str]:
        errors = self.identity.validate()
        seen: set[str] = set()
        for binding in self.capabilities:
            if not binding.capability_id:
                errors.append("capability_id is required")
            if binding.capability_id in seen:
                errors.append(f"duplicate capability binding: {binding.capability_id}")
            seen.add(binding.capability_id)
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "description": self.description,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "permissions": list(self.permissions),
            "budget": self.budget.to_dict(),
            "policy": dict(self.policy),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentManifest":
        return cls(
            identity=AgentIdentity.from_dict(data.get("identity") or {}),
            description=str(data.get("description") or ""),
            capabilities=tuple(AgentCapabilityBinding.from_dict(item) for item in (data.get("capabilities") or ())),
            permissions=tuple(str(v) for v in (data.get("permissions") or ())),
            budget=AgentBudget.from_dict(data.get("budget")),
            policy=dict(data.get("policy") or {}),
            metadata=dict(data.get("metadata") or {}),
            schema_version=str(data.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass(frozen=True)
class AgentProfile:
    manifest: AgentManifest
    state: AgentState = AgentState.CREATED
    health: AgentHealth = field(default_factory=AgentHealth)
    registered_at: str = ""
    updated_at: str = field(default_factory=utc_now)

    @property
    def agent_id(self) -> str:
        return self.manifest.identity.agent_id

    def with_state(self, state: AgentState, *, error: str = "") -> "AgentProfile":
        health = self.health
        if state == AgentState.FAILED:
            health = AgentHealth(status="failed", last_seen_at=utc_now(), failure_count=health.failure_count + 1, last_error=error)
        elif state in {AgentState.READY, AgentState.RUNNING, AgentState.WAITING}:
            health = AgentHealth(status="ok", last_seen_at=utc_now(), failure_count=health.failure_count, last_error="")
        return AgentProfile(
            manifest=self.manifest,
            state=state,
            health=health,
            registered_at=self.registered_at,
            updated_at=utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "state": self.state.value,
            "health": self.health.to_dict(),
            "registered_at": self.registered_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentProfile":
        return cls(
            manifest=AgentManifest.from_dict(data.get("manifest") or {}),
            state=AgentState(str(data.get("state") or AgentState.CREATED.value)),
            health=AgentHealth.from_dict(data.get("health")),
            registered_at=str(data.get("registered_at") or ""),
            updated_at=str(data.get("updated_at") or utc_now()),
        )

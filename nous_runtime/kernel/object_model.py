# -*- coding: utf-8 -*-
"""
Unified Object Model -base class for all core runtime objects.

Every core object (Goal, Plan, Task, Job, Capability, Provider, Pack,
Node, Policy) shares a common identity, lifecycle, and status model.

Usage:
    from nous_runtime.kernel.object_model import NousObject, Phase, Condition, Health

    class Capability(NousObject):
        kind = "Capability"
        api_version = "v1"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nous_runtime.compat.ids import make_id


# Phase

class Phase(str, Enum):
    """Standard lifecycle phases applicable across all object kinds."""
    # Generic
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # Capability-specific
    REGISTERED = "registered"
    VALIDATED = "validated"
    ENABLED = "enabled"
    READY = "ready"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"
    UNREGISTERED = "unregistered"
    # Provider-specific
    DISCOVERED = "discovered"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ADVERTISED = "advertised"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    # Job-specific
    CLAIMED = "claimed"
    RUNNING = "running"
    DONE = "done"
    # Planner-specific
    PLANNING = "planning"
    BUILDING = "building"
    EXECUTING = "executing"
    SCHEDULED = "scheduled"
    # Pack-specific
    INSTALLED = "installed"
    REMOVED = "removed"


class Health(str, Enum):
    """Standard health status."""
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


# Condition

@dataclass
class Condition:
    """A condition describes the state of an object at a point in time."""
    type: str                           # Ready, Healthy, Progressing, Degraded
    status: str = "Unknown"             # True, False, Unknown
    reason: str = ""                    # Machine-readable reason
    message: str = ""                   # Human-readable message
    last_transition: str = ""           # ISO 8601 UTC

    def __post_init__(self):
        if not self.last_transition:
            self.last_transition = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Metadata

@dataclass
class ObjectMetadata:
    """Standard metadata for every runtime object."""
    id: str = ""                        # Unique ID
    kind: str = ""                      # Object kind
    api_version: str = "v1"             # API version
    name: str = ""                      # Human-readable name
    namespace: str = "default"          # Isolation namespace
    owner: str = ""                     # Owner reference
    labels: dict[str, str] = field(default_factory=dict)
    created_at: str = ""                # ISO 8601 UTC
    updated_at: str = ""                # ISO 8601 UTC
    generation: int = 0                 # Monotonic update counter

    def __post_init__(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


# NousObject

@dataclass
class NousObject:
    """
    Base class for all core runtime objects.

    Subclasses must define:
        kind: str           -Object kind (e.g., "Capability", "Provider", "Job")
        api_version: str    -API version (e.g., "v1")

    Usage:
        class Capability(NousObject):
            kind = "Capability"
            api_version = "v1"
    """

    kind: str = field(default="", init=False)
    api_version: str = field(default="v1", init=False)

    def __post_init__(self):
        if not self.metadata.id:
            prefix_map = {
                "Goal": "goal", "Plan": "plan", "Task": "task",
                "Job": "job", "Capability": "cap", "Provider": "prov",
                "Pack": "pack", "Node": "node", "Policy": "pol",
            }
            prefix = prefix_map.get(self.kind, "obj")
            self.metadata.id = make_id(prefix=prefix)
            self.metadata.kind = self.kind
            self.metadata.api_version = self.api_version

    # Metadata
    metadata: ObjectMetadata = field(default_factory=lambda: ObjectMetadata(
        kind="", api_version="v1",
    ))

    # Status
    phase: Phase = Phase.PENDING
    health: Health = Health.UNKNOWN
    conditions: list[Condition] = field(default_factory=list)
    message: str = ""
    observed_at: str = ""

    def set_phase(self, phase: Phase, message: str = "") -> None:
        """Transition to a new phase."""
        self.phase = phase
        self.message = message
        self.observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.metadata.updated_at = self.observed_at
        self.metadata.generation += 1

    def set_health(self, health: Health, message: str = "") -> None:
        """Update health status."""
        self.health = health
        if message:
            self.message = message
        self.observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def add_condition(self, condition: Condition) -> None:
        """Add or update a condition."""
        # Replace existing condition of same type
        self.conditions = [c for c in self.conditions if c.type != condition.type]
        self.conditions.append(condition)

    def is_ready(self) -> bool:
        return self.phase in (Phase.READY, Phase.ACTIVE, Phase.DONE)

    def is_terminal(self) -> bool:
        return self.phase in (Phase.COMPLETED, Phase.FAILED, Phase.CANCELLED,
                              Phase.UNREGISTERED, Phase.REMOVED)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "metadata": {
                "id": self.metadata.id,
                "kind": self.kind,
                "api_version": self.api_version,
                "name": self.metadata.name,
                "namespace": self.metadata.namespace,
                "owner": self.metadata.owner,
                "labels": self.metadata.labels,
                "created_at": self.metadata.created_at,
                "updated_at": self.metadata.updated_at,
                "generation": self.metadata.generation,
            },
            "status": {
                "phase": self.phase.value,
                "health": self.health.value,
                "conditions": [
                    {
                        "type": c.type,
                        "status": c.status,
                        "reason": c.reason,
                        "message": c.message,
                        "last_transition": c.last_transition,
                    }
                    for c in self.conditions
                ],
                "message": self.message,
                "observed_at": self.observed_at,
            },
        }

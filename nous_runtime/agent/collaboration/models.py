"""Serializable contracts for deterministic Agent collaboration."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping


class CollaborationRole(str, Enum):
    MANAGER = "manager"
    WORKER = "worker"
    REVIEWER = "reviewer"


class CollaborationStrategy(str, Enum):
    SEQUENTIAL = "sequential"
    FALLBACK = "fallback"
    PARALLEL = "parallel"


class CollaborationStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REVIEW_REJECTED = "review_rejected"


class ContributionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


@dataclass(frozen=True)
class RoleRequirement:
    role: CollaborationRole
    required_capabilities: frozenset[str] = frozenset()
    preferred_capabilities: frozenset[str] = frozenset()
    exclude_agent_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RoleAssignment:
    role: CollaborationRole
    agent_id: str
    score: float
    matched_capabilities: tuple[str, ...] = ()
    missing_preferred_capabilities: tuple[str, ...] = ()
    rationale: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["role"] = self.role.value
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RoleAssignment":
        return cls(
            role=CollaborationRole(str(data["role"])),
            agent_id=str(data["agent_id"]),
            score=float(data.get("score") or 0.0),
            matched_capabilities=tuple(data.get("matched_capabilities") or ()),
            missing_preferred_capabilities=tuple(
                data.get("missing_preferred_capabilities") or ()
            ),
            rationale=tuple(data.get("rationale") or ()),
        )


@dataclass(frozen=True)
class CollaborationStep:
    step_id: str
    objective: str
    capability_id: str
    candidate_agent_ids: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "objective": self.objective,
            "capability_id": self.capability_id,
            "candidate_agent_ids": list(self.candidate_agent_ids),
            "depends_on": list(self.depends_on),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CollaborationStep":
        return cls(
            step_id=str(data["step_id"]),
            objective=str(data["objective"]),
            capability_id=str(data["capability_id"]),
            candidate_agent_ids=tuple(data.get("candidate_agent_ids") or ()),
            depends_on=tuple(data.get("depends_on") or ()),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class ModelCollaborationPlan:
    task_id: str
    manager: RoleAssignment
    workers: tuple[RoleAssignment, ...]
    reviewer: RoleAssignment
    steps: tuple[CollaborationStep, ...]
    strategy: CollaborationStrategy = CollaborationStrategy.SEQUENTIAL
    max_parallelism: int = 1
    plan_id: str = field(
        default_factory=lambda: f"collab_{uuid.uuid4().hex}"
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "manager": self.manager.to_dict(),
            "workers": [item.to_dict() for item in self.workers],
            "reviewer": self.reviewer.to_dict(),
            "steps": [item.to_dict() for item in self.steps],
            "strategy": self.strategy.value,
            "max_parallelism": self.max_parallelism,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModelCollaborationPlan":
        return cls(
            task_id=str(data["task_id"]),
            manager=RoleAssignment.from_dict(data["manager"]),
            workers=tuple(
                RoleAssignment.from_dict(item)
                for item in data.get("workers") or ()
            ),
            reviewer=RoleAssignment.from_dict(data["reviewer"]),
            steps=tuple(
                CollaborationStep.from_dict(item)
                for item in data.get("steps") or ()
            ),
            strategy=CollaborationStrategy(
                str(data.get("strategy") or "sequential")
            ),
            max_parallelism=int(data.get("max_parallelism") or 1),
            plan_id=str(data.get("plan_id") or f"collab_{uuid.uuid4().hex}"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class AgentContribution:
    step_id: str
    agent_id: str
    status: ContributionStatus
    output: Any = None
    attempt: int = 1
    run_id: str = ""
    invocation_id: str = ""
    error: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MergeConflict:
    key: str
    agent_ids: tuple[str, ...]
    values: tuple[Any, ...]


@dataclass(frozen=True)
class MergeResult:
    output: Any
    conflicts: tuple[MergeConflict, ...] = ()
    sources: tuple[str, ...] = ()
    strategy: str = "deterministic"


@dataclass(frozen=True)
class CollaborationResult:
    plan_id: str
    task_id: str
    status: CollaborationStatus
    contributions: tuple[AgentContribution, ...] = ()
    merged: MergeResult | None = None
    review: Mapping[str, Any] = field(default_factory=dict)
    error: str = ""


__all__ = [
    "AgentContribution",
    "CollaborationRole",
    "CollaborationStatus",
    "CollaborationStep",
    "CollaborationStrategy",
    "CollaborationResult",
    "ContributionStatus",
    "MergeConflict",
    "MergeResult",
    "ModelCollaborationPlan",
    "RoleAssignment",
    "RoleRequirement",
]

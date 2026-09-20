"""Build executable collaboration plans from explicit work specifications."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from nous_runtime.agent.collaboration.assignment import RoleAssignmentEngine
from nous_runtime.agent.collaboration.models import (
    CollaborationRole,
    CollaborationStep,
    CollaborationStrategy,
    ModelCollaborationPlan,
    RoleRequirement,
)
from nous_runtime.agent.errors import AgentCollaborationError
from nous_runtime.agent.models import AgentProfile


@dataclass(frozen=True)
class CollaborationWork:
    step_id: str
    objective: str
    capability_id: str
    depends_on: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ModelCollaborationPlanner:
    def __init__(
        self,
        assignment_engine: RoleAssignmentEngine | None = None,
    ) -> None:
        self.assignment_engine = assignment_engine or RoleAssignmentEngine()

    def build(
        self,
        *,
        task_id: str,
        work: tuple[CollaborationWork, ...],
        profiles: tuple[AgentProfile, ...],
        strategy: CollaborationStrategy = CollaborationStrategy.SEQUENTIAL,
        max_parallelism: int = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> ModelCollaborationPlan:
        task_id = str(task_id or "").strip()
        if not task_id:
            raise AgentCollaborationError("collaboration task_id is required")
        self._validate_work(work)
        manager = self.assignment_engine.assign(
            RoleRequirement(
                CollaborationRole.MANAGER,
                required_capabilities=frozenset({"planning"}),
            ),
            profiles,
        )
        reviewer = self.assignment_engine.assign(
            RoleRequirement(
                CollaborationRole.REVIEWER,
                required_capabilities=frozenset({"verification"}),
                exclude_agent_ids=frozenset({manager.agent_id}),
            ),
            profiles,
        )
        worker_assignments = {}
        steps = []
        for item in work:
            ranked = self.assignment_engine.rank(
                RoleRequirement(
                    CollaborationRole.WORKER,
                    required_capabilities=frozenset({item.capability_id}),
                    exclude_agent_ids=frozenset(
                        {manager.agent_id, reviewer.agent_id}
                    ),
                ),
                profiles,
            )
            if not ranked:
                ranked = self.assignment_engine.rank(
                    RoleRequirement(
                        CollaborationRole.WORKER,
                        required_capabilities=frozenset({item.capability_id}),
                    ),
                    profiles,
                )
            if not ranked:
                raise AgentCollaborationError(
                    f"no eligible worker for capability: {item.capability_id}",
                    context={"step_id": item.step_id},
                )
            for assignment in ranked:
                worker_assignments.setdefault(
                    assignment.agent_id,
                    assignment,
                )
            steps.append(
                CollaborationStep(
                    step_id=item.step_id,
                    objective=item.objective,
                    capability_id=item.capability_id,
                    candidate_agent_ids=tuple(
                        assignment.agent_id for assignment in ranked
                    ),
                    depends_on=item.depends_on,
                    metadata=item.metadata,
                )
            )
        return ModelCollaborationPlan(
            task_id=task_id,
            manager=manager,
            workers=tuple(
                sorted(
                    worker_assignments.values(),
                    key=lambda item: (-item.score, item.agent_id),
                )
            ),
            reviewer=reviewer,
            steps=tuple(steps),
            strategy=strategy,
            max_parallelism=max(1, min(int(max_parallelism), 32)),
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _validate_work(work: tuple[CollaborationWork, ...]) -> None:
        if not work:
            raise AgentCollaborationError("collaboration work is required")
        ids = [item.step_id for item in work]
        if any(
            not item.step_id or not item.objective or not item.capability_id
            for item in work
        ):
            raise AgentCollaborationError(
                "step_id, objective and capability_id are required"
            )
        if len(ids) != len(set(ids)):
            raise AgentCollaborationError("collaboration step ids must be unique")
        known = set(ids)
        edges = {item.step_id: item.depends_on for item in work}
        for item in work:
            if item.step_id in item.depends_on:
                raise AgentCollaborationError("step cannot depend on itself")
            if set(item.depends_on) - known:
                raise AgentCollaborationError("unknown collaboration dependency")
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(step_id: str) -> None:
            if step_id in visiting:
                raise AgentCollaborationError(
                    "collaboration dependency cycle"
                )
            if step_id in visited:
                return
            visiting.add(step_id)
            for dependency in edges[step_id]:
                visit(dependency)
            visiting.remove(step_id)
            visited.add(step_id)

        for step_id in ids:
            visit(step_id)


__all__ = ["CollaborationWork", "ModelCollaborationPlanner"]

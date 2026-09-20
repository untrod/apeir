"""Capability-to-model composition built on the canonical ModelRouter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from nous_runtime.model_runtime.evaluation import ModelEvaluationStore
from nous_runtime.model_runtime.models import (
    ModelModality,
    ModelRequest,
    ModelRole,
    RouteDecision,
    RoutingMode,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.model_runtime.router import ModelRouter


@dataclass(frozen=True)
class ModelRoleRequirement:
    role: ModelRole
    capabilities: frozenset[str]
    modalities: frozenset[ModelModality] = field(
        default_factory=lambda: frozenset({ModelModality.TEXT})
    )
    quality_target: float = 0.5


@dataclass(frozen=True)
class ModelRoleAssignment:
    role: ModelRole
    model_id: str
    instance_id: str
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ModelCapabilityPlan:
    task_id: str
    assignments: tuple[ModelRoleAssignment, ...]
    routes: tuple[RouteDecision, ...]

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(item.model_id for item in self.assignments)


class ModelCapabilityGraph:
    """Compose planner/worker/reviewer models without bypassing routing."""

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        *,
        evaluations: ModelEvaluationStore | None = None,
    ) -> None:
        self.registry = registry
        self.evaluations = evaluations
        self.router = ModelRouter(registry)

    def plan(
        self,
        task_id: str,
        requirements: Iterable[ModelRoleRequirement],
    ) -> ModelCapabilityPlan:
        assignments: list[ModelRoleAssignment] = []
        routes: list[RouteDecision] = []
        for index, requirement in enumerate(requirements):
            preferred = self._evaluation_preference(
                requirement.capabilities
            )
            request = ModelRequest(
                task_id=f"{task_id}:{index}:{requirement.role.value}",
                required_capabilities=requirement.capabilities,
                required_modalities=requirement.modalities,
                role=requirement.role,
                quality_target=requirement.quality_target,
                preferred_models=preferred,
                routing_mode=(
                    RoutingMode.PREFERRED if preferred else RoutingMode.AUTO
                ),
                metadata={"capability_graph": True},
            )
            route = self.router.route(request)
            routes.append(route)
            assignments.append(
                ModelRoleAssignment(
                    role=requirement.role,
                    model_id=route.selected_model_id,
                    instance_id=route.selected_instance_id,
                    score=route.score,
                    reasons=route.reasons,
                )
            )
        return ModelCapabilityPlan(
            task_id=task_id,
            assignments=tuple(assignments),
            routes=tuple(routes),
        )

    def software_delivery_plan(
        self,
        task_id: str,
    ) -> ModelCapabilityPlan:
        return self.plan(
            task_id,
            (
                ModelRoleRequirement(
                    ModelRole.PLANNER,
                    frozenset({"reasoning"}),
                    quality_target=0.7,
                ),
                ModelRoleRequirement(
                    ModelRole.CODE_WORKER,
                    frozenset({"coding"}),
                    quality_target=0.7,
                ),
                ModelRoleRequirement(
                    ModelRole.REVIEWER,
                    frozenset({"reasoning", "coding"}),
                    quality_target=0.8,
                ),
            ),
        )

    def _evaluation_preference(
        self, capabilities: frozenset[str]
    ) -> tuple[str, ...]:
        if self.evaluations is None:
            return ()
        task_type = sorted(capabilities)[0] if capabilities else None
        return tuple(
            item.model_id
            for item in self.evaluations.leaderboard(task_type=task_type)
        )


__all__ = [
    "ModelCapabilityGraph",
    "ModelCapabilityPlan",
    "ModelRoleAssignment",
    "ModelRoleRequirement",
]

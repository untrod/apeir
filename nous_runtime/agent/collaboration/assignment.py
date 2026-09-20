"""Capability-based, deterministic collaboration role assignment."""

from __future__ import annotations

from nous_runtime.agent.errors import AgentCollaborationError
from nous_runtime.agent.models import AgentProfile, AgentState
from nous_runtime.agent.collaboration.models import (
    CollaborationRole,
    RoleAssignment,
    RoleRequirement,
)


_EXECUTABLE_STATES = {
    AgentState.REGISTERED,
    AgentState.READY,
    AgentState.RUNNING,
    AgentState.WAITING,
}


class RoleAssignmentEngine:
    """Assign roles without calling a model or mutating Agent profiles."""

    def rank(
        self,
        requirement: RoleRequirement,
        profiles: tuple[AgentProfile, ...],
    ) -> tuple[RoleAssignment, ...]:
        ranked: list[RoleAssignment] = []
        for profile in profiles:
            if (
                profile.agent_id in requirement.exclude_agent_ids
                or profile.state not in _EXECUTABLE_STATES
            ):
                continue
            capabilities = {
                item.capability_id for item in profile.manifest.capabilities
            }
            if not requirement.required_capabilities.issubset(capabilities):
                continue
            matched = requirement.preferred_capabilities & capabilities
            missing = requirement.preferred_capabilities - capabilities
            role_hints = {
                str(item).lower()
                for item in profile.manifest.metadata.get("roles", ())
            }
            role_bonus = 0.15 if requirement.role.value in role_hints else 0.0
            preferred_score = (
                len(matched) / len(requirement.preferred_capabilities)
                if requirement.preferred_capabilities
                else 1.0
            )
            reliability = max(
                0.0,
                min(
                    1.0,
                    float(profile.manifest.metadata.get("reliability", 0.5)),
                ),
            )
            score = min(
                1.0,
                0.60 + 0.20 * preferred_score + 0.20 * reliability + role_bonus,
            )
            rationale = [
                "required_capabilities_satisfied",
                f"preferred_match={preferred_score:.3f}",
                f"reliability={reliability:.3f}",
            ]
            if role_bonus:
                rationale.append("role_hint_matched")
            ranked.append(
                RoleAssignment(
                    role=requirement.role,
                    agent_id=profile.agent_id,
                    score=round(score, 6),
                    matched_capabilities=tuple(sorted(matched)),
                    missing_preferred_capabilities=tuple(sorted(missing)),
                    rationale=tuple(rationale),
                )
            )
        return tuple(sorted(ranked, key=lambda item: (-item.score, item.agent_id)))

    def assign(
        self,
        requirement: RoleRequirement,
        profiles: tuple[AgentProfile, ...],
    ) -> RoleAssignment:
        ranked = self.rank(requirement, profiles)
        if not ranked:
            raise AgentCollaborationError(
                f"no eligible agent for role: {requirement.role.value}",
                context={
                    "role": requirement.role.value,
                    "required_capabilities": sorted(
                        requirement.required_capabilities
                    ),
                },
            )
        return ranked[0]

    def assign_core_roles(
        self,
        profiles: tuple[AgentProfile, ...],
        *,
        worker_capabilities: frozenset[str],
    ) -> tuple[RoleAssignment, tuple[RoleAssignment, ...], RoleAssignment]:
        manager = self.assign(
            RoleRequirement(
                CollaborationRole.MANAGER,
                preferred_capabilities=frozenset({"planning"}),
            ),
            profiles,
        )
        reviewer = self.assign(
            RoleRequirement(
                CollaborationRole.REVIEWER,
                preferred_capabilities=frozenset({"verification"}),
                exclude_agent_ids=frozenset({manager.agent_id}),
            ),
            profiles,
        )
        worker_rank = self.rank(
            RoleRequirement(
                CollaborationRole.WORKER,
                required_capabilities=worker_capabilities,
                exclude_agent_ids=frozenset(
                    {manager.agent_id, reviewer.agent_id}
                ),
            ),
            profiles,
        )
        if not worker_rank:
            worker_rank = self.rank(
                RoleRequirement(
                    CollaborationRole.WORKER,
                    required_capabilities=worker_capabilities,
                ),
                profiles,
            )
        if not worker_rank:
            raise AgentCollaborationError(
                "no eligible worker agents",
                context={
                    "required_capabilities": sorted(worker_capabilities)
                },
            )
        return manager, worker_rank, reviewer


__all__ = ["RoleAssignmentEngine"]

from dataclasses import replace

import pytest

from nous_runtime.agent.collaboration import (
    CollaborationRole,
    RoleAssignmentEngine,
    RoleRequirement,
)
from nous_runtime.agent.errors import AgentCollaborationError
from nous_runtime.agent.models import AgentState


def test_assignment_is_capability_filtered_and_deterministic(
    collaboration_profiles,
) -> None:
    engine = RoleAssignmentEngine()
    requirement = RoleRequirement(
        CollaborationRole.WORKER,
        required_capabilities=frozenset({"coding"}),
    )

    ranked = engine.rank(requirement, collaboration_profiles)

    assert [item.agent_id for item in ranked] == [
        "agent.worker_a",
        "agent.worker_b",
    ]
    assert ranked[0].rationale[0] == "required_capabilities_satisfied"


def test_inactive_and_excluded_agents_are_not_eligible(
    collaboration_profiles,
) -> None:
    inactive = replace(
        collaboration_profiles[2],
        state=AgentState.TERMINATED,
    )
    requirement = RoleRequirement(
        CollaborationRole.WORKER,
        required_capabilities=frozenset({"coding"}),
        exclude_agent_ids=frozenset({"agent.worker_b"}),
    )

    ranked = RoleAssignmentEngine().rank(
        requirement,
        (*collaboration_profiles[:2], inactive, collaboration_profiles[3]),
    )

    assert ranked == ()


def test_missing_role_raises_structured_agent_error(
    collaboration_profiles,
) -> None:
    with pytest.raises(AgentCollaborationError, match="no eligible agent"):
        RoleAssignmentEngine().assign(
            RoleRequirement(
                CollaborationRole.WORKER,
                required_capabilities=frozenset({"vision"}),
            ),
            collaboration_profiles,
        )

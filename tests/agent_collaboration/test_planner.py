import pytest

from nous_runtime.agent.collaboration import (
    CollaborationStrategy,
    CollaborationWork,
    ModelCollaborationPlan,
    ModelCollaborationPlanner,
)
from nous_runtime.agent.errors import AgentCollaborationError


def test_plan_assigns_manager_workers_and_reviewer(
    collaboration_profiles,
) -> None:
    plan = ModelCollaborationPlanner().build(
        task_id="task-6",
        work=(
            CollaborationWork("code", "write code", "coding"),
            CollaborationWork(
                "math",
                "check math",
                "mathematics",
                depends_on=("code",),
            ),
        ),
        profiles=collaboration_profiles,
        strategy=CollaborationStrategy.FALLBACK,
    )

    assert plan.manager.agent_id == "agent.manager"
    assert plan.reviewer.agent_id == "agent.reviewer"
    assert plan.steps[0].candidate_agent_ids == (
        "agent.worker_a",
        "agent.worker_b",
    )
    assert plan.steps[1].candidate_agent_ids == ("agent.worker_b",)

    restored = ModelCollaborationPlan.from_dict(plan.to_dict())
    assert restored == plan


@pytest.mark.parametrize(
    "work,error",
    [
        ((), "work is required"),
        (
            (
                CollaborationWork("same", "one", "coding"),
                CollaborationWork("same", "two", "coding"),
            ),
            "unique",
        ),
        (
            (
                CollaborationWork(
                    "one",
                    "one",
                    "coding",
                    depends_on=("missing",),
                ),
            ),
            "unknown",
        ),
        (
            (
                CollaborationWork(
                    "one",
                    "one",
                    "coding",
                    depends_on=("two",),
                ),
                CollaborationWork(
                    "two",
                    "two",
                    "coding",
                    depends_on=("one",),
                ),
            ),
            "cycle",
        ),
    ],
)
def test_invalid_work_graph_is_rejected(
    collaboration_profiles,
    work,
    error,
) -> None:
    with pytest.raises(AgentCollaborationError, match=error):
        ModelCollaborationPlanner().build(
            task_id="task",
            work=work,
            profiles=collaboration_profiles,
        )

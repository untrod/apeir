import pytest

from nous_runtime.agent.collaboration import (
    AgentContribution,
    CollaborationResultMerger,
    ContributionStatus,
    MergePolicy,
)
from nous_runtime.agent.errors import AgentCollaborationError


def contribution(agent_id, output, *, step_id="step"):
    return AgentContribution(
        step_id=step_id,
        agent_id=agent_id,
        status=ContributionStatus.COMPLETED,
        output=output,
    )


def test_structured_merge_is_deterministic_and_reports_conflicts() -> None:
    result = CollaborationResultMerger().merge(
        (
            contribution("agent.a", {"shared": 1, "a": True}),
            contribution("agent.b", {"shared": 2, "b": True}),
        )
    )

    assert result.output == {"shared": 1, "a": True, "b": True}
    assert result.conflicts[0].key == "shared"
    assert result.conflicts[0].agent_ids == ("agent.a", "agent.b")


def test_consensus_uses_stable_first_winner() -> None:
    result = CollaborationResultMerger().merge(
        (
            contribution("agent.a", "A"),
            contribution("agent.b", "B"),
            contribution("agent.c", "A"),
        ),
        policy=MergePolicy.CONSENSUS,
    )

    assert result.output == "A"
    assert result.sources == ("agent.a", "agent.c")


def test_collect_preserves_contribution_order() -> None:
    result = CollaborationResultMerger().merge(
        (
            contribution("agent.a", 1),
            contribution("agent.b", 2),
        ),
        policy=MergePolicy.COLLECT,
    )
    assert result.output == (1, 2)


def test_merge_requires_successful_contribution() -> None:
    failed = AgentContribution(
        step_id="step",
        agent_id="agent.a",
        status=ContributionStatus.FAILED,
    )
    with pytest.raises(AgentCollaborationError):
        CollaborationResultMerger().merge((failed,))

from __future__ import annotations

import threading
import time

from nous_runtime.agent.collaboration import (
    CollaborationStatus,
    CollaborationStrategy,
    CollaborationWork,
    ContributionStatus,
    MergePolicy,
    ModelCollaborationPlanner,
    ModelCollaborationRuntime,
)


def build_plan(
    profiles,
    *,
    work=None,
    strategy=CollaborationStrategy.SEQUENTIAL,
    max_parallelism=1,
):
    return ModelCollaborationPlanner().build(
        task_id="task-collaboration",
        work=work or (CollaborationWork("code", "write code", "coding"),),
        profiles=profiles,
        strategy=strategy,
        max_parallelism=max_parallelism,
    )


def test_runtime_executes_manager_worker_merge_and_review(
    collaboration_profiles,
) -> None:
    plan = build_plan(collaboration_profiles)

    def handler(request):
        if request.capability_id == "planning":
            return {"accepted": True}
        if request.capability_id == "verification":
            return {"approved": True, "reason": "verified"}
        return {"code": "print('ok')"}

    runtime = ModelCollaborationRuntime()
    result = runtime.execute(
        plan,
        profiles={item.agent_id: item for item in collaboration_profiles},
        handler=handler,
    )

    assert result.status is CollaborationStatus.COMPLETED
    assert result.merged.output == {"code": "print('ok')"}
    assert result.review["approved"] is True
    assert len(runtime.agent_runtime.list()) == 3
    assert {
        item.step_id for item in result.contributions
    } == {"__manager__", "code", "__reviewer__"}


def test_fallback_uses_next_worker_after_failure(
    collaboration_profiles,
) -> None:
    plan = build_plan(
        collaboration_profiles,
        strategy=CollaborationStrategy.FALLBACK,
    )

    def handler(request):
        if request.capability_id == "planning":
            return True
        if request.capability_id == "verification":
            return {"approved": True}
        if request.agent_id == "agent.worker_a":
            raise RuntimeError("primary unavailable")
        return {"code": "fallback"}

    result = ModelCollaborationRuntime().execute(
        plan,
        profiles={item.agent_id: item for item in collaboration_profiles},
        handler=handler,
    )

    worker_attempts = [
        item for item in result.contributions if item.step_id == "code"
    ]
    assert [item.status for item in worker_attempts] == [
        ContributionStatus.FAILED,
        ContributionStatus.COMPLETED,
    ]
    assert [item.attempt for item in worker_attempts] == [1, 2]
    assert result.merged.output == {"code": "fallback"}


def test_parallel_strategy_runs_independent_steps_concurrently(
    collaboration_profiles,
) -> None:
    plan = build_plan(
        collaboration_profiles,
        work=(
            CollaborationWork("code", "write code", "coding"),
            CollaborationWork("math", "solve math", "mathematics"),
        ),
        strategy=CollaborationStrategy.PARALLEL,
        max_parallelism=2,
    )
    lock = threading.Lock()
    active = 0
    maximum = 0

    def handler(request):
        nonlocal active, maximum
        if request.capability_id == "planning":
            return True
        if request.capability_id == "verification":
            return {"approved": True}
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return {request.capability_id: "done"}

    result = ModelCollaborationRuntime().execute(
        plan,
        profiles={item.agent_id: item for item in collaboration_profiles},
        handler=handler,
    )

    assert result.status is CollaborationStatus.COMPLETED
    assert maximum == 2
    assert result.merged.output == {
        "coding": "done",
        "mathematics": "done",
    }


def test_review_rejection_is_explicit(collaboration_profiles) -> None:
    plan = build_plan(collaboration_profiles)

    def handler(request):
        if request.capability_id == "verification":
            return {"approved": False, "reason": "quality threshold"}
        return {"value": "candidate"}

    result = ModelCollaborationRuntime().execute(
        plan,
        profiles={item.agent_id: item for item in collaboration_profiles},
        handler=handler,
        merge_policy=MergePolicy.FIRST_SUCCESS,
    )

    assert result.status is CollaborationStatus.REVIEW_REJECTED
    assert result.error == "quality threshold"


def test_missing_profile_is_rejected(collaboration_profiles) -> None:
    plan = build_plan(collaboration_profiles)
    profiles = {
        item.agent_id: item
        for item in collaboration_profiles
        if item.agent_id != "agent.reviewer"
    }

    from pytest import raises

    from nous_runtime.agent.errors import AgentCollaborationError

    with raises(AgentCollaborationError, match="profiles are missing"):
        ModelCollaborationRuntime().execute(
            plan,
            profiles=profiles,
            handler=lambda request: True,
        )

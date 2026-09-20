"""In-memory execution engine for model collaboration plans."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Mapping

from nous_runtime.agent.collaboration.merger import (
    CollaborationResultMerger,
    MergePolicy,
)
from nous_runtime.agent.collaboration.models import (
    AgentContribution,
    CollaborationResult,
    CollaborationStatus,
    CollaborationStep,
    CollaborationStrategy,
    ContributionStatus,
    ModelCollaborationPlan,
)
from nous_runtime.agent.errors import AgentCollaborationError
from nous_runtime.agent.execution_state import InvocationStatus
from nous_runtime.agent.invocation import InvocationRequest
from nous_runtime.agent.models import AgentProfile
from nous_runtime.agent.runtime import AgentExecutionRuntime


CollaborationHandler = Callable[[InvocationRequest], Any]


class ModelCollaborationRuntime:
    """Execute a plan through AgentExecutionRuntime invocation boundaries."""

    def __init__(
        self,
        *,
        agent_runtime: AgentExecutionRuntime | None = None,
        merger: CollaborationResultMerger | None = None,
    ) -> None:
        self.agent_runtime = agent_runtime or AgentExecutionRuntime()
        self.merger = merger or CollaborationResultMerger()

    def execute(
        self,
        plan: ModelCollaborationPlan,
        *,
        profiles: Mapping[str, AgentProfile],
        handler: CollaborationHandler,
        review_handler: CollaborationHandler | None = None,
        merge_policy: MergePolicy = MergePolicy.STRUCTURED,
    ) -> CollaborationResult:
        profile_map = dict(profiles)
        self._validate_profiles(plan, profile_map)
        manager = self._invoke_agent(
            plan=plan,
            profile=profile_map[plan.manager.agent_id],
            step_id="__manager__",
            capability_id="planning",
            objective="coordinate collaboration plan",
            parameters={"plan": plan.to_dict()},
            handler=handler,
            attempt=1,
        )
        if manager.status is not ContributionStatus.COMPLETED:
            return CollaborationResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                status=CollaborationStatus.FAILED,
                contributions=(manager,),
                error=manager.error or "manager invocation failed",
            )

        worker_contributions = self._execute_steps(
            plan,
            profile_map,
            handler,
        )
        successful_steps = {
            item.step_id
            for item in worker_contributions
            if item.status is ContributionStatus.COMPLETED
        }
        expected_steps = {item.step_id for item in plan.steps}
        all_contributions = (manager, *worker_contributions)
        if successful_steps != expected_steps:
            return CollaborationResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                status=CollaborationStatus.FAILED,
                contributions=all_contributions,
                error="one or more collaboration steps failed",
            )

        successful = tuple(
            item
            for item in worker_contributions
            if item.status is ContributionStatus.COMPLETED
        )
        merged = self.merger.merge(successful, policy=merge_policy)
        reviewer = self._invoke_agent(
            plan=plan,
            profile=profile_map[plan.reviewer.agent_id],
            step_id="__reviewer__",
            capability_id="verification",
            objective="review merged collaboration result",
            parameters={
                "merged_output": merged.output,
                "conflicts": [
                    {
                        "key": item.key,
                        "agent_ids": list(item.agent_ids),
                    }
                    for item in merged.conflicts
                ],
            },
            handler=review_handler or handler,
            attempt=1,
        )
        all_contributions = (*all_contributions, reviewer)
        if reviewer.status is not ContributionStatus.COMPLETED:
            return CollaborationResult(
                plan_id=plan.plan_id,
                task_id=plan.task_id,
                status=CollaborationStatus.FAILED,
                contributions=all_contributions,
                merged=merged,
                error=reviewer.error or "reviewer invocation failed",
            )
        review = self._normalize_review(reviewer.output, merged.conflicts)
        status = (
            CollaborationStatus.COMPLETED
            if review["approved"]
            else CollaborationStatus.REVIEW_REJECTED
        )
        return CollaborationResult(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            status=status,
            contributions=all_contributions,
            merged=merged,
            review=review,
            error="" if review["approved"] else str(review["reason"]),
        )

    def _execute_steps(
        self,
        plan: ModelCollaborationPlan,
        profiles: Mapping[str, AgentProfile],
        handler: CollaborationHandler,
    ) -> tuple[AgentContribution, ...]:
        pending = {item.step_id: item for item in plan.steps}
        successful: dict[str, AgentContribution] = {}
        contributions: list[AgentContribution] = []
        while pending:
            ready = [
                item
                for item in plan.steps
                if item.step_id in pending
                and set(item.depends_on).issubset(successful)
            ]
            if not ready:
                return tuple(contributions)
            dependency_outputs = {
                key: item.output for key, item in successful.items()
            }
            if (
                plan.strategy is CollaborationStrategy.PARALLEL
                and len(ready) > 1
            ):
                with ThreadPoolExecutor(
                    max_workers=min(plan.max_parallelism, len(ready))
                ) as pool:
                    futures = [
                        pool.submit(
                            self._execute_step,
                            plan,
                            item,
                            profiles,
                            handler,
                            dependency_outputs,
                        )
                        for item in ready
                    ]
                    round_results = [future.result() for future in futures]
            else:
                round_results = [
                    self._execute_step(
                        plan,
                        item,
                        profiles,
                        handler,
                        dependency_outputs,
                    )
                    for item in ready
                ]
            for step, attempts in zip(ready, round_results, strict=True):
                contributions.extend(attempts)
                completed = next(
                    (
                        item
                        for item in reversed(attempts)
                        if item.status is ContributionStatus.COMPLETED
                    ),
                    None,
                )
                pending.pop(step.step_id)
                if completed is not None:
                    successful[step.step_id] = completed
        return tuple(contributions)

    def _execute_step(
        self,
        plan: ModelCollaborationPlan,
        step: CollaborationStep,
        profiles: Mapping[str, AgentProfile],
        handler: CollaborationHandler,
        dependency_outputs: Mapping[str, Any],
    ) -> tuple[AgentContribution, ...]:
        attempts: list[AgentContribution] = []
        candidate_ids = (
            step.candidate_agent_ids
            if plan.strategy is CollaborationStrategy.FALLBACK
            else step.candidate_agent_ids[:1]
        )
        for attempt, agent_id in enumerate(candidate_ids, start=1):
            contribution = self._invoke_agent(
                plan=plan,
                profile=profiles[agent_id],
                step_id=step.step_id,
                capability_id=step.capability_id,
                objective=step.objective,
                parameters={
                    "objective": step.objective,
                    "dependencies": {
                        key: dependency_outputs[key]
                        for key in step.depends_on
                        if key in dependency_outputs
                    },
                    "metadata": dict(step.metadata),
                },
                handler=handler,
                attempt=attempt,
            )
            attempts.append(contribution)
            if contribution.status is ContributionStatus.COMPLETED:
                break
        return tuple(attempts)

    def _invoke_agent(
        self,
        *,
        plan: ModelCollaborationPlan,
        profile: AgentProfile,
        step_id: str,
        capability_id: str,
        objective: str,
        parameters: Mapping[str, Any],
        handler: CollaborationHandler,
        attempt: int,
    ) -> AgentContribution:
        binding = next(
            (
                item
                for item in profile.manifest.capabilities
                if item.capability_id == capability_id and item.model_id
            ),
            None,
        )
        if binding is None:
            return AgentContribution(
                step_id=step_id,
                agent_id=profile.agent_id,
                status=ContributionStatus.DENIED,
                attempt=attempt,
                error=f"no model binding for capability: {capability_id}",
            )
        execution = self.agent_runtime.create(
            task_id=plan.task_id,
            profile=profile,
            metadata={
                "plan_id": plan.plan_id,
                "step_id": step_id,
                "role_objective": objective,
            },
        )
        self.agent_runtime.start(execution.run_id)
        output: dict[str, Any] = {}

        def capture(request: InvocationRequest) -> Any:
            result = handler(request)
            output["value"] = result
            return result

        invocation = self.agent_runtime.invoke_model(
            execution.run_id,
            model_id=binding.model_id,
            capability_id=capability_id,
            handler=capture,
            parameters=parameters,
        )
        status = {
            InvocationStatus.COMPLETED: ContributionStatus.COMPLETED,
            InvocationStatus.FAILED: ContributionStatus.FAILED,
            InvocationStatus.DENIED: ContributionStatus.DENIED,
        }[invocation.status]
        if status is ContributionStatus.COMPLETED:
            self.agent_runtime.complete(execution.run_id)
        return AgentContribution(
            step_id=step_id,
            agent_id=profile.agent_id,
            status=status,
            output=output.get("value"),
            attempt=attempt,
            run_id=execution.run_id,
            invocation_id=invocation.invocation_id,
            error=invocation.message,
            metadata={
                "model_id": binding.model_id,
                "capability_id": capability_id,
            },
        )

    @staticmethod
    def _validate_profiles(
        plan: ModelCollaborationPlan,
        profiles: Mapping[str, AgentProfile],
    ) -> None:
        required = {
            plan.manager.agent_id,
            plan.reviewer.agent_id,
            *(
                agent_id
                for step in plan.steps
                for agent_id in step.candidate_agent_ids
            ),
        }
        missing = sorted(required - set(profiles))
        if missing:
            raise AgentCollaborationError(
                "collaboration profiles are missing",
                context={"missing_agent_ids": missing},
            )

    @staticmethod
    def _normalize_review(output: Any, conflicts) -> dict[str, Any]:
        if isinstance(output, Mapping):
            approved = bool(output.get("approved", False))
            reason = str(output.get("reason") or "")
            return {
                "approved": approved,
                "reason": reason,
                "metadata": dict(output.get("metadata") or {}),
            }
        if isinstance(output, bool):
            return {"approved": output, "reason": "", "metadata": {}}
        approved = not conflicts
        return {
            "approved": approved,
            "reason": "" if approved else "merge conflicts require review",
            "metadata": {"review_output_type": type(output).__name__},
        }


__all__ = ["CollaborationHandler", "ModelCollaborationRuntime"]

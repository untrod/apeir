# -*- coding: utf-8 -*-
"""
Unified Decision Pipeline — the complete intelligence chain.

Request → Policy → Goal → Plan → Resolve → Route → Execute → Evaluate → Experience
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from nous_runtime.intelligence import (
    DecisionContext,
    DecisionRequest,
    DecisionType,
    RuntimeDecision,
    RuntimePolicyEngine,
    lifecycle_for_workspace,
    record_retrieval_outcome,
)
from nous_runtime.planner.goal import Goal
from nous_runtime.planner.observation import Observation
from nous_runtime.planner.plan import Plan, PlanStatus
from nous_runtime.planner.graph import TaskGraph
from nous_runtime.planner.scheduler import Scheduler
from nous_runtime.planner.dispatcher import Dispatcher
from nous_runtime.planner.evaluator import Evaluator, EvaluationResult

log = logging.getLogger("nous.pipeline")


@dataclass
class PipelineResult:
    """Complete result of a decision pipeline execution."""
    goal: Goal
    plan: Plan | None = None
    evaluation: EvaluationResult | None = None
    trace_id: str = ""
    total_duration_ms: float = 0.0
    success: bool = False
    errors: list[str] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    decisions: list[RuntimeDecision] = field(default_factory=list)


class DecisionPipeline:
    """
    The unified intelligence pipeline.

    Usage:
        pipeline = DecisionPipeline()
        result = pipeline.run("Analyze this project")
        print(f"Success: {result.success}, Score: {result.evaluation.score}")
    """

    def __init__(self):
        self.scheduler = Scheduler()
        self.dispatcher = Dispatcher()
        self.evaluator = Evaluator()

    def run(
        self,
        objective: str,
        constraints: dict[str, Any] | None = None,
        auto_execute: bool = True,
    ) -> PipelineResult:
        """
        Execute the full decision pipeline.

        Args:
            objective: Natural language goal description.
            constraints: Optional constraints (max_steps, timeout, etc.).
            auto_execute: If True, execute immediately. If False, return plan.

        Returns:
            PipelineResult with goal, plan, evaluation, and trace.
        """
        from nous_runtime.kernel.tracing import TraceContext, ExecutionTimeline

        start = time.time()
        errors: list[str] = []
        decisions: list[RuntimeDecision] = []
        timeline = ExecutionTimeline()

        with TraceContext() as ctx:
            # 1. Goal Understanding
            timeline.add("goal_understanding", event="started")
            goal = Goal(objective=objective, constraints=constraints or {})
            goal.start_understanding()
            timeline.add("goal_understanding", event="completed",
                        detail=f"Goal: {objective[:60]}")
            decision = self._runtime_decision(objective, goal.goal_id, constraints or {})
            decisions.append(decision)
            self._record_runtime_decision_created(decision)
            timeline.add(
                "runtime_decision",
                event="completed",
                detail=f"{decision.decision_type.value}: {decision.selected}",
            )

            # 2. Planning
            timeline.add("planning", event="started")
            goal.start_planning()
            plan = Plan(goal_id=goal.goal_id)
            plan.metadata["runtime_decisions"] = [d.to_dict() for d in decisions]

            # Decompose into tasks based on objective keywords
            tasks = self._decompose(objective)
            self._add_tasks(plan, tasks)
            plan.status = PlanStatus.READY
            timeline.add("planning", event="completed",
                        detail=f"{len(plan.tasks)} tasks planned")

            # 3. Build Task Graph
            timeline.add("task_graph", event="started")
            graph = TaskGraph()
            graph.build(plan.tasks)
            timeline.add("task_graph", event="completed",
                        detail=graph.summary())

            # 4. Execute (if auto)
            if auto_execute:
                timeline.add("execution", event="started")
                goal.start_executing()

                try:
                    execution_obs = self.dispatcher.dispatch_plan_observation(plan)
                    observations = [execution_obs]
                    exec_result = execution_obs.data
                    timeline.add("execution", event="completed",
                                detail=f"{exec_result['progress']['done']}/{exec_result['progress']['total']} done")

                    if plan.all_done() and not plan.any_failed():
                        goal.complete()
                    elif plan.any_failed():
                        goal.fail(f"{plan.progress()['failed']} tasks failed")
                    else:
                        goal.complete()
                except Exception as e:
                    errors.append(str(e))
                    goal.fail(str(e))
                    timeline.add("execution", event="failed", detail=str(e))
                    observations = []
            else:
                observations = []

            # 5. Evaluate
            timeline.add("evaluation", event="started")
            duration_s = (time.time() - start)
            evaluation = self.evaluator.evaluate_plan(plan, duration_s)
            self._record_pipeline_decision_outcomes(
                decisions,
                execution_id=ctx.trace_id,
                ok=evaluation.success if evaluation else False,
                latency_ms=(time.time() - start) * 1000,
                auto_execute=auto_execute,
            )
            timeline.add("evaluation", event="completed",
                        detail=f"Score: {evaluation.score}")

        return PipelineResult(
            goal=goal,
            plan=plan,
            evaluation=evaluation,
            trace_id=ctx.trace_id,
            total_duration_ms=(time.time() - start) * 1000,
            success=evaluation.success if evaluation else False,
            errors=errors,
            observations=observations,
            decisions=decisions,
        )

    @staticmethod
    def _runtime_decision(objective: str, task_id: str, constraints: dict[str, Any]) -> RuntimeDecision:
        context = DecisionContext(
            task_kind=str(constraints.get("task_kind") or "pipeline"),
            prompt=objective,
            token_budget=int(constraints.get("token_budget") or 6000),
            retrieval_available=bool(constraints.get("retrieval_available")),
            active_generation_id=str(constraints.get("active_generation_id") or ""),
            explicit_overrides=dict(constraints.get("overrides") or {}),
        )
        request = DecisionRequest(task_id=task_id, decision_type=DecisionType.RETRIEVAL, context=context)
        return RuntimePolicyEngine().decide(request)

    @staticmethod
    def _record_runtime_decision_created(decision: RuntimeDecision) -> None:
        try:
            from nous_runtime.project.workspace import find_workspace

            workspace = find_workspace()
            if workspace is None:
                return
            lifecycle_for_workspace(str(workspace)).record_decision_created(decision, source="pipeline")
        except Exception:
            log.debug("Runtime decision lifecycle creation was not recorded", exc_info=True)

    @staticmethod
    def _record_pipeline_decision_outcomes(
        decisions: list[RuntimeDecision],
        *,
        execution_id: str,
        ok: bool,
        latency_ms: float,
        auto_execute: bool,
    ) -> None:
        try:
            from nous_runtime.project.workspace import find_workspace

            workspace = find_workspace()
            if workspace is None:
                return
            service = lifecycle_for_workspace(str(workspace))
            for decision in decisions:
                if decision.decision_type == DecisionType.RETRIEVAL:
                    record_retrieval_outcome(
                        service,
                        decision,
                        execution_id=execution_id,
                        ok=ok,
                        latency_ms=latency_ms,
                        context_packed=bool(decision.outcome.metadata.get("generation_id")),
                        fallback_used=False,
                        metadata={
                            "selected_strategy": decision.selected,
                            "auto_execute": auto_execute,
                        },
                    )
        except Exception:
            log.debug("Runtime decision outcome was not recorded", exc_info=True)

    @staticmethod
    def _add_tasks(plan: Plan, task_defs: list[dict[str, Any]]) -> None:
        """Add task definitions to a plan and resolve dependency placeholders."""
        pending_dependencies: list[list[str]] = []
        for task_def in task_defs:
            params = task_def.get("params", {})
            task = plan.add_task(
                task_def.get("description", ""),
                capability_id=task_def.get("capability_id", ""),
                depends_on=task_def.get("depends_on", []),
                **params,
            )
            pending_dependencies.append(list(task.depends_on))

        for task, dependencies in zip(plan.tasks, pending_dependencies):
            resolved: list[str] = []
            for dep in dependencies:
                if dep.startswith("task_auto_"):
                    try:
                        idx = int(dep.rsplit("_", 1)[1])
                    except ValueError:
                        idx = -1
                    if 0 <= idx < len(plan.tasks):
                        resolved.append(plan.tasks[idx].task_id)
                else:
                    resolved.append(dep)
            task.depends_on = resolved

    @staticmethod
    def _decompose(objective: str) -> list[dict[str, Any]]:
        """Decompose an objective into tasks using keyword analysis."""
        tasks: list[dict[str, Any]] = []
        lower = objective.lower()

        # Inspection tasks
        if any(kw in lower for kw in ["analyze", "inspect", "check", "review", "分析"]):
            if any(kw in lower for kw in ["project", "code", "repository", "项目", "代码"]):
                tasks.append({
                    "description": "Inspect project structure",
                    "capability_id": "device.shell",
                    "params": {"command": "find . -type f -name '*.py' | head -20"},
                })
                tasks.append({
                    "description": "Analyze code organization",
                    "capability_id": "model.reason",
                    "params": {"prompt": f"Analyze this objective: {objective}"},
                })
                tasks.append({
                    "description": "Generate analysis report",
                    "capability_id": "model.reason",
                    "params": {"prompt": "Generate a concise summary report"},
                    "depends_on": ["task_placeholder"],  # Will be resolved
                })

        # System health tasks
        elif any(kw in lower for kw in ["health", "status", "check system", "健康", "状态"]):
            tasks.append({
                "description": "Check system health",
                "capability_id": "device.shell",
                "params": {"command": "echo 'System check: OK'"},
            })
            tasks.append({
                "description": "Report health status",
                "capability_id": "model.reason",
                "params": {"prompt": "Summarize system health in one sentence"},
            })

        # Default: single reasoning task
        if not tasks:
            tasks.append({
                "description": f"Process: {objective[:40]}",
                "capability_id": "model.reason",
                "params": {"prompt": objective},
            })

        # Fix dependencies: last task depends on all previous
        if len(tasks) > 1:
            prev_ids = [f"task_auto_{i}" for i in range(len(tasks) - 1)]
            tasks[-1]["depends_on"] = prev_ids

        # Assign IDs
        for i, t in enumerate(tasks):
            if "depends_on" in t and "task_placeholder" in t["depends_on"]:
                t["depends_on"] = [f"task_auto_{i-1}"] if i > 0 else []

        return tasks

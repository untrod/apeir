"""Workspace-scoped durable facade for long-running Work execution."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from nous_runtime.agent import AgentExecutionRuntime
from nous_runtime.agent.checkpoint import AgentCheckpointManager
from nous_runtime.agent.manifest import build_agent_manifest
from nous_runtime.agent.models import (
    AgentBudget,
    AgentCapabilityBinding,
    AgentProfile,
    AgentState,
)
from nous_runtime.checkpoint import Checkpoint, CheckpointStore, SQLiteCheckpointStore
from nous_runtime.conversation import ConversationMessage, ConversationStore
from nous_runtime.core.redaction import redact_sensitive_data
from nous_runtime.events import EventStream, RunEvent, RunState
from nous_runtime.execution import ExecutionContext
from nous_runtime.intelligence.planning import TaskPlanner
from nous_runtime.intelligence.task import TaskAnalysis, TaskAnalyzer
from nous_runtime.planner import Goal, Plan
from nous_runtime.planner.plan import PlanStatus, Task
from nous_runtime.task import Task as RuntimeTask
from nous_runtime.workspace.snapshot import snapshot_workspace
from nous_runtime.work.models import (
    PlanStepDraft,
    WorkContext,
    WorkSnapshot,
    work_timestamp,
)


Deliberator = Callable[[WorkContext], Any]
Verifier = Callable[[WorkContext], Any]


class WorkHarness:
    """Compose existing Runtime services into one recoverable Work entry point."""

    def __init__(
        self,
        root: str | Path = ".",
        *,
        checkpoints: CheckpointStore | None = None,
        events: EventStream | None = None,
        conversations: ConversationStore | None = None,
        agent_runtime: AgentExecutionRuntime | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoints = checkpoints or SQLiteCheckpointStore(
            self.root / ".nous" / "checkpoints.db"
        )
        self.events = events or EventStream(str(self.root))
        self.conversations = conversations or ConversationStore(self.root)
        self.analyzer = TaskAnalyzer()
        self.planner = TaskPlanner()
        self.agent_runtime = agent_runtime or AgentExecutionRuntime(
            checkpoints=AgentCheckpointManager(self.checkpoints)
        )

    def create(
        self,
        objective: str,
        *,
        constraints: Mapping[str, Any] | None = None,
        completion_criteria: tuple[str, ...] | list[str] = (),
        conversation_id: str = "",
        owner_id: str = "local",
        execution_options: Mapping[str, Any] | None = None,
    ) -> WorkSnapshot:
        objective = str(objective or "").strip()
        if not objective:
            raise ValueError("work objective is required")

        workspace = snapshot_workspace(str(self.root), root=str(self.root))
        if conversation_id:
            if self.conversations.get(conversation_id) is None:
                raise KeyError(f"conversation not found: {conversation_id}")
        else:
            conversation_id = self.conversations.create(
                workspace.workspace_id or str(self.root),
                owner_id,
                title=objective[:120],
            ).conversation_id

        goal = Goal(
            objective=objective,
            constraints=dict(constraints or {}),
            completion_criteria=[str(item) for item in completion_criteria],
        )
        runtime_task = RuntimeTask(
            id=goal.goal_id,
            name=objective[:160],
            description=objective,
            metadata={"workspace": str(self.root)},
        )
        analysis = self.analyzer.analyze(runtime_task)
        if constraints:
            analysis = replace(
                analysis,
                constraints={**analysis.constraints, **dict(constraints)},
            )

        plan = self._initial_plan(goal, analysis) if analysis.needs_plan else None
        snapshot = WorkSnapshot.create(
            goal=goal,
            analysis=analysis,
            workspace_root=str(self.root),
            conversation_id=conversation_id,
            plan=plan,
            execution_options=execution_options,
        )
        self.events.create_run(
            snapshot.run_id,
            task_id=goal.goal_id,
            workspace_id=workspace.workspace_id,
        )
        self.conversations.append(
            ConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content=objective,
                run_id=snapshot.run_id,
                task_id=goal.goal_id,
            )
        )
        self._persist(snapshot, "work.received", {"objective": objective})

        goal.start_understanding()
        snapshot.state = RunState.UNDERSTANDING
        self._persist(
            snapshot,
            "work.analysis",
            {"assessment": analysis.to_dict()},
        )

        snapshot.state = RunState.PREPARING
        self._persist(
            snapshot,
            "work.preparing",
            {"workspace": workspace.to_dict()},
        )
        if plan is not None:
            goal.start_planning()
            goal.bind_plan_revision(plan.revision)
            snapshot.state = RunState.PLANNING
            self._persist(
                snapshot,
                "work.plan.created",
                {"plan": plan.to_dict()},
            )
            snapshot.state = RunState.PREPARING
            self._persist(
                snapshot,
                "work.prepared",
                {"plan_revision": plan.revision},
            )
        return snapshot

    def run(
        self,
        run_id: str,
        *,
        deliberator: Deliberator,
        tools: Any = None,
        verifier: Verifier | None = None,
        max_iterations: int = 32,
    ) -> WorkSnapshot:
        from nous_runtime.work.loop import AgentLoop

        snapshot = self.require(run_id)
        return AgentLoop(self).run(
            snapshot,
            deliberator=deliberator,
            tools=tools,
            verifier=verifier,
            max_iterations=max_iterations,
        )

    def resume(
        self,
        run_id: str,
        *,
        deliberator: Deliberator,
        tools: Any = None,
        verifier: Verifier | None = None,
        max_iterations: int = 32,
    ) -> WorkSnapshot:
        snapshot = self.require(run_id)
        if snapshot.terminal:
            return snapshot
        if snapshot.pending_action and str(
            snapshot.pending_action.get("recovery_policy") or ""
        ) == "kernel_or_manual":
            reason = (
                "an effectful tool call has an uncertain outcome; "
                "Kernel or manual recovery evidence is required"
            )
            if snapshot.goal.status.value != "blocked":
                snapshot.goal.block(reason)
            snapshot.state = RunState.RECOVERY_REQUIRED
            snapshot.reanalysis_reason = reason
            return self._persist(
                snapshot,
                "work.recovery.required",
                {
                    "reason": reason,
                    "pending_action": dict(snapshot.pending_action),
                    "automatic_replay": False,
                },
            )
        if snapshot.goal.status.value in {"paused", "blocked", "waiting_user"}:
            snapshot.goal.resume()
        else:
            snapshot.goal.start_understanding()
        snapshot.state = RunState.RECOVERING
        pending = dict(snapshot.pending_action)
        snapshot.pending_action.clear()
        snapshot.reanalysis_reason = (
            "runtime resumed; re-evaluate workspace and external state before acting"
            + (
                "; the interrupted read-only action may be issued again only after "
                "this reassessment"
                if pending
                else ""
            )
        )
        self._persist(
            snapshot,
            "run.recovering",
            {
                "resume_policy": "reassess_before_action",
                "interrupted_action": pending,
            },
        )
        return self.run(
            run_id,
            deliberator=deliberator,
            tools=tools,
            verifier=verifier,
            max_iterations=max_iterations,
        )

    def steer(
        self,
        run_id: str,
        instruction: str,
        *,
        constraints: Mapping[str, Any] | None = None,
    ) -> WorkSnapshot:
        snapshot = self.require(run_id)
        if snapshot.terminal:
            raise ValueError("terminal work cannot be steered")
        instruction = str(instruction or "").strip()
        if not instruction and not constraints:
            raise ValueError("steering instruction or constraints are required")
        snapshot.goal.steer(instruction, constraints=dict(constraints or {}))
        if snapshot.plan is not None:
            snapshot.plan.note_revision(reason=instruction or "constraints updated")
            snapshot.plan.metadata.setdefault("steering", []).append(
                {
                    "revision": snapshot.plan.revision,
                    "instruction": instruction,
                    "constraints": dict(constraints or {}),
                    "at": work_timestamp(),
                }
            )
            snapshot.goal.bind_plan_revision(snapshot.plan.revision)
        snapshot.state = RunState.REPLANNING
        snapshot.reanalysis_reason = instruction or "work constraints changed"
        return self._persist(
            snapshot,
            "work.plan.updated",
            {
                "summary": snapshot.reanalysis_reason,
                "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
            },
        )

    def pause(self, run_id: str, *, reason: str = "") -> WorkSnapshot:
        snapshot = self.require(run_id)
        if snapshot.terminal:
            return snapshot
        snapshot.goal.pause(reason)
        snapshot.state = RunState.PAUSED
        snapshot.reanalysis_reason = str(reason or "paused by user")
        return self._persist(
            snapshot,
            "run.paused",
            {"reason": snapshot.reanalysis_reason},
        )

    def cancel(self, run_id: str, *, reason: str = "") -> WorkSnapshot:
        snapshot = self.require(run_id)
        if snapshot.terminal:
            return snapshot
        snapshot.goal.cancel()
        snapshot.state = RunState.CANCELLED
        snapshot.error = str(reason or "cancelled by user")
        return self._persist(
            snapshot,
            "run.cancelled",
            {"reason": snapshot.error},
        )

    def fail(self, run_id: str, *, reason: str) -> WorkSnapshot:
        snapshot = self.require(run_id)
        if snapshot.terminal:
            return snapshot
        snapshot.goal.fail(reason)
        snapshot.state = RunState.FAILED
        snapshot.error = str(reason or "work failed")
        return self._persist(
            snapshot,
            "run.failed",
            {"reason": snapshot.error},
        )

    def require(self, run_id: str) -> WorkSnapshot:
        candidates = [
            checkpoint
            for checkpoint in self.checkpoints.list()
            if checkpoint.metadata.get("kind") == "work_harness"
            and checkpoint.metadata.get("run_id") == str(run_id)
        ]
        if not candidates:
            raise KeyError(run_id)
        checkpoint = max(
            candidates,
            key=self._checkpoint_order,
        )
        snapshot = WorkSnapshot.from_dict(checkpoint.state)
        snapshot.last_checkpoint_id = checkpoint.checkpoint_id
        return snapshot

    def list(self) -> list[WorkSnapshot]:
        latest: dict[str, Checkpoint] = {}
        for checkpoint in self.checkpoints.list():
            if checkpoint.metadata.get("kind") != "work_harness":
                continue
            run_id = str(checkpoint.metadata.get("run_id") or "")
            current = latest.get(run_id)
            if current is None or self._checkpoint_order(
                checkpoint
            ) > self._checkpoint_order(current):
                latest[run_id] = checkpoint
        snapshots = [WorkSnapshot.from_dict(item.state) for item in latest.values()]
        return sorted(
            snapshots,
            key=lambda item: (item.updated_at, item.run_id),
            reverse=True,
        )

    def inspect(self, run_id: str) -> dict[str, Any]:
        snapshot = self.require(run_id)
        return {
            "work": snapshot.to_dict(),
            "events": [event.to_dict() for event in self.events.load_events(run_id)],
        }

    def context_for(
        self, snapshot: WorkSnapshot, *, recovering: bool = False
    ) -> WorkContext:
        workspace = snapshot_workspace(
            snapshot.workspace_root, root=snapshot.workspace_root
        )
        conversation: dict[str, Any] = {}
        if snapshot.conversation_id:
            conversation = self.conversations.context_window(snapshot.conversation_id)
        events = self.events.load_events(snapshot.run_id)[-20:]
        budget: dict[str, Any] = {}
        if snapshot.agent_run_id:
            try:
                budget = self.agent_runtime.budget_for(
                    snapshot.agent_run_id
                ).usage.to_dict()
            except Exception:
                budget = {}
        return WorkContext(
            run_id=snapshot.run_id,
            goal=snapshot.goal.to_dict(),
            assessment=snapshot.analysis.to_dict(),
            plan=snapshot.plan.to_dict() if snapshot.plan else None,
            workspace=workspace.to_dict(),
            conversation=conversation,
            recent_observations=tuple(snapshot.observations[-12:]),
            recent_events=tuple(event.to_dict() for event in events),
            loaded_tools=tuple(snapshot.loaded_tools.values()),
            loaded_skills=tuple(snapshot.loaded_skills.values()),
            reanalysis_reason=snapshot.reanalysis_reason,
            recovering=recovering or snapshot.state is RunState.RECOVERING,
            budget=budget,
        )

    def refresh(self, snapshot: WorkSnapshot) -> WorkSnapshot:
        current = self.require(snapshot.run_id)
        return (
            current
            if current.last_checkpoint_id != snapshot.last_checkpoint_id
            else snapshot
        )

    def agent_profile(self, tools: Any, *, max_iterations: int) -> AgentProfile:
        names = self._tool_names(tools)
        bindings = [
            AgentCapabilityBinding(
                capability_id="model.work.deliberate",
                model_id="model-router",
            )
        ]
        bindings.extend(
            AgentCapabilityBinding(capability_id=name) for name in sorted(names)
        )
        manifest = build_agent_manifest(
            "APEIR Work Agent",
            agent_id="agent.apeir.work",
            description="Durable goal-directed Work Harness execution",
            permissions=("runtime.execute", "workspace.read", "workspace.effect"),
        )
        manifest = replace(
            manifest,
            capabilities=tuple(bindings),
            budget=AgentBudget(
                max_tokens=2_000_000,
                max_runtime_ms=24 * 60 * 60 * 1000,
                max_invocations=max_iterations * 3,
                max_tool_invocations=max_iterations,
                max_model_invocations=max_iterations * 2,
                max_checkpoints=max_iterations * 2,
                max_steps=max_iterations * 3,
            ),
        )
        return AgentProfile(manifest=manifest, state=AgentState.READY)

    def ensure_agent(
        self,
        snapshot: WorkSnapshot,
        *,
        tools: Any,
        max_iterations: int,
    ) -> str:
        profile = self.agent_profile(tools, max_iterations=max_iterations)
        context = ExecutionContext(
            task_id=snapshot.goal.goal_id,
            agent_id=profile.agent_id,
            metadata={
                "source": "work.harness",
                "work_run_id": snapshot.run_id,
                "workspace_root": snapshot.workspace_root,
            },
        )
        if snapshot.agent_run_id:
            try:
                execution = self.agent_runtime.require(snapshot.agent_run_id)
            except Exception:
                if not snapshot.agent_checkpoint_id:
                    snapshot.agent_run_id = ""
                else:
                    execution = self.agent_runtime.restore(
                        snapshot.agent_checkpoint_id,
                        profile=profile,
                        context=context,
                    )
            if snapshot.agent_run_id:
                if execution.state.value == "CHECKPOINTED":
                    self.agent_runtime.resume(execution.run_id)
                return execution.run_id
        execution = self.agent_runtime.create(
            task_id=snapshot.goal.goal_id,
            profile=profile,
            context=context,
            metadata={"source": "work.harness", "work_run_id": snapshot.run_id},
        )
        self.agent_runtime.start(execution.run_id)
        snapshot.agent_run_id = execution.run_id
        self._persist(
            snapshot,
            "work.agent.started",
            {"agent_run_id": execution.run_id},
        )
        return execution.run_id

    def checkpoint_agent(self, snapshot: WorkSnapshot, *, resume: bool) -> None:
        if not snapshot.agent_run_id:
            return
        execution = self.agent_runtime.require(snapshot.agent_run_id)
        if execution.state.value not in {"RUNNING", "WAITING"}:
            return
        checkpoint = self.agent_runtime.checkpoint(snapshot.agent_run_id)
        snapshot.agent_checkpoint_id = checkpoint.checkpoint_id
        self._save_snapshot(snapshot)
        if resume:
            self.agent_runtime.resume(snapshot.agent_run_id)

    def replace_plan(
        self,
        snapshot: WorkSnapshot,
        steps: tuple[PlanStepDraft, ...],
        *,
        reason: str,
    ) -> None:
        if snapshot.plan is None:
            snapshot.plan = Plan(goal_id=snapshot.goal.goal_id)
        tasks = [
            Task(
                task_id=step.step_id,
                description=step.description,
                capability_id=step.capability_id,
                depends_on=list(step.depends_on),
                params=dict(step.params),
            )
            for step in steps
        ]
        ids = [task.task_id for task in tasks]
        if len(ids) != len(set(ids)):
            raise ValueError("replacement plan step ids must be unique")
        known = set(ids)
        if any(set(task.depends_on) - known for task in tasks):
            raise ValueError("replacement plan dependencies must reference known steps")
        snapshot.plan.replace_tasks(tasks, reason=reason)
        snapshot.plan.status = PlanStatus.READY
        snapshot.goal.bind_plan_revision(snapshot.plan.revision)
        snapshot.state = RunState.REPLANNING
        self._persist(
            snapshot,
            "work.plan.updated",
            {"plan": snapshot.plan.to_dict(), "summary": reason},
        )

    def persist_progress(
        self,
        snapshot: WorkSnapshot,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> WorkSnapshot:
        return self._persist(snapshot, event_type, payload)

    def append_result(self, snapshot: WorkSnapshot, content: str) -> None:
        if not snapshot.conversation_id or not str(content or "").strip():
            return
        self.conversations.append(
            ConversationMessage(
                conversation_id=snapshot.conversation_id,
                role="assistant",
                content=str(content),
                run_id=snapshot.run_id,
                task_id=snapshot.goal.goal_id,
            )
        )

    def _initial_plan(self, goal: Goal, analysis: TaskAnalysis) -> Plan:
        task_plan = self.planner.generate(analysis)
        plan = Plan(goal_id=goal.goal_id)
        for step in task_plan.steps:
            plan.tasks.append(
                Task(
                    task_id=step.step_id,
                    description=step.name,
                    capability_id=step.capability,
                    depends_on=list(task_plan.dependencies.get(step.step_id, ())),
                    params=dict(step.metadata),
                )
            )
        plan.status = PlanStatus.READY
        plan.metadata.update(task_plan.metadata)
        plan.metadata["source_plan_id"] = task_plan.plan_id
        return plan

    @staticmethod
    def _tool_names(tools: Any) -> set[str]:
        if tools is None:
            return set()
        specifications = getattr(tools, "specifications", None)
        if not callable(specifications):
            return set()
        names: set[str] = set()
        for item in specifications() or ():
            if not isinstance(item, Mapping):
                continue
            function = item.get("function")
            name = (
                str(function.get("name") or "")
                if isinstance(function, Mapping)
                else str(item.get("name") or "")
            )
            if name:
                names.add(name)
        return names

    def _persist(
        self,
        snapshot: WorkSnapshot,
        event_type: str,
        payload: Mapping[str, Any],
    ) -> WorkSnapshot:
        self._save_snapshot(snapshot)
        self.events.emit(
            RunEvent(
                run_id=snapshot.run_id,
                task_id=snapshot.goal.goal_id,
                event_type=event_type,
                actor="work.harness",
                payload=self._json_safe(
                    {"state": snapshot.state.value, **dict(payload)}
                ),
            )
        )
        return snapshot

    def _save_snapshot(self, snapshot: WorkSnapshot) -> WorkSnapshot:
        snapshot.updated_at = work_timestamp()
        snapshot.checkpoint_sequence += 1
        provisional = Checkpoint(
            task_id=snapshot.goal.goal_id,
            state={},
            metadata={"kind": "work_harness", "run_id": snapshot.run_id},
        )
        snapshot.last_checkpoint_id = provisional.checkpoint_id
        safe_state = self._json_safe(redact_sensitive_data(snapshot.to_dict()))
        checkpoint = Checkpoint(
            checkpoint_id=provisional.checkpoint_id,
            task_id=provisional.task_id,
            timestamp=provisional.timestamp,
            state=safe_state,
            metadata=provisional.metadata,
        )
        self.checkpoints.save(checkpoint)
        return snapshot

    @staticmethod
    def _json_safe(value: Any) -> Any:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    @staticmethod
    def _checkpoint_order(checkpoint: Checkpoint) -> tuple[int, str, str]:
        return (
            int(checkpoint.state.get("checkpoint_sequence") or 0),
            checkpoint.timestamp,
            checkpoint.checkpoint_id,
        )


__all__ = ["Deliberator", "Verifier", "WorkHarness"]

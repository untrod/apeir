"""Thin coordination layer over existing Plan, Workflow, Work, and Event APIs."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from nous_runtime.core.events import EventEnvelope
from nous_runtime.events.bus import RuntimeEventBus
from nous_runtime.intelligence.planning.models import TaskPlan
from nous_runtime.intelligence.planning.workflow import PlanWorkflowBridge
from nous_runtime.workflow.models import WorkflowRun, WorkflowState
from nous_runtime.workflow.runtime import StepHandler, WorkflowRuntime

from .session import (
    AgentSession,
    AgentSessionState,
    AgentSessionStore,
    session_timestamp,
    transition_session,
)

_OBSERVATION_LIMIT = 256
SessionPlanner = Callable[[AgentSession], TaskPlan]
SessionReplanner = Callable[[AgentSession], TaskPlan | None]


class AgentSessionCoordinator:
    """Bind durable Agent sessions to existing governed execution primitives.

    This class does not execute tools or Node operations directly. A TaskPlan is
    compiled into the existing Workflow Runtime, whose handlers remain the only
    path to local capabilities or Distributed Work.
    """

    def __init__(
        self,
        root: str | Path = ".",
        *,
        event_bus: RuntimeEventBus | None = None,
    ):
        self.root = Path(root).resolve()
        self.store = AgentSessionStore(self.root)
        self.events = event_bus or RuntimeEventBus(str(self.root))
        self._owns_event_bus = event_bus is None
        self._subscriptions: dict[tuple[str, str], Any] = {}
        self._lock = threading.RLock()
        self.restore_subscriptions()

    def create(
        self,
        *,
        agent_id: str,
        model: str,
        objective: str,
        context: Mapping[str, Any] | None = None,
        event_subscriptions: tuple[str, ...] = (),
        budget: Mapping[str, Any] | None = None,
        policy_scope: Mapping[str, Any] | None = None,
    ) -> AgentSession:
        from nous_runtime.core.redaction import (
            redact_sensitive_data,
            redact_sensitive_text,
        )

        session = AgentSession.create(
            agent_id=agent_id,
            model=model,
            objective=redact_sensitive_text(objective),
            context=redact_sensitive_data(dict(context or {})),
            event_subscriptions=event_subscriptions,
            budget=budget,
            policy_scope=policy_scope,
        )
        session = transition_session(session, AgentSessionState.ACTIVE)
        self.store.save(session)
        self._subscribe(session)
        self._publish("agent.session.created", session)
        return session

    def require(self, session_id: str) -> AgentSession:
        session = self.store.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def coordinate(
        self,
        session_id: str,
        planner: SessionPlanner,
        *,
        handlers: Mapping[str, StepHandler] | None = None,
        inputs: Mapping[str, Any] | None = None,
        replanner: SessionReplanner | None = None,
        max_replans: int = 0,
        max_parallel: int = 4,
    ) -> AgentSession:
        """Run one bounded goal-to-Workflow coordination cycle.

        Planner callbacks may use a model, a human-authored plan, or a
        deterministic planner. They only return TaskPlan proposals; all effects
        still pass through Workflow handlers and their existing authority path.
        """
        if not 0 <= max_replans <= 8:
            raise ValueError("max_replans must be between 0 and 8")
        session = self.require(session_id)
        if session.terminal:
            raise ValueError("cannot coordinate a terminal Agent session")
        try:
            session = transition_session(session, AgentSessionState.PLANNING)
            self.store.save(session)
            plan = planner(session)
            session = self.submit_plan(
                session_id,
                plan,
                handlers=handlers,
                inputs=inputs,
                max_parallel=max_parallel,
            )
            revisions = 0
            while (
                session.state is AgentSessionState.OBSERVING
                and session.error
                and replanner is not None
                and revisions < max_replans
            ):
                session = transition_session(
                    session, AgentSessionState.REPLANNING, error=session.error
                )
                self.store.save(session)
                replacement = replanner(session)
                if replacement is None:
                    break
                revisions += 1
                session = self.submit_plan(
                    session_id,
                    replacement,
                    handlers=handlers,
                    inputs=inputs,
                    max_parallel=max_parallel,
                    replan=True,
                )
            if session.state is AgentSessionState.OBSERVING and session.error:
                session = self.wait(session_id, reason=session.error)
            return session
        except Exception as exc:
            current = self.require(session_id)
            if current.terminal:
                raise
            self.fail(session_id, reason=str(exc))
            raise

    def submit_plan(
        self,
        session_id: str,
        plan: TaskPlan,
        *,
        handlers: Mapping[str, StepHandler] | None = None,
        inputs: Mapping[str, Any] | None = None,
        max_parallel: int = 4,
        replan: bool = False,
    ) -> AgentSession:
        session = self.require(session_id)
        if session.terminal:
            raise ValueError("cannot submit a plan to a terminal Agent session")
        from nous_runtime.core.redaction import redact_sensitive_data

        for step in plan.steps:
            if step.capability in {"reality.operation", "reality.observe"} and (
                redact_sensitive_data(step.metadata) != dict(step.metadata)
            ):
                raise ValueError("Credential material cannot enter a Reality Plan")
        target = AgentSessionState.REPLANNING if replan else AgentSessionState.PLANNING
        session = transition_session(session, target, error="")
        session = replace(
            session,
            plan_history=(*session.plan_history, plan.to_dict()),
            updated_at=session_timestamp(),
        )

        definition = PlanWorkflowBridge().compile(plan)
        runtime = WorkflowRuntime(
            str(self.root),
            handlers=dict(handlers or {}),
            max_parallel=max_parallel,
            event_bus=self.events,
            event_metadata={"agent_session_id": session.session_id},
        )
        runtime.register(definition)
        session = replace(
            session,
            workflow_id=definition.workflow_id,
            pending_approvals=(),
            result={},
            updated_at=session_timestamp(),
        )
        session = transition_session(session, AgentSessionState.SUBMITTING_WORK)
        self.store.save(session)
        self._publish(
            "agent.session.plan.submitted",
            session,
            {"plan_id": plan.plan_id, "workflow_id": definition.workflow_id},
        )

        run = runtime.start(
            definition.workflow_id,
            definition.version,
            {
                **dict(inputs or {}),
                "_agent_session_id": session.session_id,
                "_agent_id": session.agent_id,
                "_plan_id": plan.plan_id,
                "_workflow_id": definition.workflow_id,
            },
            idempotency_key=f"{session.session_id}:{plan.plan_id}",
        )
        return self._observe_workflow(session.session_id, runtime, run)

    def resume_plan(
        self,
        session_id: str,
        *,
        approved_steps: tuple[str, ...] = (),
        handlers: Mapping[str, StepHandler] | None = None,
        max_parallel: int = 4,
    ) -> AgentSession:
        session = self.require(session_id)
        if not session.workflow_run_id:
            raise ValueError("Agent session has no Workflow run to resume")
        if session.terminal:
            raise ValueError("cannot resume a terminal Agent session")
        runtime = WorkflowRuntime(
            str(self.root),
            handlers=dict(handlers or {}),
            max_parallel=max_parallel,
            event_bus=self.events,
            event_metadata={"agent_session_id": session.session_id},
        )
        if session.state is AgentSessionState.OBSERVING:
            session = transition_session(session, AgentSessionState.REPLANNING)
        session = transition_session(session, AgentSessionState.SUBMITTING_WORK)
        self.store.save(session)
        run = runtime.resume(session.workflow_run_id, approved_steps=approved_steps)
        observed = self._observe_workflow(session.session_id, runtime, run)
        if observed.state is AgentSessionState.OBSERVING and observed.error:
            return self.wait(session_id, reason=observed.error)
        return observed

    def wait(self, session_id: str, *, reason: str = "") -> AgentSession:
        session = transition_session(
            self.require(session_id), AgentSessionState.WAITING, error=reason
        )
        self.store.save(session)
        self._publish("agent.session.waiting", session, {"reason": reason})
        return session

    def complete(
        self, session_id: str, *, result: Mapping[str, Any] | None = None
    ) -> AgentSession:
        session = transition_session(
            self.require(session_id), AgentSessionState.COMPLETED, error=""
        )
        session = replace(
            session,
            result=dict(result or session.result),
            updated_at=session_timestamp(),
        )
        self.store.save(session)
        self._publish("agent.session.completed", session)
        return session

    def fail(self, session_id: str, *, reason: str) -> AgentSession:
        session = transition_session(
            self.require(session_id), AgentSessionState.FAILED, error=reason
        )
        self.store.save(session)
        self._publish("agent.session.failed", session, {"reason": reason})
        return session

    def cancel(self, session_id: str, *, reason: str = "") -> AgentSession:
        session = transition_session(
            self.require(session_id), AgentSessionState.CANCELLED, error=reason
        )
        self.store.save(session)
        self._publish("agent.session.cancelled", session, {"reason": reason})
        return session

    def restore_subscriptions(self) -> None:
        for session in self.store.list(include_terminal=False):
            self._subscribe(session)

    def close(self) -> None:
        with self._lock:
            subscriptions = tuple(self._subscriptions.items())
            self._subscriptions.clear()
        for (_, pattern), callback in subscriptions:
            self.events.unsubscribe(pattern, callback)
        if self._owns_event_bus:
            self.events.shutdown()

    def _observe_workflow(
        self,
        session_id: str,
        runtime: WorkflowRuntime,
        run: WorkflowRun,
    ) -> AgentSession:
        session = self.require(session_id)
        if session.state is AgentSessionState.SUBMITTING_WORK:
            session = transition_session(session, AgentSessionState.OBSERVING)
        events = tuple(
            {
                "kind": "workflow_event",
                **event.to_dict(),
            }
            for event in runtime.events.load_events(run.run_id)
        )
        reality_evidence = tuple(
            {
                "kind": "reality_effect",
                "work_id": output["work_id"],
                "receipt": dict(output.get("receipt") or {}),
                "observations": list(output.get("observations") or ()),
                "effect_verification": dict(output.get("effect_verification") or {}),
            }
            for output in run.outputs.values()
            if isinstance(output, Mapping) and output.get("effect_verification")
        )
        work_ids = tuple(
            dict.fromkeys(
                str(output.get("work_id"))
                for output in run.outputs.values()
                if isinstance(output, Mapping) and output.get("work_id")
            )
        )
        session = replace(
            session,
            workflow_run_id=run.run_id,
            active_work=work_ids,
            observations=(*session.observations, *events, *reality_evidence)[
                -_OBSERVATION_LIMIT:
            ],
            updated_at=session_timestamp(),
        )
        if run.state is WorkflowState.COMPLETED:
            session = transition_session(session, AgentSessionState.COMPLETED)
            session = replace(
                session,
                result={"workflow_outputs": dict(run.outputs)},
                pending_approvals=(),
                error="",
                updated_at=session_timestamp(),
            )
        elif run.state is WorkflowState.WAITING_APPROVAL:
            pending = tuple(
                str(run.outputs.get(step_id, {}).get("approval_request_id") or step_id)
                for step_id, state in run.step_states.items()
                if state == "waiting_approval"
            )
            session = replace(session, pending_approvals=pending)
            session = transition_session(
                session, AgentSessionState.WAITING, error=run.error
            )
        elif run.state in {
            WorkflowState.FAILED,
            WorkflowState.COMPENSATION_FAILED,
        }:
            # A failed Workflow is evidence for the Agent. It is not silently
            # retried and does not terminally fail the session before replan.
            session = replace(session, error=run.error, updated_at=session_timestamp())
        elif run.state is WorkflowState.CANCELLED:
            session = transition_session(
                session, AgentSessionState.CANCELLED, error=run.error
            )
        else:
            session = transition_session(session, AgentSessionState.WAITING)
        self.store.save(session)
        self._publish(
            "agent.session.workflow.observed",
            session,
            {"workflow_run_id": run.run_id, "workflow_state": run.state.value},
        )
        return session

    def _subscribe(self, session: AgentSession) -> None:
        for pattern in session.event_subscriptions:
            key = (session.session_id, pattern)
            with self._lock:
                if key in self._subscriptions:
                    continue

                def callback(
                    event: EventEnvelope,
                    *,
                    session_id: str = session.session_id,
                ) -> None:
                    self._record_event(session_id, event)

                self._subscriptions[key] = callback
            self.events.subscribe(pattern, callback)

    def _record_event(self, session_id: str, event: EventEnvelope) -> None:
        event_session = str(event.metadata.get("agent_session_id") or "")
        if event_session and event_session != session_id:
            return
        if event_session == session_id and event.source == "workflow.runtime":
            # The per-run EventStream is the authoritative durable copy for the
            # session's own Workflow. The global bus remains available to other
            # subscribers without duplicating the observation locally.
            return
        with self._lock:
            session = self.store.get(session_id)
            if session is None or session.terminal:
                return
            device_id = str(
                event.metadata.get("device_id") or event.payload.get("device_id") or ""
            )
            target_device = str(session.context.get("device_id") or "")
            if device_id and target_device and device_id != target_device:
                return
            if any(
                str(item.get("event_id") or "") == event.event_id
                for item in session.observations
            ):
                return
            observation = {"kind": "runtime_event", **event.to_dict()}
            target = session
            if session.state is AgentSessionState.WAITING:
                target = transition_session(session, AgentSessionState.OBSERVING)
            target = replace(
                target,
                observations=(*target.observations, observation)[-_OBSERVATION_LIMIT:],
                updated_at=session_timestamp(),
            )
            self.store.save(target)

    def _publish(
        self,
        event_type: str,
        session: AgentSession,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.events.publish(
            event_type,
            source="agent.coordination",
            payload={"session_id": session.session_id, **dict(payload or {})},
            metadata={"agent_session_id": session.session_id},
        )


__all__ = [
    "AgentSessionCoordinator",
    "SessionPlanner",
    "SessionReplanner",
]

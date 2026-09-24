"""Decision/observation loop for the durable Work Harness."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from typing import Any, TYPE_CHECKING

from nous_runtime.agent.execution_state import (
    AgentExecutionState,
    InvocationStatus,
)
from nous_runtime.events import RunState
from nous_runtime.planner.plan import PlanStatus, TaskStatus
from nous_runtime.work.models import (
    DecisionStatus,
    WorkContext,
    WorkDecision,
    WorkSnapshot,
    work_timestamp,
)

if TYPE_CHECKING:
    from nous_runtime.work.runtime import WorkHarness


Deliberator = Callable[[WorkContext], WorkDecision | Mapping[str, Any]]
Verifier = Callable[[WorkContext], bool | Mapping[str, Any]]


class AgentLoop:
    """Run one bounded, checkpointed deliberation loop over existing services."""

    def __init__(self, harness: "WorkHarness") -> None:
        self.harness = harness

    def run(
        self,
        snapshot: WorkSnapshot,
        *,
        deliberator: Deliberator,
        tools: Any = None,
        verifier: Verifier | None = None,
        max_iterations: int = 32,
    ) -> WorkSnapshot:
        maximum = max(1, min(int(max_iterations), 1_000))
        recovering = snapshot.state is RunState.RECOVERING
        agent_run_id = self.harness.ensure_agent(
            snapshot,
            tools=tools,
            max_iterations=maximum,
        )

        for iteration in range(1, maximum + 1):
            snapshot = self.harness.refresh(snapshot)
            if snapshot.terminal:
                return snapshot
            if snapshot.state in {
                RunState.PAUSED,
                RunState.WAITING_USER,
                RunState.WAITING_FOR_APPROVAL,
                RunState.BLOCKED,
                RunState.RECOVERY_REQUIRED,
            }:
                self.harness.checkpoint_agent(snapshot, resume=False)
                return snapshot

            snapshot.state = RunState.UNDERSTANDING
            self.harness.persist_progress(
                snapshot,
                "work.analysis",
                {
                    "summary": (
                        "Re-evaluating current state before continuing"
                        if recovering or snapshot.reanalysis_reason
                        else "Evaluating the next bounded action"
                    ),
                    "iteration": iteration,
                    "recovering": recovering,
                    "trigger": snapshot.reanalysis_reason,
                },
            )
            decision_checkpoint_id = snapshot.last_checkpoint_id
            context = self.harness.context_for(snapshot, recovering=recovering)
            captured: dict[str, Any] = {}

            def deliberate(_request: Any) -> Any:
                value = deliberator(context)
                captured["decision"] = value
                return value

            invocation = self.harness.agent_runtime.invoke_model(
                agent_run_id,
                model_id="model-router",
                capability_id="model.work.deliberate",
                handler=deliberate,
            )
            if invocation.status is not InvocationStatus.COMPLETED:
                return self._fail(
                    snapshot,
                    invocation.message or "work deliberation failed",
                )

            latest = self.harness.require(snapshot.run_id)
            if latest.last_checkpoint_id != decision_checkpoint_id:
                snapshot = latest
                if snapshot.terminal:
                    return snapshot
                if snapshot.state in {
                    RunState.PAUSED,
                    RunState.WAITING_USER,
                    RunState.WAITING_FOR_APPROVAL,
                    RunState.BLOCKED,
                    RunState.RECOVERY_REQUIRED,
                }:
                    self.harness.checkpoint_agent(snapshot, resume=False)
                    return snapshot
                snapshot.reanalysis_reason = (
                    snapshot.reanalysis_reason
                    or "work state changed during deliberation; discard stale decision"
                )
                recovering = False
                continue
            try:
                decision = WorkDecision.from_value(captured.get("decision"))
            except (TypeError, ValueError) as exc:
                return self._fail(snapshot, f"invalid work decision: {exc}")

            snapshot.last_decision = decision
            snapshot.reanalysis_reason = ""
            self._complete_analysis_step(snapshot, decision)
            self.harness.persist_progress(
                snapshot,
                "work.progress",
                {
                    "summary": decision.summary,
                    "next_action": decision.next_action,
                    "confidence": decision.confidence,
                    "decision_status": decision.status.value,
                    "iteration": iteration,
                },
            )

            if decision.plan_revision_required:
                self.harness.replace_plan(
                    snapshot,
                    decision.replacement_steps,
                    reason=decision.reason or decision.summary,
                )

            if decision.status is DecisionStatus.ASK_USER:
                snapshot.goal.wait_for_user(decision.reason or decision.summary)
                snapshot.state = RunState.WAITING_USER
                self.harness.checkpoint_agent(snapshot, resume=False)
                return self.harness.persist_progress(
                    snapshot,
                    "work.waiting_user",
                    {"summary": decision.summary, "question": decision.next_action},
                )

            if decision.status is DecisionStatus.REQUEST_APPROVAL:
                snapshot.goal.wait_for_user(decision.reason or decision.summary)
                snapshot.state = RunState.WAITING_FOR_APPROVAL
                self.harness.checkpoint_agent(snapshot, resume=False)
                return self.harness.persist_progress(
                    snapshot,
                    "work.waiting_approval",
                    {
                        "summary": decision.summary,
                        "action": decision.next_action,
                        "tool": decision.tool_name,
                    },
                )

            if decision.status is DecisionStatus.BLOCKED:
                snapshot.goal.block(decision.reason or decision.summary)
                snapshot.state = RunState.BLOCKED
                self.harness.checkpoint_agent(snapshot, resume=False)
                return self.harness.persist_progress(
                    snapshot,
                    "work.blocked",
                    {"summary": decision.summary, "reason": snapshot.goal.blocker},
                )

            if decision.status is DecisionStatus.FAIL:
                return self._fail(snapshot, decision.reason or decision.summary)

            if decision.status is DecisionStatus.REPLAN:
                snapshot.state = RunState.REPLANNING
                snapshot.reanalysis_reason = decision.reason or decision.summary
                self.harness.checkpoint_agent(snapshot, resume=True)
                self.harness.persist_progress(
                    snapshot,
                    "work.plan.updated",
                    {
                        "summary": snapshot.reanalysis_reason,
                        "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
                    },
                )
                recovering = False
                continue

            if decision.status is DecisionStatus.VERIFY:
                verified = self._verify(snapshot, verifier)
                self.harness.checkpoint_agent(snapshot, resume=True)
                if not verified:
                    recovering = False
                    continue
                snapshot.state = RunState.OBSERVING
                self.harness.persist_progress(
                    snapshot,
                    "work.milestone",
                    {"summary": "Verification passed"},
                )
                recovering = False
                continue

            if decision.status is DecisionStatus.COMPLETE:
                if not self._completion_gate(snapshot, verifier):
                    self.harness.checkpoint_agent(snapshot, resume=True)
                    recovering = False
                    continue
                return self._complete(snapshot, decision)

            if decision.tool_name:
                self._execute_tool(snapshot, decision, tools, agent_run_id)
                execution = self.harness.agent_runtime.require(agent_run_id)
                if execution.state in {
                    AgentExecutionState.FAILED,
                    AgentExecutionState.TERMINATED,
                    AgentExecutionState.TIMED_OUT,
                }:
                    return self._fail(
                        snapshot,
                        execution.termination_message or "agent execution terminated",
                    )
                self.harness.checkpoint_agent(snapshot, resume=True)
            elif decision.step_id:
                self._complete_reasoning_step(snapshot, decision)
                self.harness.checkpoint_agent(snapshot, resume=True)
            else:
                snapshot.reanalysis_reason = (
                    "decision selected no executable action; reassess the next step"
                )
                self.harness.checkpoint_agent(snapshot, resume=True)

            recovering = False

        snapshot.goal.block("work iteration budget reached")
        snapshot.state = RunState.BLOCKED
        snapshot.reanalysis_reason = "iteration budget reached"
        self.harness.checkpoint_agent(snapshot, resume=False)
        return self.harness.persist_progress(
            snapshot,
            "work.blocked",
            {"reason": snapshot.reanalysis_reason, "max_iterations": maximum},
        )

    def _execute_tool(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        tools: Any,
        agent_run_id: str,
    ) -> None:
        discovery_tools = {"catalog_expand", "skill_list", "skill_search", "skill_load"}
        step_id = "" if decision.tool_name in discovery_tools else decision.step_id
        snapshot.state = RunState.EXECUTING
        snapshot.current_step = step_id
        self.harness.persist_progress(
            snapshot,
            "work.progress",
            {
                "summary": decision.summary,
                "tool": decision.tool_name,
                "step_id": step_id,
            },
        )
        known = self.harness._tool_names(tools)
        execute = getattr(tools, "execute", None) if tools is not None else None
        progressive = callable(getattr(tools, "prompt_specifications", None))
        disclosed = (
            decision.tool_name == "catalog_expand"
            or decision.tool_name in snapshot.loaded_tools
        )
        captured: dict[str, Any] = {}
        effect_class, capability_id = self._tool_effect(tools, decision.tool_name)
        snapshot.pending_action = {
            "tool": decision.tool_name,
            "step_id": step_id,
            "arguments_digest": self._arguments_digest(decision.tool_arguments),
            "effect_class": effect_class,
            "capability_id": capability_id,
            "action_sequence": snapshot.action_sequence + 1,
            "dispatched_at": work_timestamp(),
            "recovery_policy": (
                "reassess_then_reissue"
                if effect_class in {"none", "read"}
                else "kernel_or_manual"
            ),
        }
        self.harness.persist_progress(
            snapshot,
            "work.action.dispatched",
            {"action": dict(snapshot.pending_action)},
        )
        if decision.tool_name not in known or not callable(execute):
            result: Any = {
                "ok": False,
                "error": f"tool is unavailable: {decision.tool_name}",
            }
            invocation_status = "denied"
        elif progressive and not disclosed:
            result = {
                "ok": False,
                "error": (
                    f"tool schema is not loaded: {decision.tool_name}; "
                    "use catalog_expand first"
                ),
            }
            invocation_status = "denied"
        else:

            def invoke(_request: Any) -> Any:
                value = execute(decision.tool_name, dict(decision.tool_arguments))
                captured["result"] = value
                return value

            invocation = self.harness.agent_runtime.invoke_tool(
                agent_run_id,
                tool_id=decision.tool_name,
                capability_id=decision.tool_name,
                parameters=dict(decision.tool_arguments),
                handler=invoke,
            )
            invocation_status = invocation.status.value
            result = captured.get("result")
            if result is None:
                result = {
                    "ok": False,
                    "error": invocation.message or "tool invocation failed",
                    "error_code": invocation.error_code,
                }

        normalized = self._result_mapping(result)
        ok = invocation_status == "completed" and self._result_ok(normalized)
        if decision.tool_name == "catalog_expand" and ok:
            for item in normalized.get("tools") or ():
                if not isinstance(item, Mapping):
                    continue
                tool_id = str(item.get("tool_id") or "")
                if tool_id:
                    snapshot.loaded_tools[tool_id] = dict(item)
            while len(snapshot.loaded_tools) > 64:
                snapshot.loaded_tools.pop(next(iter(snapshot.loaded_tools)))
        if decision.tool_name == "skill_load" and ok:
            skill = normalized.get("skill")
            if isinstance(skill, Mapping):
                skill_id = str(skill.get("skill_id") or "")
                if skill_id:
                    snapshot.loaded_skills[skill_id] = dict(skill)
            while len(snapshot.loaded_skills) > 16:
                snapshot.loaded_skills.pop(next(iter(snapshot.loaded_skills)))
        snapshot.action_sequence += 1
        observation = {
            "kind": "tool",
            "tool": decision.tool_name,
            "step_id": step_id,
            "ok": ok,
            "action_sequence": snapshot.action_sequence,
            "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
            "result": normalized,
            "observed_at": work_timestamp(),
        }
        snapshot.observations.append(observation)
        snapshot.observations[:] = snapshot.observations[-50:]
        snapshot.pending_action.clear()
        self._collect_artifacts(snapshot, normalized)
        self._record_task_result(snapshot, step_id, ok, normalized)
        snapshot.state = RunState.OBSERVING
        snapshot.reanalysis_reason = (
            "" if ok else f"tool {decision.tool_name} failed; analyze before retrying"
        )
        self.harness.persist_progress(
            snapshot,
            "work.observing",
            {
                "tool": decision.tool_name,
                "step_id": step_id,
                "ok": ok,
                "error": str(normalized.get("error") or "")[:500],
            },
        )

    @staticmethod
    def _tool_effect(tools: Any, tool_name: str) -> tuple[str, str]:
        require = getattr(tools, "require", None)
        if not callable(require):
            return "unknown", tool_name
        try:
            definition = require(tool_name)
        except (KeyError, ValueError):
            return "unknown", tool_name
        return (
            str(getattr(definition, "effect_class", "unknown") or "unknown"),
            str(getattr(definition, "capability_id", tool_name) or tool_name),
        )

    @staticmethod
    def _arguments_digest(arguments: Mapping[str, Any]) -> str:
        encoded = json.dumps(
            dict(arguments),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _verify(self, snapshot: WorkSnapshot, verifier: Verifier | None) -> bool:
        snapshot.state = RunState.VERIFYING
        self.harness.persist_progress(
            snapshot,
            "work.verifying",
            {"summary": "Checking completion criteria and current results"},
        )
        if verifier is None:
            result: Mapping[str, Any] = {
                "ok": not snapshot.goal.completion_criteria and snapshot.plan is None,
                "error": "verification handler is required"
                if snapshot.goal.completion_criteria or snapshot.plan is not None
                else "",
            }
        else:
            try:
                value = verifier(self.harness.context_for(snapshot))
                result = (
                    dict(value) if isinstance(value, Mapping) else {"ok": bool(value)}
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
        ok = self._result_ok(result)
        snapshot.observations.append(
            {
                "kind": "verification",
                "ok": ok,
                "action_sequence": snapshot.action_sequence,
                "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
                "result": dict(result),
                "observed_at": work_timestamp(),
            }
        )
        snapshot.observations[:] = snapshot.observations[-50:]
        if snapshot.plan is not None:
            verify_task = next(
                (task for task in snapshot.plan.tasks if task.task_id == "verify"),
                None,
            )
            if verify_task is not None:
                verify_task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
                verify_task.result = dict(result)
                verify_task.error = (
                    "" if ok else str(result.get("error") or "verification failed")
                )
        snapshot.reanalysis_reason = (
            "" if ok else str(result.get("error") or "verification failed; reanalyze")
        )
        self.harness.persist_progress(
            snapshot,
            "work.milestone" if ok else "work.progress",
            {
                "summary": "Verification passed" if ok else "Verification failed",
                "ok": ok,
                "error": str(result.get("error") or "")[:500],
            },
        )
        return ok

    def _completion_gate(
        self,
        snapshot: WorkSnapshot,
        verifier: Verifier | None,
    ) -> bool:
        verified = any(
            item.get("kind") == "verification"
            and item.get("ok") is True
            and int(item.get("action_sequence") or 0) == snapshot.action_sequence
            and int(item.get("plan_revision") or 0)
            == (snapshot.plan.revision if snapshot.plan else 0)
            for item in snapshot.observations
        )
        if not verified and (
            snapshot.plan is not None or snapshot.goal.completion_criteria
        ):
            verified = self._verify(snapshot, verifier)
        if not verified and (
            snapshot.plan is not None or snapshot.goal.completion_criteria
        ):
            return False
        if snapshot.plan is not None:
            if snapshot.plan.any_failed() or not snapshot.plan.all_done():
                snapshot.reanalysis_reason = (
                    "completion gate rejected: plan still has non-terminal steps"
                )
                snapshot.state = RunState.UNDERSTANDING
                self.harness.persist_progress(
                    snapshot,
                    "work.analysis",
                    {"summary": snapshot.reanalysis_reason},
                )
                return False
            snapshot.plan.status = PlanStatus.COMPLETED
        return True

    def _complete(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> WorkSnapshot:
        snapshot.goal.complete()
        snapshot.state = RunState.COMPLETED
        snapshot.result = (
            decision.output if decision.output is not None else decision.summary
        )
        snapshot.current_step = ""
        execution = self.harness.agent_runtime.require(snapshot.agent_run_id)
        if execution.state is AgentExecutionState.RUNNING:
            self.harness.agent_runtime.complete(
                snapshot.agent_run_id,
                message=decision.summary,
            )
        self.harness.persist_progress(
            snapshot,
            "work.completed",
            {
                "summary": decision.summary,
                "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
            },
        )
        self.harness.append_result(snapshot, str(snapshot.result))
        return snapshot

    def _fail(self, snapshot: WorkSnapshot, reason: str) -> WorkSnapshot:
        snapshot.goal.fail(reason)
        snapshot.state = RunState.FAILED
        snapshot.error = str(reason or "work failed")
        if snapshot.agent_run_id:
            try:
                execution = self.harness.agent_runtime.require(snapshot.agent_run_id)
                if execution.state is AgentExecutionState.RUNNING:
                    self.harness.agent_runtime.fail(
                        snapshot.agent_run_id,
                        message=snapshot.error,
                    )
            except Exception:
                pass
        return self.harness.persist_progress(
            snapshot,
            "run.failed",
            {"reason": snapshot.error},
        )

    @staticmethod
    def _complete_analysis_step(
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> None:
        if snapshot.plan is None:
            return
        try:
            task = snapshot.plan.require_task("analyze")
        except KeyError:
            return
        if task.status in {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.RUNNING}:
            task.status = TaskStatus.COMPLETED
            task.result = {"summary": decision.summary}

    @staticmethod
    def _complete_reasoning_step(
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> None:
        if snapshot.plan is None:
            return
        try:
            task = snapshot.plan.require_task(decision.step_id)
        except KeyError:
            snapshot.reanalysis_reason = f"unknown plan step: {decision.step_id}"
            return
        if task.capability_id != "reasoning":
            snapshot.reanalysis_reason = (
                f"step {decision.step_id} requires an executable capability"
            )
            return
        task.status = TaskStatus.COMPLETED
        task.result = {"summary": decision.summary}

    @staticmethod
    def _record_task_result(
        snapshot: WorkSnapshot,
        step_id: str,
        ok: bool,
        result: Mapping[str, Any],
    ) -> None:
        if snapshot.plan is None or not step_id:
            return
        try:
            task = snapshot.plan.require_task(step_id)
        except KeyError:
            snapshot.reanalysis_reason = (
                f"tool result referenced unknown step: {step_id}"
            )
            return
        task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
        task.result = dict(result)
        task.error = "" if ok else str(result.get("error") or "tool failed")
        task.completed_at = work_timestamp()

    @staticmethod
    def _result_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        return {"ok": True, "result": value}

    @staticmethod
    def _result_ok(value: Mapping[str, Any]) -> bool:
        for key in ("ok", "success", "passed"):
            if key in value:
                return bool(value[key])
        return True

    @staticmethod
    def _collect_artifacts(
        snapshot: WorkSnapshot,
        result: Mapping[str, Any],
    ) -> None:
        values: list[Any] = [result]
        if isinstance(result.get("files"), list):
            values.extend(result["files"])
        for key in ("artifact", "evidence_ref"):
            if isinstance(result.get(key), Mapping):
                values.append(result[key])
        for item in values:
            if not isinstance(item, Mapping):
                continue
            artifact_id = str(item.get("artifact_id") or item.get("artifact_ref") or "")
            if artifact_id and artifact_id not in snapshot.artifacts:
                snapshot.artifacts.append(artifact_id)


__all__ = ["AgentLoop", "Deliberator", "Verifier"]

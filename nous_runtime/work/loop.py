"""Decision/observation loop for the durable Work Harness."""

from __future__ import annotations

import hashlib
import json
import re
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
_MAX_IDENTICAL_READ_SUPPRESSIONS = 3
_MAX_URL_FAILURE_ATTEMPTS = 3
_RETRYABLE_WEB_FAILURES = {
    "NETWORK_CONNECT_FAILED",
    "NETWORK_CONNECTION_RESET",
    "NETWORK_DNS_FAILED",
    "NETWORK_RATE_LIMITED",
    "NETWORK_TIMEOUT",
}
_NON_RETRYABLE_WEB_FAILURES = {
    "NETWORK_BODY_BLOCKED",
    "NETWORK_CANCELLED",
    "NETWORK_CREDENTIAL_REDIRECT_BLOCKED",
    "NETWORK_CREDENTIAL_UNAVAILABLE",
    "NETWORK_DOMAIN_BLOCKED",
    "NETWORK_DOMAIN_NOT_ALLOWED",
    "NETWORK_ENCODING_BLOCKED",
    "NETWORK_HEADER_INVALID",
    "NETWORK_HEADER_BLOCKED",
    "NETWORK_METHOD_BLOCKED",
    "NETWORK_MIME_MISMATCH",
    "NETWORK_REDIRECT_INVALID",
    "NETWORK_REDIRECT_LIMIT",
    "NETWORK_REDIRECT_LOOP",
    "NETWORK_REQUEST_TOO_LARGE",
    "NETWORK_RESPONSE_TOO_LARGE",
    "NETWORK_RETRY_UNSAFE",
    "NETWORK_SCHEME_BLOCKED",
    "NETWORK_SCOPE_BLOCKED",
    "NETWORK_SSRF_BLOCKED",
    "NETWORK_TLS_FAILED",
    "NETWORK_URL_INVALID",
}
_VOLATILE_OBSERVATION_TOOLS = {
    "shell_status",
    "shell_attach",
    "shell_stdout",
    "shell_stderr",
}


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
        snapshot = self._prepare_governed_context(snapshot, tools, agent_run_id)
        if snapshot.terminal:
            return snapshot
        if (
            str(snapshot.pending_action.get("recovery_policy") or "")
            == "approved_replay"
        ):
            pending = dict(snapshot.pending_action)
            arguments = dict(pending.get("arguments") or {})
            if self._arguments_digest(arguments) != str(
                pending.get("arguments_digest") or ""
            ):
                snapshot.goal.block("approved action arguments failed integrity check")
                snapshot.state = RunState.RECOVERY_REQUIRED
                snapshot.reanalysis_reason = snapshot.goal.blocker
                return self.harness.persist_progress(
                    snapshot,
                    "work.recovery.required",
                    {
                        "reason": snapshot.goal.blocker,
                        "pending_action": pending,
                        "automatic_replay": False,
                    },
                )
            self._execute_tool(
                snapshot,
                WorkDecision(
                    status=DecisionStatus.CONTINUE,
                    summary="Execute the exact action covered by the granted approval",
                    next_action="Consume the bound one-use approval lease",
                    confidence="high",
                    tool_name=str(pending.get("tool") or ""),
                    tool_arguments=arguments,
                    step_id=str(pending.get("step_id") or ""),
                    phase=str(pending.get("phase") or ""),
                    action_source="approved_replay",
                ),
                tools,
                agent_run_id,
            )
            snapshot = self.harness.require(snapshot.run_id)
            if snapshot.state in {
                RunState.WAITING_FOR_APPROVAL,
                RunState.RECOVERY_REQUIRED,
            }:
                self.harness.checkpoint_agent(snapshot, resume=False)
                return snapshot
            self.harness.persist_progress(
                snapshot,
                "work.approval.consumed",
                {
                    "approval_request_id": str(
                        pending.get("approval_request_id") or ""
                    ),
                    "tool": str(pending.get("tool") or ""),
                    "arguments_digest": str(pending.get("arguments_digest") or ""),
                },
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
            self._reconcile_plan_progress(snapshot)
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
                reason = invocation.message or "work deliberation failed"
                if self.harness.is_recoverable_runtime_failure(reason):
                    return self.harness.require_runtime_recovery(
                        snapshot,
                        reason=reason,
                    )
                return self._fail(snapshot, reason)

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

            skill_discovery = self._required_skill_discovery(snapshot, decision, tools)
            if skill_discovery is not None:
                decision = skill_discovery
            elif (
                bool(snapshot.analysis.needs_tools)
                and not snapshot.loaded_tools
                and decision.status in {DecisionStatus.BLOCKED, DecisionStatus.COMPLETE}
                and "catalog_expand" in self.harness._tool_names(tools)
            ):
                decision = WorkDecision(
                    status=DecisionStatus.CONTINUE,
                    summary="Load workspace file tools before making a terminal decision",
                    next_action="Discover the governed workspace file tools",
                    confidence="high",
                    tool_name="catalog_expand",
                    tool_arguments={"category": "files"},
                )
            elif (
                bool(snapshot.analysis.needs_tools)
                and "list_workspace" in snapshot.loaded_tools
                and decision.status in {DecisionStatus.BLOCKED, DecisionStatus.COMPLETE}
                and not any(
                    item.get("kind") == "tool"
                    and item.get("ok") is True
                    and item.get("tool")
                    not in {
                        "catalog_expand",
                        "skill_list",
                        "skill_search",
                        "skill_load",
                    }
                    for item in snapshot.observations
                )
            ):
                decision = WorkDecision(
                    status=DecisionStatus.CONTINUE,
                    summary="Inspect the workspace before making a terminal decision",
                    next_action="List the governed workspace root",
                    confidence="high",
                    tool_name="list_workspace",
                    tool_arguments={"path": ".", "max_depth": 2},
                )
            elif self._needs_safe_inspection(snapshot, decision):
                search_path = self._latest_search_match(snapshot)
                if search_path and "read_file" in snapshot.loaded_tools:
                    path, line = search_path
                    decision = WorkDecision(
                        status=DecisionStatus.CONTINUE,
                        summary="Read a relevant source match before deciding",
                        next_action="Inspect the matched source context",
                        confidence="high",
                        tool_name="read_file",
                        tool_arguments={
                            "path": path,
                            "start_line": max(1, line - 20),
                            "end_line": line + 80,
                        },
                    )
                elif "search_workspace" in snapshot.loaded_tools:
                    decision = WorkDecision(
                        status=DecisionStatus.CONTINUE,
                        summary="Search the workspace before deciding",
                        next_action="Locate code related to the goal",
                        confidence="high",
                        tool_name="search_workspace",
                        tool_arguments={
                            "query": self._workspace_search_query(
                                snapshot.goal.objective
                            ),
                            "path": ".",
                        },
                    )

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

            patch_recovery_read = self._failed_patch_recovery_read(
                snapshot,
                decision,
            )
            covered = (
                None
                if patch_recovery_read
                else self._covered_file_read(snapshot, decision)
            )
            if covered is not None:
                if self._awaiting_action_transition(snapshot):
                    return self._block_action_transition_stall(snapshot, decision)
                self._record_covered_read(snapshot, decision, covered)
                self.harness.checkpoint_agent(snapshot, resume=True)
                recovering = False
                continue

            retry_block = self._web_retry_block(snapshot, decision)
            if retry_block is not None:
                return self._block_web_retry(snapshot, decision, retry_block)

            duplicate = (
                None
                if patch_recovery_read
                else self._successful_read_action(snapshot, decision, tools)
            )
            if duplicate is not None:
                arguments_digest = self._arguments_digest(decision.tool_arguments)
                suppression_count = 1 + sum(
                    1
                    for observation in snapshot.observations
                    if observation.get("kind") == "guardrail"
                    and observation.get("tool") == decision.tool_name
                    and observation.get("arguments_digest") == arguments_digest
                    and int(observation.get("plan_revision") or 0)
                    == (snapshot.plan.revision if snapshot.plan else 0)
                )
                snapshot.reanalysis_reason = (
                    "identical read-only action already succeeded; use the recorded "
                    "observation and choose a different action"
                )
                snapshot.observations.append(
                    {
                        "kind": "guardrail",
                        "tool": decision.tool_name,
                        "step_id": decision.step_id,
                        "ok": False,
                        "action_sequence": snapshot.action_sequence,
                        "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
                        "arguments_digest": arguments_digest,
                        "result": {
                            "ok": False,
                            "duplicate": True,
                            "suppression_count": suppression_count,
                            "reused_action_sequence": int(
                                duplicate.get("action_sequence") or 0
                            ),
                            "error": snapshot.reanalysis_reason,
                        },
                        "observed_at": work_timestamp(),
                    }
                )
                snapshot.observations[:] = snapshot.observations[-50:]
                self.harness.persist_progress(
                    snapshot,
                    "work.action.suppressed",
                    {
                        "tool": decision.tool_name,
                        "arguments_digest": arguments_digest,
                        "reason": snapshot.reanalysis_reason,
                        "suppression_count": suppression_count,
                        "reused_action_sequence": int(
                            duplicate.get("action_sequence") or 0
                        ),
                    },
                )
                if suppression_count >= _MAX_IDENTICAL_READ_SUPPRESSIONS:
                    reason = (
                        "repeated identical read-only decision loop detected; "
                        "automatic execution stopped to protect the model budget"
                    )
                    snapshot.goal.block(reason)
                    snapshot.state = RunState.BLOCKED
                    snapshot.reanalysis_reason = reason
                    self.harness.checkpoint_agent(snapshot, resume=False)
                    return self.harness.persist_progress(
                        snapshot,
                        "work.blocked",
                        {
                            "reason": reason,
                            "tool": decision.tool_name,
                            "arguments_digest": arguments_digest,
                            "suppression_count": suppression_count,
                        },
                    )
                self.harness.checkpoint_agent(snapshot, resume=True)
                recovering = False
                continue

            if (
                self._awaiting_action_transition(snapshot)
                and decision.tool_name != "patch_file"
                and not self._decision_can_add_evidence(snapshot, decision, tools)
            ):
                return self._block_action_transition_stall(snapshot, decision)

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
                if snapshot.state is RunState.RECOVERY_REQUIRED:
                    self.harness.checkpoint_agent(snapshot, resume=False)
                    return snapshot
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

    def _prepare_governed_context(
        self,
        snapshot: WorkSnapshot,
        tools: Any,
        agent_run_id: str,
    ) -> WorkSnapshot:
        """Load deterministic, read-only prerequisites without model calls.

        Catalog discovery and a recommended Skill are controller prerequisites, not
        reasoning decisions. They still travel through AgentRuntime, create normal
        observations, and are checkpointed; only the provider round trip is removed.
        """

        known = self.harness._tool_names(tools)
        if "catalog_expand" not in known:
            return snapshot

        categories: list[str] = []
        if snapshot.analysis.needs_workspace:
            categories.append("files")
        if snapshot.analysis.task_type == "coding":
            categories.append("shell")
            if known.intersection(
                {"git_status", "git_diff", "git_log", "git_branch", "git_show"}
            ):
                categories.append("git")
        if snapshot.analysis.needs_web:
            categories.append("web")

        for category in categories:
            if self._category_is_loaded(snapshot, category):
                continue
            self._execute_tool(
                snapshot,
                WorkDecision(
                    status=DecisionStatus.CONTINUE,
                    summary=f"Prepare governed {category} tools",
                    next_action=f"Load the {category} tool catalog",
                    confidence="high",
                    tool_name="catalog_expand",
                    tool_arguments={"category": category},
                ),
                tools,
                agent_run_id,
            )
            self.harness.checkpoint_agent(snapshot, resume=True)

        candidates = tuple(
            str(item)
            for item in snapshot.analysis.candidate_skills
            if str(item) and str(item) not in snapshot.loaded_skills
        )
        if not candidates or "skill_load" not in known:
            return snapshot
        if not self._category_is_loaded(snapshot, "skill"):
            self._execute_tool(
                snapshot,
                WorkDecision(
                    status=DecisionStatus.CONTINUE,
                    summary="Prepare governed Skill discovery",
                    next_action="Load the Skill catalog",
                    confidence="high",
                    tool_name="catalog_expand",
                    tool_arguments={"category": "skill"},
                ),
                tools,
                agent_run_id,
            )
            self.harness.checkpoint_agent(snapshot, resume=True)
        if "skill_load" not in snapshot.loaded_tools:
            return snapshot
        self._execute_tool(
            snapshot,
            WorkDecision(
                status=DecisionStatus.CONTINUE,
                summary="Load the recommended Skill",
                next_action=f"Load Skill {candidates[0]}",
                confidence="high",
                tool_name="skill_load",
                tool_arguments={"skill_id": candidates[0]},
            ),
            tools,
            agent_run_id,
        )
        self.harness.checkpoint_agent(snapshot, resume=True)
        return snapshot

    @staticmethod
    def _category_is_loaded(snapshot: WorkSnapshot, category: str) -> bool:
        return any(
            str(item.get("category") or "") == category
            for item in snapshot.loaded_tools.values()
        )

    @staticmethod
    def _needs_safe_inspection(snapshot: WorkSnapshot, decision: WorkDecision) -> bool:
        if not bool(snapshot.analysis.needs_tools):
            return False
        if decision.status not in {
            DecisionStatus.BLOCKED,
            DecisionStatus.COMPLETE,
            DecisionStatus.CONTINUE,
        }:
            return False
        if decision.status is DecisionStatus.CONTINUE and (
            decision.tool_name or decision.step_id
        ):
            return False
        return not any(
            item.get("kind") == "tool"
            and item.get("ok") is True
            and item.get("tool") == "read_file"
            and AgentLoop._is_source_path(
                str((item.get("result") or {}).get("path") or "")
            )
            for item in snapshot.observations
            if isinstance(item.get("result"), Mapping)
        )

    def _required_skill_discovery(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        tools: Any,
    ) -> WorkDecision | None:
        """Load one recommended Skill before extended tool use.

        The analyzer's recommendation is workflow guidance, never authority. The
        load still travels through the governed discovery tools, and a failed
        load is not retried automatically.
        """

        if decision.status not in {
            DecisionStatus.CONTINUE,
            DecisionStatus.BLOCKED,
            DecisionStatus.COMPLETE,
        }:
            return None
        candidates = tuple(
            str(item)
            for item in snapshot.analysis.candidate_skills
            if str(item) and str(item) not in snapshot.loaded_skills
        )
        if not candidates or not snapshot.loaded_tools:
            return None
        known = self.harness._tool_names(tools)
        if not {"catalog_expand", "skill_load"}.issubset(known):
            return None
        candidate = candidates[0]
        if "skill_load" not in snapshot.loaded_tools:
            if (
                decision.tool_name == "catalog_expand"
                and str(decision.tool_arguments.get("category") or "") == "skill"
            ):
                return None
            skill_category_digest = self._arguments_digest({"category": "skill"})
            if self._action_was_observed(
                snapshot, "catalog_expand", skill_category_digest
            ):
                return None
            return WorkDecision(
                status=DecisionStatus.CONTINUE,
                summary="Discover the recommended Skill before extended tool use",
                next_action="Load the governed Skill catalog",
                confidence="high",
                tool_name="catalog_expand",
                tool_arguments={"category": "skill"},
            )
        if (
            decision.tool_name == "skill_load"
            and str(decision.tool_arguments.get("skill_id") or "") == candidate
        ):
            return None
        load_digest = self._arguments_digest({"skill_id": candidate})
        if self._action_was_observed(snapshot, "skill_load", load_digest):
            return None
        return WorkDecision(
            status=DecisionStatus.CONTINUE,
            summary="Load the recommended Skill before extended tool use",
            next_action=f"Load Skill {candidate}",
            confidence="high",
            tool_name="skill_load",
            tool_arguments={"skill_id": candidate},
        )

    @staticmethod
    def _action_was_observed(
        snapshot: WorkSnapshot, tool_name: str, arguments_digest: str
    ) -> bool:
        return any(
            item.get("kind") == "tool"
            and item.get("tool") == tool_name
            and item.get("arguments_digest") == arguments_digest
            for item in snapshot.observations
        )

    @staticmethod
    def _latest_search_match(snapshot: WorkSnapshot) -> tuple[str, int] | None:
        for item in reversed(snapshot.observations):
            if item.get("tool") != "search_workspace" or item.get("ok") is not True:
                continue
            result = item.get("result")
            if not isinstance(result, Mapping):
                continue
            matches = [
                match
                for match in result.get("matches") or ()
                if isinstance(match, Mapping) and match.get("path")
            ]
            if not matches:
                continue
            path_counts: dict[str, int] = {}
            for match in matches:
                path = str(match["path"])
                path_counts[path] = path_counts.get(path, 0) + 1
            ranked = sorted(
                enumerate(matches),
                key=lambda indexed: (
                    AgentLoop._source_path_rank(str(indexed[1]["path"])),
                    -path_counts[str(indexed[1]["path"])],
                    indexed[0],
                ),
            )
            match = ranked[0][1]
            return str(match["path"]), max(1, int(match.get("line") or 1))
        return None

    @staticmethod
    def _is_source_path(path: str) -> bool:
        return AgentLoop._source_path_rank(path) < 3

    @staticmethod
    def _source_path_rank(path: str) -> int:
        normalized = str(path or "").replace("\\", "/").lstrip("./").casefold()
        parts = tuple(part for part in normalized.split("/") if part)
        if not parts or any(
            part in {".venv", "venv", "site-packages", "node_modules"} for part in parts
        ):
            return 4
        if parts[0] in {"src", "lib", "app", "crates"}:
            return 0
        if parts[0] in {"tests", "test"}:
            return 1
        if parts[0] in {"docs", "doc"} or parts[-1] in {
            "readme.md",
            "changelog.md",
            "changes.rst",
        }:
            return 3
        return 2

    @staticmethod
    def _workspace_search_query(objective: str) -> str:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_.]{2,}", str(objective or ""))
        underscored = [item.strip(".") for item in tokens if "_" in item]
        if underscored:
            return underscored[-1]
        dotted = [item.strip(".") for item in tokens if "." in item]
        if dotted:
            return dotted[-1].rsplit(".", 1)[-1]
        return max(tokens, key=len, default="source")

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
        tool_call_id = ""
        effect_class, capability_id = self._tool_effect(tools, decision.tool_name)
        snapshot.pending_action = {
            "tool": decision.tool_name,
            "step_id": step_id,
            "phase": decision.phase,
            "action_source": decision.action_source,
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
                arguments = dict(decision.tool_arguments)
                if decision.tool_name == "shell_start":
                    arguments.update(
                        {
                            "_work_id": snapshot.run_id,
                            "_tool_call_id": str(
                                getattr(_request, "invocation_id", "") or ""
                            ),
                            "_action_sequence": snapshot.action_sequence + 1,
                        }
                    )
                value = execute(decision.tool_name, arguments)
                captured["result"] = value
                return value

            invocation = self.harness.agent_runtime.invoke_tool(
                agent_run_id,
                tool_id=decision.tool_name,
                capability_id=decision.tool_name,
                parameters=dict(decision.tool_arguments),
                handler=invoke,
            )
            tool_call_id = invocation.invocation_id
            invocation_status = invocation.status.value
            result = captured.get("result")
            if result is None:
                result = {
                    "ok": False,
                    "error": invocation.message or "tool invocation failed",
                    "error_code": invocation.error_code,
                }

        normalized = self._result_mapping(result)
        self._bind_change_records(normalized, snapshot.run_id, tool_call_id)
        ok = invocation_status == "completed" and self._result_ok(normalized)
        if decision.tool_name == "web_fetch" and not ok:
            failure_class, retryable, failure_code = self._classify_web_failure(
                normalized
            )
            normalized.update(
                {
                    "failure_class": failure_class,
                    "retryable": retryable,
                    "failure_code": failure_code,
                    "resource_key": self._web_resource_key(decision.tool_arguments),
                }
            )
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
            "arguments_digest": self._arguments_digest(decision.tool_arguments),
            "result": normalized,
            "observed_at": work_timestamp(),
        }
        snapshot.observations.append(observation)
        snapshot.observations[:] = snapshot.observations[-50:]
        self._collect_artifacts(snapshot, normalized)
        self._record_task_result(
            snapshot,
            step_id,
            ok,
            normalized,
            effect_class=effect_class,
        )
        if (
            decision.tool_name in {"web_search", "web_fetch"}
            and not ok
            and str(normalized.get("error_code") or "") == "NOUS_APPROVAL_REQUIRED"
            and str(normalized.get("approval_request_id") or "")
        ):
            reason = str(normalized.get("error") or "network approval required")
            snapshot.pending_action.update(
                {
                    "arguments": dict(decision.tool_arguments),
                    "approval_request_id": str(
                        normalized.get("approval_request_id") or ""
                    ),
                    "proposal_hash": str(normalized.get("proposal_hash") or ""),
                    "recovery_policy": "approval_then_retry",
                }
            )
            snapshot.goal.wait_for_user(reason)
            snapshot.state = RunState.WAITING_FOR_APPROVAL
            snapshot.error = ""
            snapshot.reanalysis_reason = reason
            self.harness.checkpoint_agent(snapshot, resume=False)
            self.harness.persist_progress(
                snapshot,
                "work.waiting_approval",
                {
                    "summary": reason,
                    "action": "Approve the exact bound network request",
                    "tool": decision.tool_name,
                    "approval_request_id": str(
                        normalized.get("approval_request_id") or ""
                    ),
                    "proposal_hash": str(normalized.get("proposal_hash") or ""),
                    "arguments_digest": self._arguments_digest(decision.tool_arguments),
                },
            )
            return
        if self._effect_outcome_requires_recovery(effect_class, normalized):
            reason = (
                f"tool {decision.tool_name} has an uncertain effect outcome; "
                "Kernel or manual recovery evidence is required"
            )
            snapshot.goal.block(reason)
            snapshot.state = RunState.RECOVERY_REQUIRED
            snapshot.error = str(normalized.get("error") or reason)
            snapshot.reanalysis_reason = reason
            self.harness.persist_progress(
                snapshot,
                "work.recovery.required",
                {
                    "reason": reason,
                    "pending_action": dict(snapshot.pending_action),
                    "result": normalized,
                    "automatic_replay": False,
                },
            )
            return
        snapshot.pending_action.clear()
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
    def _effect_outcome_requires_recovery(
        effect_class: str,
        result: Mapping[str, Any],
    ) -> bool:
        """Keep uncertain side effects pending until durable evidence resolves them."""

        if effect_class not in {"write", "execute", "network"}:
            return False
        state = (
            str(
                result.get("state")
                or result.get("status")
                or result.get("outcome")
                or ""
            )
            .strip()
            .upper()
        )
        return bool(result.get("recovery_required")) or state in {
            "RECOVERY_REQUIRED",
            "UNKNOWN",
            "LOST",
        }

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

    @classmethod
    def _successful_read_action(
        cls,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        tools: Any,
    ) -> Mapping[str, Any] | None:
        if not decision.tool_name:
            return None
        if decision.tool_name in _VOLATILE_OBSERVATION_TOOLS:
            # These reads observe a live process and may legitimately change while
            # their arguments remain identical. The bounded Work iteration budget
            # still prevents an unbounded polling loop.
            return None
        effect_class, _ = cls._tool_effect(tools, decision.tool_name)
        if effect_class not in {"none", "read"}:
            return None
        arguments_digest = cls._arguments_digest(decision.tool_arguments)
        plan_revision = snapshot.plan.revision if snapshot.plan else 0
        for observation in reversed(snapshot.observations):
            if (
                observation.get("kind") == "tool"
                and observation.get("ok") is True
                and observation.get("tool") == decision.tool_name
                and int(observation.get("plan_revision") or 0) == plan_revision
                and observation.get("arguments_digest") == arguments_digest
            ):
                return observation
        return None

    @classmethod
    def _covered_file_read(
        cls,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> Mapping[str, Any] | None:
        """Return current-revision evidence that covers a requested file range."""

        if decision.tool_name != "read_file":
            return None
        path = cls._normalize_workspace_path(decision.tool_arguments.get("path"))
        if not path:
            return None
        requested_start = max(1, int(decision.tool_arguments.get("start_line") or 1))
        raw_end = decision.tool_arguments.get("end_line")
        requested_end = max(requested_start, int(raw_end)) if raw_end else None
        plan_revision = snapshot.plan.revision if snapshot.plan else 0
        latest_mutation = cls._latest_file_mutation(snapshot, path, plan_revision)
        arguments_digest = cls._arguments_digest(decision.tool_arguments)
        current_digest = ""
        for observation in reversed(snapshot.observations):
            result = observation.get("result")
            if (
                observation.get("kind") == "tool"
                and observation.get("ok") is True
                and observation.get("tool") == "read_file"
                and int(observation.get("plan_revision") or 0) == plan_revision
                and int(observation.get("action_sequence") or 0) > latest_mutation
                and isinstance(result, Mapping)
                and cls._normalize_workspace_path(result.get("path")) == path
            ):
                current_digest = str(result.get("sha256") or "")
                break
        for observation in reversed(snapshot.observations):
            if (
                observation.get("kind") != "tool"
                or observation.get("ok") is not True
                or observation.get("tool") != "read_file"
                or int(observation.get("plan_revision") or 0) != plan_revision
                or int(observation.get("action_sequence") or 0) <= latest_mutation
            ):
                continue
            result = observation.get("result")
            if not isinstance(result, Mapping):
                continue
            if cls._normalize_workspace_path(result.get("path")) != path:
                continue
            if current_digest and str(result.get("sha256") or "") != current_digest:
                continue
            covered_start = max(1, int(result.get("start_line") or 1))
            covered_end = max(
                covered_start, int(result.get("end_line") or covered_start)
            )
            exact = observation.get("arguments_digest") == arguments_digest
            range_covered = (
                requested_end is not None
                and covered_start <= requested_start
                and covered_end >= requested_end
            )
            if exact or range_covered:
                return {
                    "observation": observation,
                    "path": path,
                    "requested_start": requested_start,
                    "requested_end": requested_end,
                    "covered_start": covered_start,
                    "covered_end": covered_end,
                    "sha256": str(result.get("sha256") or ""),
                }
        return None

    def _record_covered_read(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        covered: Mapping[str, Any],
    ) -> None:
        reused = covered["observation"]
        snapshot.reanalysis_reason = (
            "requested source range is already covered by current-revision evidence; "
            "reuse it and transition to patch_file or collect genuinely new evidence"
        )
        result = {
            "ok": True,
            "already_covered": True,
            "new_evidence": False,
            "path": covered["path"],
            "requested_range": [
                covered["requested_start"],
                covered["requested_end"],
            ],
            "covered_range": [covered["covered_start"], covered["covered_end"]],
            "sha256": covered["sha256"],
            "reused_action_sequence": int(reused.get("action_sequence") or 0),
            "progress_delta": "reuse_evidence_then_act",
        }
        snapshot.observations.append(
            {
                "kind": "evidence_reuse",
                "tool": "read_file",
                "step_id": decision.step_id,
                "ok": True,
                "action_sequence": snapshot.action_sequence,
                "plan_revision": snapshot.plan.revision if snapshot.plan else 0,
                "arguments_digest": self._arguments_digest(decision.tool_arguments),
                "result": result,
                "observed_at": work_timestamp(),
            }
        )
        snapshot.observations[:] = snapshot.observations[-50:]
        self.harness.persist_progress(
            snapshot,
            "work.evidence.reused",
            {"tool": "read_file", **result},
        )

    @classmethod
    def _latest_file_mutation(
        cls,
        snapshot: WorkSnapshot,
        path: str,
        plan_revision: int,
    ) -> int:
        latest = 0
        for observation in snapshot.observations:
            if (
                observation.get("kind") != "tool"
                or observation.get("ok") is not True
                or int(observation.get("plan_revision") or 0) != plan_revision
            ):
                continue
            for changed_path in cls._changed_paths(observation.get("result")):
                if cls._normalize_workspace_path(changed_path) == path:
                    latest = max(latest, int(observation.get("action_sequence") or 0))
        return latest

    @staticmethod
    def _changed_paths(result: Any) -> tuple[str, ...]:
        if not isinstance(result, Mapping):
            return ()
        if result.get("changed") is False:
            return ()
        paths: list[str] = []

        def collect(change: Any) -> None:
            if not isinstance(change, Mapping) or change.get("changed") is False:
                return
            before = str(change.get("before_digest") or "")
            after = str(change.get("after_digest") or "")
            if before and after and before == after:
                return
            if change.get("path"):
                paths.append(str(change["path"]))

        collect(result.get("change"))
        for change in result.get("changes") or ():
            collect(change)
        for item in result.get("files") or ():
            if isinstance(item, Mapping):
                collect(item.get("change"))
        return tuple(paths)

    @staticmethod
    def _normalize_workspace_path(value: Any) -> str:
        path = str(value or "").replace("\\", "/").strip()
        while path.startswith("./"):
            path = path[2:]
        return path.casefold()

    @staticmethod
    def _awaiting_action_transition(snapshot: WorkSnapshot) -> bool:
        plan_revision = snapshot.plan.revision if snapshot.plan else 0
        for observation in reversed(snapshot.observations):
            if int(observation.get("plan_revision") or 0) != plan_revision:
                continue
            if observation.get("kind") == "evidence_reuse":
                return True
            if observation.get("kind") == "tool" and observation.get("ok") is True:
                return False
        return False

    @staticmethod
    def _failed_patch_recovery_read(
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> bool:
        """Allow one fresh source read after a failed exact-context patch."""

        if decision.tool_name != "read_file":
            return False
        plan_revision = snapshot.plan.revision if snapshot.plan else 0
        for observation in reversed(snapshot.observations):
            if (
                observation.get("kind") != "tool"
                or int(observation.get("plan_revision") or 0) != plan_revision
            ):
                continue
            if observation.get("tool") == "read_file" and observation.get("ok") is True:
                return False
            if observation.get("tool") == "patch_file":
                result = observation.get("result")
                error = (
                    str(result.get("error") or "")
                    if isinstance(result, Mapping)
                    else ""
                )
                return (
                    observation.get("ok") is False
                    and "context must match exactly once" in error.casefold()
                )
        return False

    @classmethod
    def _decision_can_add_evidence(
        cls,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        tools: Any,
    ) -> bool:
        if not decision.tool_name:
            return False
        effect_class, _ = cls._tool_effect(tools, decision.tool_name)
        if effect_class not in {"none", "read"}:
            return False
        digest = cls._arguments_digest(decision.tool_arguments)
        plan_revision = snapshot.plan.revision if snapshot.plan else 0
        return not any(
            item.get("kind") == "tool"
            and item.get("ok") is True
            and item.get("tool") == decision.tool_name
            and item.get("arguments_digest") == digest
            and int(item.get("plan_revision") or 0) == plan_revision
            for item in snapshot.observations
        )

    def _block_action_transition_stall(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> WorkSnapshot:
        code = "ACTION_TRANSITION_STALL"
        reason = (
            f"{code}: sufficient current-revision evidence was reused, but the "
            "next decision produced neither patch_file nor new evidence"
        )
        snapshot.goal.block(reason)
        snapshot.state = RunState.BLOCKED
        snapshot.reanalysis_reason = reason
        self.harness.checkpoint_agent(snapshot, resume=False)
        return self.harness.persist_progress(
            snapshot,
            "work.blocked",
            {
                "reason": reason,
                "reason_code": code,
                "tool": decision.tool_name,
                "arguments_digest": self._arguments_digest(decision.tool_arguments),
            },
        )

    @classmethod
    def _web_retry_block(
        cls,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
    ) -> Mapping[str, Any] | None:
        if (
            decision.status is not DecisionStatus.CONTINUE
            or decision.tool_name != "web_fetch"
        ):
            return None
        resource_key = cls._web_resource_key(decision.tool_arguments)
        failures: list[Mapping[str, Any]] = []
        for observation in snapshot.observations:
            if observation.get("tool") != "web_fetch" or observation.get("ok") is True:
                continue
            result = observation.get("result")
            if (
                not isinstance(result, Mapping)
                or result.get("resource_key") != resource_key
            ):
                continue
            failures.append(result)
        terminal = next(
            (
                item
                for item in reversed(failures)
                if item.get("failure_class") in {"non_retryable", "unknown"}
            ),
            None,
        )
        if terminal is not None:
            return {
                "reason_code": (
                    "NON_RETRYABLE_URL_FAILURE"
                    if terminal.get("failure_class") == "non_retryable"
                    else "UNCLASSIFIED_URL_FAILURE"
                ),
                "resource_key": resource_key,
                "attempts": len(failures),
            }
        retryable = sum(item.get("failure_class") == "retryable" for item in failures)
        if retryable >= _MAX_URL_FAILURE_ATTEMPTS:
            return {
                "reason_code": "URL_RETRY_BUDGET_EXHAUSTED",
                "resource_key": resource_key,
                "attempts": retryable,
            }
        return None

    def _block_web_retry(
        self,
        snapshot: WorkSnapshot,
        decision: WorkDecision,
        block: Mapping[str, Any],
    ) -> WorkSnapshot:
        code = str(block["reason_code"])
        reason = f"{code}: governed URL fetch was not reissued"
        snapshot.goal.block(reason)
        snapshot.state = RunState.BLOCKED
        snapshot.reanalysis_reason = reason
        self.harness.checkpoint_agent(snapshot, resume=False)
        return self.harness.persist_progress(
            snapshot,
            "work.blocked",
            {"reason": reason, **dict(block), "tool": decision.tool_name},
        )

    @staticmethod
    def _web_resource_key(arguments: Mapping[str, Any]) -> str:
        url = str(arguments.get("url") or "").strip()
        return "sha256:" + hashlib.sha256(url.encode("utf-8")).hexdigest()

    @staticmethod
    def _classify_web_failure(
        result: Mapping[str, Any],
    ) -> tuple[str, bool, str]:
        code = str(result.get("error_code") or result.get("failure_code") or "")
        error = str(result.get("error") or result.get("error_message") or "")
        if not code:
            match = re.search(r"NETWORK_[A-Z_]+", error.upper())
            code = match.group(0) if match else "WEB_REQUEST_FAILED"
        if code in _RETRYABLE_WEB_FAILURES:
            return "retryable", True, code
        if code in _NON_RETRYABLE_WEB_FAILURES:
            return "non_retryable", False, code
        lowered = error.casefold()
        if code == "NETWORK_HTTP_STATUS":
            match = re.search(r"HTTP\s+(\d{3})", error.upper())
            status = int(match.group(1)) if match else 0
            if status in {408, 425, 429, 500, 502, 503, 504}:
                return "retryable", True, code
            return "non_retryable", False, code
        if any(
            marker in lowered
            for marker in (
                "timed out",
                "timeout",
                "temporar",
                "connection reset",
                "reset the connection",
                "remote peer reset",
                "connection aborted",
                "server disconnected",
            )
        ):
            return "retryable", True, code
        if any(
            marker in lowered
            for marker in (
                "invalid url",
                "malformed",
                "not allowed",
                "blocked",
                "certificate",
                "credential",
            )
        ):
            return "non_retryable", False, code
        return "unknown", False, code

    @staticmethod
    def _bind_change_records(
        result: dict[str, Any],
        work_id: str,
        tool_call_id: str,
    ) -> None:
        def bind(value: Any) -> Any:
            if not isinstance(value, Mapping):
                return value
            change = dict(value)
            change["work_id"] = str(change.get("work_id") or work_id)
            change["tool_call_id"] = str(change.get("tool_call_id") or tool_call_id)
            return change

        if isinstance(result.get("change"), Mapping):
            result["change"] = bind(result["change"])
        if isinstance(result.get("changes"), list):
            result["changes"] = [bind(item) for item in result["changes"]]
        if isinstance(result.get("files"), list):
            files = []
            for item in result["files"]:
                file_result = dict(item) if isinstance(item, Mapping) else item
                if isinstance(file_result, dict) and isinstance(
                    file_result.get("change"), Mapping
                ):
                    file_result["change"] = bind(file_result["change"])
                files.append(file_result)
            result["files"] = files

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
        *,
        effect_class: str = "unknown",
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
        if ok and task.capability_id == "coding" and effect_class in {"none", "read"}:
            task.status = TaskStatus.RUNNING
        else:
            task.status = TaskStatus.COMPLETED if ok else TaskStatus.FAILED
        task.result = dict(result)
        task.error = "" if ok else str(result.get("error") or "tool failed")
        task.completed_at = work_timestamp()

    @staticmethod
    def _reconcile_plan_progress(snapshot: WorkSnapshot) -> None:
        if snapshot.plan is None:
            return
        revision = snapshot.plan.revision
        current = [
            item
            for item in snapshot.observations
            if int(item.get("plan_revision") or revision) == revision
        ]
        source_evidence = any(
            item.get("kind") == "tool"
            and item.get("tool") == "read_file"
            and item.get("ok") is True
            and isinstance(item.get("result"), Mapping)
            and AgentLoop._is_source_path(
                str((item.get("result") or {}).get("path") or "")
            )
            for item in current
        )
        web_evidence = any(
            item.get("kind") == "tool"
            and item.get("tool") in {"web_fetch", "web_search"}
            and item.get("ok") is True
            for item in current
        )
        evidence_sufficient = source_evidence and (
            not snapshot.analysis.needs_web or web_evidence
        )
        workspace_changed = any(
            item.get("kind") == "tool"
            and item.get("ok") is True
            and AgentLoop._changed_paths(item.get("result"))
            for item in current
        )
        for task in snapshot.plan.tasks:
            if task.task_id == "analyze" or task.task_id == "verify":
                continue
            if task.capability_id == "reasoning" and evidence_sufficient:
                task.status = TaskStatus.COMPLETED
                task.result = {"progress_fact": "evidence_sufficient"}
                task.error = ""
            elif task.capability_id == "coding":
                if workspace_changed:
                    task.status = TaskStatus.COMPLETED
                    task.result = {"progress_fact": "workspace_changed"}
                    task.error = ""
                elif task.status is TaskStatus.COMPLETED:
                    task.status = TaskStatus.RUNNING
                    task.result = {"progress_fact": "awaiting_workspace_change"}

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
        session_artifacts = result.get("artifacts")
        if isinstance(session_artifacts, Mapping):
            for artifact_ref in session_artifacts.values():
                value = str(artifact_ref or "")
                if value and value not in snapshot.artifacts:
                    snapshot.artifacts.append(value)
        for item in values:
            if not isinstance(item, Mapping):
                continue
            artifact_id = str(item.get("artifact_id") or item.get("artifact_ref") or "")
            if artifact_id and artifact_id not in snapshot.artifacts:
                snapshot.artifacts.append(artifact_id)


__all__ = ["AgentLoop", "Deliberator", "Verifier"]

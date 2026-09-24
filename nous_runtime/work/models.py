"""Durable contracts for the Work Harness."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from nous_runtime.events import RunState
from nous_runtime.intelligence.task import TaskAnalysis
from nous_runtime.planner import Goal, Plan


def work_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class DecisionStatus(str, Enum):
    CONTINUE = "continue"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    REQUEST_APPROVAL = "request_approval"
    VERIFY = "verify"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAIL = "fail"


@dataclass(frozen=True)
class PlanStepDraft:
    description: str
    capability_id: str = ""
    step_id: str = ""
    depends_on: tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "capability_id": self.capability_id,
            "step_id": self.step_id,
            "depends_on": list(self.depends_on),
            "params": dict(self.params),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlanStepDraft":
        return cls(
            description=str(data.get("description") or ""),
            capability_id=str(data.get("capability_id") or ""),
            step_id=str(data.get("step_id") or ""),
            depends_on=tuple(str(item) for item in data.get("depends_on") or ()),
            params=dict(data.get("params") or {}),
        )


@dataclass(frozen=True)
class WorkDecision:
    """A model-consumable decision summary, never raw model reasoning."""

    status: DecisionStatus
    summary: str
    next_action: str = ""
    reason: str = ""
    confidence: str = "medium"
    tool_name: str = ""
    tool_arguments: Mapping[str, Any] = field(default_factory=dict)
    step_id: str = ""
    plan_revision_required: bool = False
    replacement_steps: tuple[PlanStepDraft, ...] = ()
    output: Any = None

    def __post_init__(self) -> None:
        if not str(self.summary or "").strip():
            raise ValueError("work decision summary is required")
        if self.confidence not in {"low", "medium", "high"}:
            raise ValueError("work decision confidence must be low, medium, or high")
        if self.status is DecisionStatus.CONTINUE and not (
            self.tool_name or self.next_action
        ):
            raise ValueError("continue decision requires a tool or next action")
        if self.plan_revision_required and not self.replacement_steps:
            raise ValueError("plan revision requires replacement steps")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "next_action": self.next_action,
            "reason": self.reason,
            "confidence": self.confidence,
            "tool_name": self.tool_name,
            "tool_arguments": dict(self.tool_arguments),
            "step_id": self.step_id,
            "plan_revision_required": self.plan_revision_required,
            "replacement_steps": [item.to_dict() for item in self.replacement_steps],
            "output": self.output,
        }

    @classmethod
    def from_value(cls, value: "WorkDecision | Mapping[str, Any]") -> "WorkDecision":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("work deliberator must return WorkDecision or a mapping")
        return cls(
            status=DecisionStatus(str(value.get("status") or "continue")),
            summary=str(value.get("summary") or ""),
            next_action=str(value.get("next_action") or ""),
            reason=str(value.get("reason") or ""),
            confidence=str(value.get("confidence") or "medium"),
            tool_name=str(value.get("tool_name") or ""),
            tool_arguments=dict(value.get("tool_arguments") or {}),
            step_id=str(value.get("step_id") or ""),
            plan_revision_required=bool(value.get("plan_revision_required")),
            replacement_steps=tuple(
                PlanStepDraft.from_dict(item)
                for item in value.get("replacement_steps") or ()
            ),
            output=value.get("output"),
        )


@dataclass
class WorkSnapshot:
    run_id: str
    goal: Goal
    state: RunState
    analysis: TaskAnalysis
    workspace_root: str
    conversation_id: str = ""
    plan: Plan | None = None
    current_step: str = ""
    last_decision: WorkDecision | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    loaded_tools: dict[str, dict[str, Any]] = field(default_factory=dict)
    loaded_skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_run_id: str = ""
    agent_checkpoint_id: str = ""
    last_checkpoint_id: str = ""
    checkpoint_sequence: int = 0
    action_sequence: int = 0
    reanalysis_reason: str = ""
    result: Any = None
    error: str = ""
    created_at: str = field(default_factory=work_timestamp)
    updated_at: str = field(default_factory=work_timestamp)

    @classmethod
    def create(
        cls,
        *,
        goal: Goal,
        analysis: TaskAnalysis,
        workspace_root: str,
        conversation_id: str = "",
        plan: Plan | None = None,
    ) -> "WorkSnapshot":
        return cls(
            run_id=f"work_{uuid.uuid4().hex}",
            goal=goal,
            state=RunState.RECEIVED,
            analysis=analysis,
            workspace_root=workspace_root,
            conversation_id=conversation_id,
            plan=plan,
        )

    @property
    def terminal(self) -> bool:
        return self.state in {
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.CANCELLED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal.to_dict(),
            "state": self.state.value,
            "analysis": self.analysis.to_dict(),
            "workspace_root": self.workspace_root,
            "conversation_id": self.conversation_id,
            "plan": self.plan.to_dict() if self.plan else None,
            "current_step": self.current_step,
            "last_decision": self.last_decision.to_dict()
            if self.last_decision
            else None,
            "observations": [dict(item) for item in self.observations],
            "artifacts": list(self.artifacts),
            "loaded_tools": {
                str(key): dict(value) for key, value in self.loaded_tools.items()
            },
            "loaded_skills": {
                str(key): dict(value) for key, value in self.loaded_skills.items()
            },
            "agent_run_id": self.agent_run_id,
            "agent_checkpoint_id": self.agent_checkpoint_id,
            "last_checkpoint_id": self.last_checkpoint_id,
            "checkpoint_sequence": self.checkpoint_sequence,
            "action_sequence": self.action_sequence,
            "reanalysis_reason": self.reanalysis_reason,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WorkSnapshot":
        raw_plan = data.get("plan")
        raw_decision = data.get("last_decision")
        return cls(
            run_id=str(data.get("run_id") or ""),
            goal=Goal.from_dict(dict(data.get("goal") or {})),
            state=RunState(str(data.get("state") or RunState.RECEIVED.value)),
            analysis=TaskAnalysis.from_dict(dict(data.get("analysis") or {})),
            workspace_root=str(data.get("workspace_root") or ""),
            conversation_id=str(data.get("conversation_id") or ""),
            plan=Plan.from_dict(dict(raw_plan))
            if isinstance(raw_plan, Mapping)
            else None,
            current_step=str(data.get("current_step") or ""),
            last_decision=(
                WorkDecision.from_value(raw_decision)
                if isinstance(raw_decision, Mapping)
                else None
            ),
            observations=[
                dict(item)
                for item in data.get("observations") or ()
                if isinstance(item, Mapping)
            ],
            artifacts=[str(item) for item in data.get("artifacts") or ()],
            loaded_tools={
                str(key): dict(value)
                for key, value in dict(data.get("loaded_tools") or {}).items()
                if isinstance(value, Mapping)
            },
            loaded_skills={
                str(key): dict(value)
                for key, value in dict(data.get("loaded_skills") or {}).items()
                if isinstance(value, Mapping)
            },
            agent_run_id=str(data.get("agent_run_id") or ""),
            agent_checkpoint_id=str(data.get("agent_checkpoint_id") or ""),
            last_checkpoint_id=str(data.get("last_checkpoint_id") or ""),
            checkpoint_sequence=max(0, int(data.get("checkpoint_sequence") or 0)),
            action_sequence=max(0, int(data.get("action_sequence") or 0)),
            reanalysis_reason=str(data.get("reanalysis_reason") or ""),
            result=data.get("result"),
            error=str(data.get("error") or ""),
            created_at=str(data.get("created_at") or work_timestamp()),
            updated_at=str(data.get("updated_at") or work_timestamp()),
        )


@dataclass(frozen=True)
class WorkContext:
    run_id: str
    goal: Mapping[str, Any]
    assessment: Mapping[str, Any]
    plan: Mapping[str, Any] | None
    workspace: Mapping[str, Any]
    conversation: Mapping[str, Any]
    recent_observations: tuple[Mapping[str, Any], ...]
    recent_events: tuple[Mapping[str, Any], ...]
    loaded_tools: tuple[Mapping[str, Any], ...] = ()
    loaded_skills: tuple[Mapping[str, Any], ...] = ()
    reanalysis_reason: str = ""
    recovering: bool = False
    budget: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": dict(self.goal),
            "assessment": dict(self.assessment),
            "plan": dict(self.plan) if self.plan else None,
            "workspace": dict(self.workspace),
            "conversation": dict(self.conversation),
            "recent_observations": [dict(item) for item in self.recent_observations],
            "recent_events": [dict(item) for item in self.recent_events],
            "loaded_tools": [dict(item) for item in self.loaded_tools],
            "loaded_skills": [dict(item) for item in self.loaded_skills],
            "reanalysis_reason": self.reanalysis_reason,
            "recovering": self.recovering,
            "budget": dict(self.budget),
        }


__all__ = [
    "DecisionStatus",
    "PlanStepDraft",
    "WorkContext",
    "WorkDecision",
    "WorkSnapshot",
    "work_timestamp",
]

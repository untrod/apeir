"""Task analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskAnalysis:
    """A lightweight, explainable description of a Runtime task."""

    task_id: str
    task_type: str
    complexity: str
    required_capabilities: tuple[str, ...] = ()
    constraints: dict[str, Any] = field(default_factory=dict)
    needs_tools: bool = False
    needs_plan: bool = False
    needs_web: bool = False
    needs_workspace: bool = False
    needs_environment: bool = False
    candidate_skills: tuple[str, ...] = ()
    missing_context: tuple[str, ...] = ()
    risk_class: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "complexity": self.complexity,
            "required_capabilities": list(self.required_capabilities),
            "constraints": dict(self.constraints),
            "needs_tools": self.needs_tools,
            "needs_plan": self.needs_plan,
            "needs_web": self.needs_web,
            "needs_workspace": self.needs_workspace,
            "needs_environment": self.needs_environment,
            "candidate_skills": list(self.candidate_skills),
            "missing_context": list(self.missing_context),
            "risk_class": self.risk_class,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskAnalysis":
        return cls(
            task_id=str(data.get("task_id") or ""),
            task_type=str(data.get("task_type") or "general"),
            complexity=str(data.get("complexity") or "low"),
            required_capabilities=tuple(
                str(item) for item in data.get("required_capabilities") or ()
            ),
            constraints=dict(data.get("constraints") or {}),
            needs_tools=bool(data.get("needs_tools")),
            needs_plan=bool(data.get("needs_plan")),
            needs_web=bool(data.get("needs_web")),
            needs_workspace=bool(data.get("needs_workspace")),
            needs_environment=bool(data.get("needs_environment")),
            candidate_skills=tuple(
                str(item) for item in data.get("candidate_skills") or ()
            ),
            missing_context=tuple(
                str(item) for item in data.get("missing_context") or ()
            ),
            risk_class=str(data.get("risk_class") or "low"),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = ["TaskAnalysis"]

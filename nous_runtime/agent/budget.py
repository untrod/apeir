# -*- coding: utf-8 -*-
"""Agent budget helpers."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Mapping

from nous_runtime.agent.errors import AgentBudgetError
from nous_runtime.agent.models import AgentBudget


def require_budget(
    budget: AgentBudget,
    *,
    cost_usd: float = 0.0,
    tokens: int = 0,
    runtime_ms: int = 0,
    invocations: int = 1,
) -> None:
    if not budget.allows(
        cost_usd=cost_usd,
        tokens=tokens,
        runtime_ms=runtime_ms,
        invocations=invocations,
    ):
        raise AgentBudgetError("agent budget exceeded")


@dataclass(frozen=True)
class AgentBudgetUsage:
    cost_usd: float = 0.0
    tokens: int = 0
    runtime_ms: int = 0
    invocations: int = 0
    tool_invocations: int = 0
    model_invocations: int = 0
    checkpoints: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_usd": self.cost_usd,
            "tokens": self.tokens,
            "runtime_ms": self.runtime_ms,
            "invocations": self.invocations,
            "tool_invocations": self.tool_invocations,
            "model_invocations": self.model_invocations,
            "checkpoints": self.checkpoints,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "AgentBudgetUsage":
        data = data or {}
        return cls(
            cost_usd=float(data.get("cost_usd") or 0.0),
            tokens=int(data.get("tokens") or 0),
            runtime_ms=int(data.get("runtime_ms") or 0),
            invocations=int(data.get("invocations") or 0),
            tool_invocations=int(data.get("tool_invocations") or 0),
            model_invocations=int(data.get("model_invocations") or 0),
            checkpoints=int(data.get("checkpoints") or 0),
        )


class AgentBudgetLedger:
    """Thread-safe cumulative budget accounting for one Agent run."""

    def __init__(
        self,
        budget: AgentBudget,
        usage: AgentBudgetUsage | None = None,
    ) -> None:
        self.budget = budget
        self._usage = usage or AgentBudgetUsage()
        self._lock = threading.RLock()

    @property
    def usage(self) -> AgentBudgetUsage:
        with self._lock:
            return self._usage

    def ensure(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        runtime_ms: int = 0,
        tool_invocations: int = 0,
        model_invocations: int = 0,
        checkpoints: int = 0,
    ) -> None:
        projected = self._project(
            cost_usd=cost_usd,
            tokens=tokens,
            runtime_ms=runtime_ms,
            tool_invocations=tool_invocations,
            model_invocations=model_invocations,
            checkpoints=checkpoints,
        )
        exceeded = self.exceeded_limits(projected)
        if exceeded:
            raise AgentBudgetError(
                "agent budget exceeded: " + ",".join(exceeded),
                context={"limits": exceeded},
            )

    def consume(self, **amounts: Any) -> AgentBudgetUsage:
        with self._lock:
            self.ensure(**amounts)
            self._usage = self._project(**amounts)
            return self._usage

    def exceeded_limits(
        self,
        usage: AgentBudgetUsage | None = None,
    ) -> tuple[str, ...]:
        usage = usage or self.usage
        checks = (
            ("cost_usd", self.budget.max_cost_usd, usage.cost_usd),
            ("tokens", self.budget.max_tokens, usage.tokens),
            ("runtime_ms", self.budget.max_runtime_ms, usage.runtime_ms),
            ("invocations", self.budget.max_invocations, usage.invocations),
            (
                "tool_invocations",
                self.budget.max_tool_invocations,
                usage.tool_invocations,
            ),
            (
                "model_invocations",
                self.budget.max_model_invocations,
                usage.model_invocations,
            ),
            ("checkpoints", self.budget.max_checkpoints, usage.checkpoints),
        )
        return tuple(
            name for name, limit, actual in checks if limit and actual > limit
        )

    def _project(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        runtime_ms: int = 0,
        tool_invocations: int = 0,
        model_invocations: int = 0,
        checkpoints: int = 0,
    ) -> AgentBudgetUsage:
        if (
            cost_usd < 0
            or tokens < 0
            or runtime_ms < 0
            or tool_invocations < 0
            or model_invocations < 0
            or checkpoints < 0
        ):
            raise AgentBudgetError("budget usage increments must be non-negative")
        usage = self._usage
        return AgentBudgetUsage(
            cost_usd=usage.cost_usd + float(cost_usd),
            tokens=usage.tokens + int(tokens),
            runtime_ms=usage.runtime_ms + int(runtime_ms),
            invocations=usage.invocations
            + int(tool_invocations)
            + int(model_invocations),
            tool_invocations=usage.tool_invocations + int(tool_invocations),
            model_invocations=usage.model_invocations + int(model_invocations),
            checkpoints=usage.checkpoints + int(checkpoints),
        )


__all__ = [
    "AgentBudgetError",
    "AgentBudgetLedger",
    "AgentBudgetUsage",
    "require_budget",
]

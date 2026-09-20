# -*- coding: utf-8 -*-
"""
Task Budget Enforcement for Nous Runtime.

Implements §17.4 of the master plan. Enforces per-task resource limits
during execution: max cost, max tokens, max model calls, max agents,
max execution time, max retries, max concurrency.

When limits are exceeded, the enforcer can:
- Degrade (switch to cheaper model)
- Pause (wait for user approval to continue)
- Terminate (stop the task)
- Request budget increase (escalate to user)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from nous_runtime.kernel.error_codes import ErrorCode, NousResult
from nous_runtime.kernel.task import TaskBudget
from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.intelligence.budget")


class BudgetAction(str, Enum):
    """Action taken when a budget limit is exceeded."""
    DEGRADE = "degrade"          # Switch to cheaper model/node
    PAUSE = "pause"              # Pause and request user approval
    TERMINATE = "terminate"      # Stop the task
    NOTIFY = "notify"            # Warn but continue
    ESCALATE = "escalate"        # Request budget increase from user


@dataclass
class BudgetEvent:
    """Record of a budget-related event."""
    event_id: str = field(default_factory=lambda: make_id(prefix="budget"))
    task_id: str = ""
    limit_type: str = ""             # cost, tokens, model_calls, agents, time, retries
    limit_value: int = 0
    current_value: int = 0
    action_taken: BudgetAction = BudgetAction.NOTIFY
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BudgetEnforcer:
    """Enforces budget limits on running tasks.

    Monitors real-time resource consumption and takes action
    when limits are approached or exceeded.
    """

    # Thresholds as fraction of limit (0.0–1.0)
    WARN_THRESHOLD = 0.7    # Warn at 70%
    DEGRADE_THRESHOLD = 0.85  # Degrade at 85%
    HARD_THRESHOLD = 1.0    # Terminate at 100%

    def __init__(self,
                 on_degrade: Callable[[str, TaskBudget], None] | None = None,
                 on_pause: Callable[[str, str], None] | None = None,
                 on_terminate: Callable[[str, str], None] | None = None):
        self._on_degrade = on_degrade
        self._on_pause = on_pause
        self._on_terminate = on_terminate
        self._events: list[BudgetEvent] = []
        self._lock = threading.Lock()

    def check(self, task_id: str, budget: TaskBudget,
              operation_cost_cents: int = 0,
              operation_tokens: int = 0) -> NousResult[BudgetAction]:
        """Check if an operation would fit within the budget.

        Returns the action to take: proceed (None), degrade, pause, or terminate.
        """
        with self._lock:
            # Check each limit
            checks = [
                ("cost", budget.max_cost_cents, budget.cost_cents_spent + operation_cost_cents),
                ("tokens", budget.max_tokens, budget.tokens_spent + operation_tokens),
                ("model_calls", budget.max_model_calls, budget.model_calls_made + 1),
                ("agents", budget.max_agents, budget.agents_spawned + 1),
            ]

            for limit_type, limit, projected in checks:
                if limit <= 0:
                    continue  # Unlimited

                ratio = projected / limit

                if ratio >= self.HARD_THRESHOLD:
                    event = BudgetEvent(
                        task_id=task_id, limit_type=limit_type,
                        limit_value=limit, current_value=projected,
                        action_taken=BudgetAction.TERMINATE,
                    )
                    self._events.append(event)
                    if self._on_terminate:
                        self._on_terminate(task_id,
                                          f"{limit_type} limit exceeded: {projected}/{limit}")
                    return NousResult.err(ErrorCode.BUDGET_EXCEEDED,
                                          message=f"{limit_type} budget exceeded")

                elif ratio >= self.DEGRADE_THRESHOLD:
                    event = BudgetEvent(
                        task_id=task_id, limit_type=limit_type,
                        limit_value=limit, current_value=projected,
                        action_taken=BudgetAction.DEGRADE,
                    )
                    self._events.append(event)
                    if self._on_degrade:
                        self._on_degrade(task_id, budget)
                    return NousResult.ok(BudgetAction.DEGRADE)

                elif ratio >= self.WARN_THRESHOLD:
                    event = BudgetEvent(
                        task_id=task_id, limit_type=limit_type,
                        limit_value=limit, current_value=projected,
                        action_taken=BudgetAction.NOTIFY,
                    )
                    self._events.append(event)
                    log.warning("Budget warning: task=%s %s at %.0f%% (%d/%d)",
                                task_id, limit_type, ratio * 100, projected, limit)

        return NousResult.ok(None)  # None = proceed normally

    def record_cost(self, task_id: str, budget: TaskBudget,
                    cost_cents: int, tokens: int = 0) -> BudgetAction | None:
        """Record actual cost incurred and check limits."""
        budget.cost_cents_spent += cost_cents
        budget.tokens_spent += tokens
        budget.model_calls_made += 1

        result = self.check(task_id, budget,
                           operation_cost_cents=0,  # already added
                           operation_tokens=0)
        if result.ok:
            return result.value  # None or DEGRADE
        return BudgetAction.TERMINATE

    def check_time(self, task_id: str, budget: TaskBudget) -> NousResult[BudgetAction]:
        """Check if the task has exceeded its time budget."""
        if budget.max_execution_seconds <= 0:
            return NousResult.ok(None)  # Unlimited

        if not budget.started_at:
            return NousResult.ok(None)

        try:
            started = datetime.fromisoformat(budget.started_at)
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        except Exception:
            return NousResult.ok(None)

        ratio = elapsed / budget.max_execution_seconds

        if ratio >= self.HARD_THRESHOLD:
            event = BudgetEvent(
                task_id=task_id, limit_type="time",
                limit_value=budget.max_execution_seconds,
                current_value=int(elapsed),
                action_taken=BudgetAction.TERMINATE,
            )
            self._events.append(event)
            return NousResult.err(ErrorCode.BUDGET_EXCEEDED,
                                  message=f"Time budget exceeded: {int(elapsed)}s")

        elif ratio >= self.WARN_THRESHOLD:
            log.warning("Time budget warning: task=%s at %.0f%% (%ds/%ds)",
                        task_id, ratio * 100, int(elapsed), budget.max_execution_seconds)

        return NousResult.ok(None)

    def get_budget_status(self, budget: TaskBudget) -> dict[str, Any]:
        """Return human-readable budget status."""
        status = {
            "cost": {"limit": budget.max_cost_cents, "spent": budget.cost_cents_spent,
                     "pct": 0.0 if budget.max_cost_cents <= 0
                     else budget.cost_cents_spent / budget.max_cost_cents * 100},
            "tokens": {"limit": budget.max_tokens, "spent": budget.tokens_spent,
                       "pct": 0.0 if budget.max_tokens <= 0
                       else budget.tokens_spent / budget.max_tokens * 100},
            "model_calls": {"limit": budget.max_model_calls, "made": budget.model_calls_made,
                            "pct": 0.0 if budget.max_model_calls <= 0
                            else budget.model_calls_made / budget.max_model_calls * 100},
            "retries": {"limit": budget.max_retries, "used": budget.retries_used},
        }
        return status

    def get_events(self, task_id: str = "", limit: int = 50) -> list[BudgetEvent]:
        with self._lock:
            events = self._events
            if task_id:
                events = [e for e in events if e.task_id == task_id]
            return events[-limit:]

# -*- coding: utf-8 -*-
"""Rolling-Horizon Replanning — dynamically adjusts execution plans.

The scheduler does NOT fix all steps at task start. It periodically
reassesses: node health, model health, cost, deadline, progress,
failed branches, new information, verification feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReplanTrigger(str, Enum):
    NODE_OFFLINE = "node_offline"
    MODEL_FAILURE = "model_failure"
    COST_OVERRUN = "cost_overrun"
    DEADLINE_AT_RISK = "deadline_at_risk"
    BRANCH_FAILED = "branch_failed"
    NEW_INFORMATION = "new_information"
    VERIFICATION_FAILED = "verification_failed"
    HUMAN_INTERVENTION = "human_intervention"


@dataclass
class ReplanAction:
    """An action taken during replanning."""
    action_type: str = ""      # reschedule, reassign, terminate_branch, expand_branch, add_reviewer, reduce_verification, escalate, pause, rollback
    target_node: str = ""      # graph node ID
    reason: str = ""
    old_value: Any = None
    new_value: Any = None
    timestamp: float = 0.0


class Replanner:
    """Rolling-horizon replanner that adjusts execution dynamically."""

    def __init__(self) -> None:
        self._actions: list[ReplanAction] = []
        self._replan_count: int = 0

    def should_replan(self, trigger: ReplanTrigger, context: dict[str, Any]) -> bool:
        """Determine if replanning is needed."""
        if trigger in (ReplanTrigger.NODE_OFFLINE, ReplanTrigger.MODEL_FAILURE, ReplanTrigger.BRANCH_FAILED):
            return True
        if trigger == ReplanTrigger.COST_OVERRUN:
            return float(context.get("cost_ratio", 0) or 0) > 1.2
        if trigger == ReplanTrigger.DEADLINE_AT_RISK:
            return float(context.get("progress_pct", 0) or 0) < 50 and float(context.get("time_elapsed_pct", 0) or 0) > 70
        if trigger == ReplanTrigger.VERIFICATION_FAILED:
            return True
        if trigger == ReplanTrigger.NEW_INFORMATION:
            return bool(context.get("significant_change", False))
        return False

    def replan(
        self,
        trigger: ReplanTrigger,
        current_graph: Any,
        context: dict[str, Any],
    ) -> list[ReplanAction]:
        """Generate replanning actions based on trigger."""
        import time
        actions: list[ReplanAction] = []
        t = time.monotonic()

        if trigger == ReplanTrigger.NODE_OFFLINE:
            offline_node = str(context.get("node_id", ""))
            for nid in getattr(current_graph, "node_ids", lambda: [])():
                actions.append(ReplanAction(
                    action_type="reassign",
                    target_node=nid,
                    reason=f"Node {offline_node} went offline",
                    old_value=offline_node,
                    new_value=context.get("alternative_node", "any_available"),
                    timestamp=t,
                ))

        elif trigger == ReplanTrigger.MODEL_FAILURE:
            failed_model = str(context.get("model_id", ""))
            actions.append(ReplanAction(
                action_type="reassign",
                target_node="*",
                reason=f"Model {failed_model} failed",
                old_value=failed_model,
                new_value=context.get("fallback_model", "any_available"),
                timestamp=t,
            ))

        elif trigger == ReplanTrigger.BRANCH_FAILED:
            branch = str(context.get("branch_id", ""))
            actions.append(ReplanAction(
                action_type="terminate_branch",
                target_node=branch,
                reason="Branch execution failed",
                timestamp=t,
            ))
            # Optionally expand alternative
            if context.get("alternative_branch"):
                actions.append(ReplanAction(
                    action_type="expand_branch",
                    target_node=str(context["alternative_branch"]),
                    reason="Expanding speculative alternative",
                    timestamp=t,
                ))

        elif trigger == ReplanTrigger.VERIFICATION_FAILED:
            actions.append(ReplanAction(
                action_type="add_reviewer",
                target_node=str(context.get("failed_node", "")),
                reason="Verification failed, adding adversarial reviewer",
                timestamp=t,
            ))

        elif trigger == ReplanTrigger.COST_OVERRUN:
            actions.append(ReplanAction(
                action_type="reduce_verification",
                target_node="*",
                reason=f"Cost at {context.get('cost_ratio', 0):.0%} of budget",
                timestamp=t,
            ))

        self._actions.extend(actions)
        self._replan_count += 1
        return actions

    def history(self) -> list[ReplanAction]:
        return list(self._actions)

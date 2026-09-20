# -*- coding: utf-8 -*-
"""Shadow Mode — safe comparison of production vs. experimental policies.

Feature flag: NOUS_SHADOW_MODE=1 enables shadow execution.
Shadow decisions are computed but NEVER control real execution.
Output is recorded to ShadowComparisonStore for later analysis.

This is the default validation mode for Bandit, Pareto Router,
and all agent orchestration algorithms before Canary promotion.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

_log = logging.getLogger("nous.shadow")



# Feature flag


def is_shadow_enabled() -> bool:
    """Check if shadow mode is enabled via environment variable."""
    return os.environ.get("NOUS_SHADOW_MODE", "0") in ("1", "true", "yes", "on")



# Shadow policy protocol


class ShadowPolicy(Protocol):
    """A policy that can run in shadow mode alongside production."""

    name: str
    version: str

    def decide(
        self,
        task: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Produce a shadow decision. Never mutates real state."""
        ...



# Data models


@dataclass
class ShadowComparison:
    """A single shadow-vs-production comparison record."""
    comparison_id: str = ""
    task_id: str = ""
    created_at: str = ""

    # Production
    production_policy: str = ""
    production_decision: dict[str, Any] = field(default_factory=dict)

    # Shadow
    shadow_policy: str = ""
    shadow_policy_version: str = ""
    shadow_decision: dict[str, Any] = field(default_factory=dict)

    # Differences
    decision_difference: dict[str, Any] = field(default_factory=dict)
    predicted_outcomes: dict[str, Any] = field(default_factory=dict)
    actual_production_result: dict[str, Any] = field(default_factory=dict)

    # Evaluation
    estimated_regret: float = 0.0       # 0-1, higher = shadow would have been worse
    safety_violations: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)

    # Metadata
    session_id: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ShadowComparison":
        return cls(**{
            k: data.get(k, v.default if not isinstance(v.default, (list, dict)) else (
                list(v.default) if isinstance(v.default, list) else dict(v.default)
            ))
            for k, v in cls.__dataclass_fields__.items()
            if k in data
        })



# Shadow execution context


class ShadowExecutionContext:
    """Wraps real execution context for shadow policy evaluation.

    The shadow policy sees the same inputs as production but its
    decisions are recorded, not executed.
    """

    def __init__(self) -> None:
        self._store = ShadowComparisonStore()

    def evaluate(
        self,
        *,
        production_policy: str,
        production_decision: dict[str, Any],
        shadow_policy: ShadowPolicy,
        task: dict[str, Any],
        context: dict[str, Any],
        session_id: str = "",
        trace_id: str = "",
    ) -> ShadowComparison:
        """Run shadow policy and record comparison.

        Returns the comparison record. Does NOT execute the shadow decision.
        """
        # Compute shadow decision
        shadow_decision = shadow_policy.decide(task, context)

        # Compute differences
        diff = _diff_decisions(production_decision, shadow_decision)

        # Estimate regret and violations
        predicted = {
            "shadow_model": shadow_decision.get("model_id", ""),
            "shadow_node": shadow_decision.get("node_id", ""),
            "shadow_verify": shadow_decision.get("should_verify", False),
        }
        safety_violations = _check_safety_violations(shadow_decision, context)
        constraint_violations = _check_constraint_violations(shadow_decision, task)

        comparison = ShadowComparison(
            comparison_id=f"shadow_{uuid.uuid4().hex[:12]}",
            task_id=str(task.get("task_id", "")),
            created_at=_utc_now(),
            production_policy=production_policy,
            production_decision=dict(production_decision),
            shadow_policy=shadow_policy.name,
            shadow_policy_version=shadow_policy.version,
            shadow_decision=dict(shadow_decision),
            decision_difference=diff,
            predicted_outcomes=predicted,
            actual_production_result={},  # filled after task completes
            estimated_regret=_estimate_regret(production_decision, shadow_decision),
            safety_violations=safety_violations,
            constraint_violations=constraint_violations,
            session_id=session_id,
            trace_id=trace_id,
        )

        # Persist
        self._store.record(comparison)
        return comparison

    def record_actual_result(
        self,
        comparison_id: str,
        actual_result: dict[str, Any],
    ) -> None:
        """Update comparison with actual production outcome."""
        self._store.update_result(comparison_id, actual_result)

    def store(self) -> "ShadowComparisonStore":
        return self._store



# Shadow comparison store


class ShadowComparisonStore:
    """JSONL store for shadow-vs-production comparisons."""

    def __init__(self, workspace_root: str = "") -> None:
        ws = Path(workspace_root or os.path.expanduser("~/.nous"))
        self._dir = ws / "shadow"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "comparisons.jsonl"
        self._lock = threading.Lock()

    def record(self, comparison: ShadowComparison) -> None:
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(comparison.to_dict(), ensure_ascii=False) + "\n")

    def update_result(
        self,
        comparison_id: str,
        actual_result: dict[str, Any],
    ) -> bool:
        """Update a comparison with actual production outcome."""
        if not self._path.exists():
            return False

        with self._lock:
            lines = self._path.read_text(encoding="utf-8").splitlines()
            updated = []
            found = False
            for line in lines:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    updated.append(line)
                    continue
                if d.get("comparison_id") == comparison_id:
                    d["actual_production_result"] = actual_result
                    updated.append(json.dumps(d, ensure_ascii=False))
                    found = True
                else:
                    updated.append(line)
            if found:
                self._path.write_text("\n".join(updated) + "\n", encoding="utf-8")
            return found

    def query(
        self,
        *,
        shadow_policy: str = "",
        min_regret: float = -1.0,
        has_safety_violation: bool | None = None,
        limit: int = 100,
    ) -> list[ShadowComparison]:
        """Query shadow comparisons."""
        if not self._path.exists():
            return []

        results = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if shadow_policy and d.get("shadow_policy") != shadow_policy:
                continue
            if min_regret >= 0 and d.get("estimated_regret", 0) < min_regret:
                continue
            if has_safety_violation is not None:
                has = len(d.get("safety_violations", [])) > 0
                if has != has_safety_violation:
                    continue
            results.append(ShadowComparison.from_dict(d))
            if len(results) >= limit:
                break
        return results

    def statistics(self) -> dict[str, Any]:
        """Aggregate statistics over all comparisons."""
        if not self._path.exists():
            return {"total_comparisons": 0}

        regrets = []
        safety = 0
        constraints = 0
        count = 0
        by_policy: dict[str, int] = {}

        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            count += 1
            regrets.append(d.get("estimated_regret", 0))
            if d.get("safety_violations"):
                safety += 1
            if d.get("constraint_violations"):
                constraints += 1
            policy = d.get("shadow_policy", "unknown")
            by_policy[policy] = by_policy.get(policy, 0) + 1

        regrets.sort()
        return {
            "total_comparisons": count,
            "mean_regret": sum(regrets) / max(len(regrets), 1),
            "median_regret": regrets[len(regrets) // 2] if regrets else 0,
            "safety_violation_rate": safety / max(count, 1),
            "constraint_violation_rate": constraints / max(count, 1),
            "by_policy": by_policy,
        }



# Helpers


def _diff_decisions(prod: dict, shadow: dict) -> dict:
    """Compute structured diff between two decisions."""
    diff = {}
    for key in set(list(prod.keys()) + list(shadow.keys())):
        p_val = prod.get(key)
        s_val = shadow.get(key)
        if p_val != s_val:
            diff[key] = {"production": p_val, "shadow": s_val}
    return diff


def _check_safety_violations(decision: dict, context: dict) -> list[str]:
    """Check shadow decision for safety violations."""
    violations = []
    # Check if shadow decision would: execute shell without approval
    if decision.get("requires_shell") and not decision.get("approval_granted"):
        violations.append("shell_execution_without_approval")
    # Check if shadow would write outside workspace
    if decision.get("write_scope") == "external":
        violations.append("external_write_scope")
    # Check if shadow model lacks required privacy class
    req_privacy = context.get("privacy_class", "")
    shadow_privacy = decision.get("model_privacy_class", "")
    if req_privacy == "restricted" and shadow_privacy != "restricted":
        violations.append("privacy_class_mismatch")
    return violations


def _check_constraint_violations(decision: dict, task: dict) -> list[str]:
    """Check shadow decision for constraint violations."""
    violations = []
    budget = float(task.get("budget_usd", 0))
    est_cost = float(decision.get("estimated_cost", 0))
    if budget > 0 and est_cost > budget:
        violations.append(f"budget_exceeded: {est_cost} > {budget}")
    deadline = int(task.get("deadline_seconds", 0))
    est_latency = int(decision.get("estimated_latency_ms", 0))
    if deadline > 0 and est_latency > deadline * 1000:
        violations.append(f"deadline_exceeded: {est_latency}ms > {deadline}s")
    return violations


def _estimate_regret(production: dict, shadow: dict) -> float:
    """Estimate regret: how much worse the shadow decision might have been.

    0 = shadow is better or equal, 1 = shadow is much worse.
    Simple heuristic comparing cost, quality, and latency.
    """
    regret = 0.0
    # Cost regret
    prod_cost = float(production.get("estimated_cost", 0))
    shadow_cost = float(shadow.get("estimated_cost", 0))
    if prod_cost > 0 and shadow_cost > prod_cost:
        regret += min(0.5, (shadow_cost - prod_cost) / prod_cost)
    # Latency regret
    prod_lat = float(production.get("estimated_latency_ms", 0))
    shadow_lat = float(shadow.get("estimated_latency_ms", 0))
    if prod_lat > 0 and shadow_lat > prod_lat:
        regret += min(0.3, (shadow_lat - prod_lat) / prod_lat)
    # Quality regret
    prod_qual = {"expert": 1.0, "advanced": 0.8, "competent": 0.6, "basic": 0.4, "novice": 0.2}.get(
        str(production.get("capability_level", "basic")).lower(), 0.4
    )
    shadow_qual = {"expert": 1.0, "advanced": 0.8, "competent": 0.6, "basic": 0.4, "novice": 0.2}.get(
        str(shadow.get("capability_level", "basic")).lower(), 0.4
    )
    if shadow_qual < prod_qual:
        regret += min(0.2, prod_qual - shadow_qual)
    return min(1.0, regret)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

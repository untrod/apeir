# -*- coding: utf-8 -*-
"""ReplayComparator — structured diff between original and replayed executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplayDiff:
    """Structured comparison between original and replayed execution."""
    field: str
    original_value: Any
    replayed_value: Any
    changed: bool = False
    significance: str = ""  # "major", "minor", "none"


@dataclass
class ReplayComparison:
    """Complete comparison between original and replayed executions."""
    original_trace_id: str = ""
    replayed_trace_id: str = ""
    diffs: list[ReplayDiff] = field(default_factory=list)
    state_transitions_changed: bool = False
    outcome_changed: bool = False
    cost_delta: float = 0.0
    latency_delta_ms: float = 0.0
    summary: str = ""


class ReplayComparator:
    """Compare original and replayed execution traces."""

    def compare(
        self,
        original: dict[str, Any],
        replayed: dict[str, Any],
    ) -> ReplayComparison:
        """Produce a structured comparison."""
        comparison = ReplayComparison(
            original_trace_id=str(original.get("trace_id", "")),
            replayed_trace_id=str(replayed.get("trace_id", "")),
        )

        diffs: list[ReplayDiff] = []

        # Compare outcomes
        orig_outcome = original.get("outcome", {})
        repl_outcome = replayed.get("outcome", {})

        # Status
        orig_status = orig_outcome.get("final_status", "")
        repl_status = repl_outcome.get("final_status", "")
        diffs.append(ReplayDiff(
            field="outcome.final_status",
            original_value=orig_status,
            replayed_value=repl_status,
            changed=orig_status != repl_status,
            significance="major" if orig_status != repl_status else "none",
        ))
        comparison.outcome_changed = orig_status != repl_status

        # Verification
        orig_verif = orig_outcome.get("verification_status", "")
        repl_verif = repl_outcome.get("verification_status", "")
        diffs.append(ReplayDiff(
            field="outcome.verification_status",
            original_value=orig_verif,
            replayed_value=repl_verif,
            changed=orig_verif != repl_verif,
            significance="major" if orig_verif != repl_verif else "none",
        ))

        # Cost
        orig_cost = float(orig_outcome.get("cost_usd", 0))
        repl_cost = float(repl_outcome.get("cost_usd", 0))
        comparison.cost_delta = repl_cost - orig_cost
        diffs.append(ReplayDiff(
            field="outcome.cost_usd",
            original_value=orig_cost,
            replayed_value=repl_cost,
            changed=abs(repl_cost - orig_cost) > 0.0001,
            significance="minor" if abs(repl_cost - orig_cost) < 0.01 else "major",
        ))

        # Latency
        orig_lat = float(orig_outcome.get("latency_ms", 0))
        repl_lat = float(repl_outcome.get("latency_ms", 0))
        comparison.latency_delta_ms = repl_lat - orig_lat
        diffs.append(ReplayDiff(
            field="outcome.latency_ms",
            original_value=orig_lat,
            replayed_value=repl_lat,
            changed=abs(repl_lat - orig_lat) > 1,
            significance="minor",
        ))

        # Decision
        orig_dec = original.get("decision", {})
        repl_dec = replayed.get("decision", {})
        diffs.append(ReplayDiff(
            field="decision.selected_plan",
            original_value=orig_dec.get("selected_plan", ""),
            replayed_value=repl_dec.get("selected_plan", ""),
            changed=orig_dec.get("selected_plan") != repl_dec.get("selected_plan"),
            significance="major",
        ))
        diffs.append(ReplayDiff(
            field="decision.confidence",
            original_value=orig_dec.get("confidence", 0),
            replayed_value=repl_dec.get("confidence", 0),
            changed=abs(float(orig_dec.get("confidence", 0)) - float(repl_dec.get("confidence", 0))) > 0.01,
            significance="minor",
        ))

        comparison.diffs = diffs
        comparison.state_transitions_changed = comparison.outcome_changed

        # Generate summary
        major_changes = [d for d in diffs if d.significance == "major" and d.changed]
        if not any(d.changed for d in diffs):
            comparison.summary = "No differences — replay produced identical results"
        elif not major_changes:
            comparison.summary = f"Minor differences: {', '.join(d.field for d in diffs if d.changed)}"
        else:
            comparison.summary = f"Major differences: {', '.join(d.field for d in major_changes)}"

        return comparison

    def compare_batch(
        self,
        pairs: list[tuple[dict, dict]],
    ) -> list[ReplayComparison]:
        """Compare multiple original/replayed trace pairs."""
        return [self.compare(orig, repl) for orig, repl in pairs]

    def aggregate(self, comparisons: list[ReplayComparison]) -> dict[str, Any]:
        """Aggregate statistics across multiple comparisons."""
        if not comparisons:
            return {"total": 0}

        outcome_changes = sum(1 for c in comparisons if c.outcome_changed)
        total_cost_delta = sum(c.cost_delta for c in comparisons)
        total_latency_delta = sum(c.latency_delta_ms for c in comparisons)

        return {
            "total_comparisons": len(comparisons),
            "outcome_change_rate": outcome_changes / len(comparisons),
            "total_cost_delta_usd": total_cost_delta,
            "avg_cost_delta_usd": total_cost_delta / len(comparisons),
            "total_latency_delta_ms": total_latency_delta,
            "avg_latency_delta_ms": total_latency_delta / len(comparisons),
            "identical_rate": sum(
                1 for c in comparisons
                if not any(d.changed for d in c.diffs)
            ) / len(comparisons),
        }

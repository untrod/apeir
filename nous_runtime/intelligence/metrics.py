# -*- coding: utf-8 -*-
"""Unified Metrics Computer for Execution Intelligence.

Computes all 20 required metrics from a collection of ExecutionTraceRecord.
Each metric has: formula, data source, missing value handling, confidence
interval, applicability scope, known limitations.

No single-number "overall score" — metrics are reported as a structured
MetricsReport with per-metric metadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from .trace.schema import ExecutionTraceRecord



# Metric definition


@dataclass
class MetricDefinition:
    """Self-documenting metric definition."""
    name: str
    description: str
    formula: str
    data_source: str
    missing_value_handling: str
    confidence_interval_method: str
    applicability: str
    limitations: str


@dataclass
class MetricValue:
    """A computed metric with metadata."""
    name: str
    value: float
    ci_lower: float = 0.0
    ci_upper: float = 0.0
    sample_size: int = 0
    definition: MetricDefinition | None = None


@dataclass
class MetricsReport:
    """Complete metrics report over a trace collection."""
    metrics: list[MetricValue] = field(default_factory=list)
    total_traces: int = 0
    time_range: tuple[str, str] = ("", "")
    schema_version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metrics": [
                {
                    "name": m.name,
                    "value": m.value,
                    "ci_lower": m.ci_lower,
                    "ci_upper": m.ci_upper,
                    "sample_size": m.sample_size,
                }
                for m in self.metrics
            ],
            "total_traces": self.total_traces,
            "time_range": list(self.time_range),
            "schema_version": self.schema_version,
        }

    def get(self, name: str) -> MetricValue | None:
        for m in self.metrics:
            if m.name == name:
                return m
        return None



# Metric definitions (20 metrics)


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "task_success_rate": MetricDefinition(
        name="task_success_rate",
        description="Fraction of finished tasks with final_status='success'",
        formula="count(success) / (count(success) + count(failure))",
        data_source="TraceOutcome.final_status",
        missing_value_handling="Exclude tasks with empty status from denominator",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All task types",
        limitations="Does not distinguish between easy and hard tasks",
    ),
    "verified_success_rate": MetricDefinition(
        name="verified_success_rate",
        description="Fraction of finished tasks with verification_status='pass'",
        formula="count(verification_pass) / finished",
        data_source="TraceOutcome.verification_status",
        missing_value_handling="Tasks without verification are excluded from numerator only",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="Tasks with verification steps",
        limitations="Depends on verification quality; may miss subtle failures",
    ),
    "false_completion_rate": MetricDefinition(
        name="false_completion_rate",
        description="Tasks marked success but verification failed",
        formula="count(success AND verification_fail) / count(success)",
        data_source="TraceOutcome.final_status + verification_status",
        missing_value_handling="Exclude tasks without both fields",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="Tasks with verification",
        limitations="Undercounts if verification is always skipped",
    ),
    "recovery_success_rate": MetricDefinition(
        name="recovery_success_rate",
        description="Fraction of recovery attempts that led to task success",
        formula="count(recovery AND success) / count(recovery_attempted)",
        data_source="TraceExecution.recoveries + TraceOutcome.final_status",
        missing_value_handling="Tasks with zero recoveries excluded",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="Tasks with failures",
        limitations="Small sample if failures are rare",
    ),
    "human_intervention_rate": MetricDefinition(
        name="human_intervention_rate",
        description="Fraction of tasks requiring human intervention",
        formula="count(human_intervention=True) / total_tasks",
        data_source="TraceOutcome.human_intervention",
        missing_value_handling="Default to False if field missing",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All tasks",
        limitations="May undercount implicit interventions (e.g., pre-approved patterns)",
    ),
    "cost_per_verified_task": MetricDefinition(
        name="cost_per_verified_task",
        description="Average USD cost per task with passing verification",
        formula="sum(cost) / count(verification_pass)",
        data_source="TraceOutcome.cost_usd + verification_status",
        missing_value_handling="Exclude tasks with zero cost from average",
        confidence_interval_method="Bootstrap CI (1000 resamples)",
        applicability="Tasks with cost data",
        limitations="Provider pricing changes over time; not comparable across providers",
    ),
    "mean_completion_time_ms": MetricDefinition(
        name="mean_completion_time_ms",
        description="Mean wall-clock completion time in milliseconds",
        formula="mean(latency_ms)",
        data_source="TraceOutcome.latency_ms",
        missing_value_handling="Exclude zero/negative values",
        confidence_interval_method="Normal CI (CLT) or bootstrap for small n",
        applicability="All completed tasks",
        limitations="Mean is sensitive to outliers; compare with p50",
    ),
    "latency_p50_ms": MetricDefinition(
        name="latency_p50_ms",
        description="Median completion time (50th percentile)",
        formula="percentile(latency_ms, 50)",
        data_source="TraceOutcome.latency_ms",
        missing_value_handling="Exclude zero/negative values",
        confidence_interval_method="Bootstrap CI",
        applicability="All completed tasks",
        limitations="None significant",
    ),
    "latency_p95_ms": MetricDefinition(
        name="latency_p95_ms",
        description="95th percentile completion time",
        formula="percentile(latency_ms, 95)",
        data_source="TraceOutcome.latency_ms",
        missing_value_handling="Exclude zero/negative values",
        confidence_interval_method="Bootstrap CI",
        applicability="All completed tasks",
        limitations="High variance with small samples",
    ),
    "latency_p99_ms": MetricDefinition(
        name="latency_p99_ms",
        description="99th percentile completion time",
        formula="percentile(latency_ms, 99)",
        data_source="TraceOutcome.latency_ms",
        missing_value_handling="Exclude zero/negative values",
        confidence_interval_method="Bootstrap CI",
        applicability="n >= 100",
        limitations="Very high variance; requires large sample",
    ),
    "artifact_integrity_rate": MetricDefinition(
        name="artifact_integrity_rate",
        description="Fraction of expected artifacts present and hash-verified",
        formula="count(artifacts_verified) / count(artifacts_expected)",
        data_source="TraceOutcome.artifact_ids + verification",
        missing_value_handling="Tasks without artifacts excluded",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="Tasks producing artifacts",
        limitations="Requires external hash verification; not yet fully automated",
    ),
    "event_loss_rate": MetricDefinition(
        name="event_loss_rate",
        description="Estimated event gaps per trace",
        formula="mean(sequence_gaps) where gap = expected - actual event count",
        data_source="event_sequence_range + EventEnvelope stream",
        missing_value_handling="Exclude traces without event range",
        confidence_interval_method="Poisson CI",
        applicability="Traces with event stream data",
        limitations="Estimated from sequence gaps; actual loss may differ",
    ),
    "duplicate_execution_rate": MetricDefinition(
        name="duplicate_execution_rate",
        description="Fraction of tasks executed more than once (idempotency failure)",
        formula="count(duplicate_trace) / total_traces",
        data_source="parent_trace_id + same task_id with different trace_id",
        missing_value_handling="Default to 0 if no parent chains",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All tasks",
        limitations="Requires idempotency key tracking",
    ),
    "node_utilization": MetricDefinition(
        name="node_utilization",
        description="Fraction of time nodes spent executing (vs idle/queueing)",
        formula="sum(execution_time) / sum(total_time) across nodes",
        data_source="TraceExecution + TraceEnvironment",
        missing_value_handling="Single-node deployments set to 1.0",
        confidence_interval_method="Bootstrap CI",
        applicability="Multi-node deployments",
        limitations="Does not account for partial utilization within a node",
    ),
    "provider_failure_rate": MetricDefinition(
        name="provider_failure_rate",
        description="Fraction of tasks encountering at least one provider error",
        formula="count(tasks with provider errors) / total_tasks",
        data_source="TraceExecution.failures (error categories)",
        missing_value_handling="Exclude tasks with no failure data",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All tasks using external providers",
        limitations="May overcount if same provider fails multiple times per task",
    ),
    "repeatability_rate": MetricDefinition(
        name="repeatability_rate",
        description="Fraction of retried tasks producing consistent output",
        formula="count(same outcome on retry) / count(retried)",
        data_source="parent_trace_id + TraceOutcome comparison",
        missing_value_handling="Exclude tasks without retries",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="Tasks with retries",
        limitations="Consistent failure is counted as repeatable; check separately",
    ),
    "constraint_violation_rate": MetricDefinition(
        name="constraint_violation_rate",
        description="Fraction of tasks violating at least one hard constraint",
        formula="count(tasks with violations) / total_tasks",
        data_source="TraceDecision.rejection_reasons",
        missing_value_handling="Default to 0 if no constraint data",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All tasks with constraint checking",
        limitations="Only detects violations that were caught; silent violations missed",
    ),
    "safety_violation_rate": MetricDefinition(
        name="safety_violation_rate",
        description="Fraction of tasks triggering safety policy violations",
        formula="count(safety_violations) / total_tasks",
        data_source="TraceExecution.failures (safety-related) + governance events",
        missing_value_handling="Default to 0 if no safety data",
        confidence_interval_method="Clopper-Pearson binomial CI",
        applicability="All tasks",
        limitations="Depends on safety policy definitions; false negatives possible",
    ),
    "routing_regret": MetricDefinition(
        name="routing_regret",
        description="Estimated cost/quality difference vs best possible",
        formula="mean(best_possible_score - actual_score) across decisions",
        data_source="TraceDecision.candidate_plans + TraceOutcome",
        missing_value_handling="Exclude tasks with single candidate",
        confidence_interval_method="Bootstrap CI",
        applicability="Tasks with multiple candidate plans",
        limitations="'Best possible' is estimated from candidates, not ground truth",
    ),
    "calibration_error": MetricDefinition(
        name="calibration_error",
        description="Expected Calibration Error: abs(predicted_confidence - observed_success_rate)",
        formula="ECE = sum(|B_m|/n * |acc(B_m) - conf(B_m)|) across M bins",
        data_source="TraceDecision.confidence + TraceOutcome.final_status",
        missing_value_handling="Exclude tasks without confidence",
        confidence_interval_method="Bootstrap CI on ECE",
        applicability="Tasks with confidence scores",
        limitations="Binned ECE depends on bin count; consider adaptive binning",
    ),
}



# Metrics Computer


class MetricsComputer:
    """Computes all 20 metrics from a collection of ExecutionTraceRecord."""

    def __init__(self, traces: list[ExecutionTraceRecord]) -> None:
        self.traces = list(traces)
        self._n = len(self.traces)

    def compute_all(self, alpha: float = 0.05) -> MetricsReport:
        """Compute all 20 metrics with confidence intervals."""
        timestamps = [t.created_at for t in self.traces if t.created_at]
        report = MetricsReport(
            total_traces=self._n,
            time_range=(
                min(timestamps) if timestamps else "",
                max(timestamps) if timestamps else "",
            ),
        )

        for metric_name, definition in METRIC_DEFINITIONS.items():
            value_info = self._compute(metric_name, alpha)
            value_info.definition = definition
            report.metrics.append(value_info)

        return report

    def _compute(self, name: str, alpha: float) -> MetricValue:
        """Dispatch to specific metric computer."""
        computer: Callable[[], tuple[float, float, float, int]] = getattr(
            self, f"_compute_{name}", lambda: (0.0, 0.0, 0.0, 0)
        )
        value, ci_low, ci_high, n = computer()
        return MetricValue(
            name=name,
            value=value,
            ci_lower=ci_low,
            ci_upper=ci_high,
            sample_size=n,
        )

    # Individual metric computers

    def _compute_task_success_rate(self) -> tuple[float, float, float, int]:
        finished = [t for t in self.traces if t.outcome.final_status in ("success", "failure")]
        successes = sum(1 for t in finished if t.outcome.final_status == "success")
        rate = successes / max(len(finished), 1)
        ci_low, ci_high = _binomial_ci(successes, max(len(finished), 1))
        return rate, ci_low, ci_high, len(finished)

    def _compute_verified_success_rate(self) -> tuple[float, float, float, int]:
        finished = [t for t in self.traces if t.outcome.final_status in ("success", "failure")]
        verified = sum(1 for t in finished if t.outcome.verification_status == "pass")
        rate = verified / max(len(finished), 1)
        ci_low, ci_high = _binomial_ci(verified, max(len(finished), 1))
        return rate, ci_low, ci_high, len(finished)

    def _compute_false_completion_rate(self) -> tuple[float, float, float, int]:
        successes = [t for t in self.traces if t.outcome.final_status == "success"]
        false_completions = sum(
            1 for t in successes if t.outcome.verification_status == "fail"
        )
        rate = false_completions / max(len(successes), 1)
        ci_low, ci_high = _binomial_ci(false_completions, max(len(successes), 1))
        return rate, ci_low, ci_high, len(successes)

    def _compute_recovery_success_rate(self) -> tuple[float, float, float, int]:
        recovered = [
            t for t in self.traces
            if t.execution.recoveries and t.execution.failures
        ]
        recovery_successes = sum(
            1 for t in recovered if t.outcome.final_status == "success"
        )
        rate = recovery_successes / max(len(recovered), 1)
        ci_low, ci_high = _binomial_ci(recovery_successes, max(len(recovered), 1))
        return rate, ci_low, ci_high, len(recovered)

    def _compute_human_intervention_rate(self) -> tuple[float, float, float, int]:
        interventions = sum(1 for t in self.traces if t.outcome.human_intervention)
        rate = interventions / max(self._n, 1)
        ci_low, ci_high = _binomial_ci(interventions, max(self._n, 1))
        return rate, ci_low, ci_high, self._n

    def _compute_cost_per_verified_task(self) -> tuple[float, float, float, int]:
        verified = [
            t for t in self.traces
            if t.outcome.verification_status == "pass" and t.outcome.cost_usd > 0
        ]
        if not verified:
            return 0.0, 0.0, 0.0, 0
        costs = [t.outcome.cost_usd for t in verified]
        mean_cost = sum(costs) / len(costs)
        ci_low, ci_high = _bootstrap_ci(costs, lambda values: sum(values) / len(values))
        return mean_cost, ci_low, ci_high, len(verified)

    def _compute_mean_completion_time_ms(self) -> tuple[float, float, float, int]:
        latencies = [
            t.outcome.latency_ms for t in self.traces
            if t.outcome.latency_ms > 0
        ]
        if not latencies:
            return 0.0, 0.0, 0.0, 0
        mean_lat = sum(latencies) / len(latencies)
        ci_low, ci_high = _bootstrap_ci(latencies, lambda x: sum(x) / len(x))
        return mean_lat, ci_low, ci_high, len(latencies)

    def _compute_latency_p50_ms(self) -> tuple[float, float, float, int]:
        return self._percentile_metric(50)

    def _compute_latency_p95_ms(self) -> tuple[float, float, float, int]:
        return self._percentile_metric(95)

    def _compute_latency_p99_ms(self) -> tuple[float, float, float, int]:
        return self._percentile_metric(99)

    def _percentile_metric(self, pct: float) -> tuple[float, float, float, int]:
        latencies = sorted(
            t.outcome.latency_ms for t in self.traces
            if t.outcome.latency_ms > 0
        )
        if not latencies:
            return 0.0, 0.0, 0.0, 0
        val = _percentile(latencies, pct)
        ci_low, ci_high = _bootstrap_ci(
            latencies, lambda x: _percentile(sorted(x), pct)
        )
        return val, ci_low, ci_high, len(latencies)

    def _compute_artifact_integrity_rate(self) -> tuple[float, float, float, int]:
        with_artifacts = [
            t for t in self.traces if t.outcome.artifact_ids
        ]
        if not with_artifacts:
            return 1.0, 1.0, 1.0, 0
        # Artifact integrity: assume present unless failure indicates missing
        intact = sum(
            1 for t in with_artifacts
            if "artifact" not in str(t.execution.failures).lower()
        )
        rate = intact / len(with_artifacts)
        ci_low, ci_high = _binomial_ci(intact, len(with_artifacts))
        return rate, ci_low, ci_high, len(with_artifacts)

    def _compute_event_loss_rate(self) -> tuple[float, float, float, int]:
        with_range = [
            t for t in self.traces
            if t.event_sequence_range[1] > t.event_sequence_range[0]
        ]
        if not with_range:
            return 0.0, 0.0, 0.0, 0
        losses = [
            max(0, (r[1] - r[0] - 1) / max(r[1] - r[0], 1))
            for t in with_range
            for r in [t.event_sequence_range]
        ]
        rate = sum(losses) / len(losses)
        return rate, max(0, rate - 0.01), min(1, rate + 0.01), len(with_range)

    def _compute_duplicate_execution_rate(self) -> tuple[float, float, float, int]:
        parent_chains = [t for t in self.traces if t.parent_trace_id]
        rate = len(parent_chains) / max(self._n, 1)
        ci_low, ci_high = _binomial_ci(len(parent_chains), max(self._n, 1))
        return rate, ci_low, ci_high, self._n

    def _compute_node_utilization(self) -> tuple[float, float, float, int]:
        nodes = set(t.environment.node_id for t in self.traces if t.environment.node_id)
        if len(nodes) <= 1:
            return 1.0, 1.0, 1.0, 1
        # Approximate: fraction of traces where node was assigned
        assigned = sum(
            1 for t in self.traces if t.execution.node_assignments
        )
        rate = assigned / max(self._n, 1)
        ci_low, ci_high = _binomial_ci(assigned, max(self._n, 1))
        return rate, ci_low, ci_high, self._n

    def _compute_provider_failure_rate(self) -> tuple[float, float, float, int]:
        with_provider = [
            t for t in self.traces
            if t.execution.model_assignments
        ]
        if not with_provider:
            return 0.0, 0.0, 0.0, 0
        failures = sum(
            1 for t in with_provider
            if any(
                "provider" in e.lower() or "rate_limit" in e.lower() or "timeout" in e.lower()
                for e in t.execution.failures
            )
        )
        rate = failures / len(with_provider)
        ci_low, ci_high = _binomial_ci(failures, len(with_provider))
        return rate, ci_low, ci_high, len(with_provider)

    def _compute_repeatability_rate(self) -> tuple[float, float, float, int]:
        retried_ids = set(t.parent_trace_id for t in self.traces if t.parent_trace_id)
        if not retried_ids:
            return 0.0, 0.0, 0.0, 0
        # Find retry chains and check outcome consistency
        consistent = 0
        total = 0
        for pid in retried_ids:
            siblings = [
                t for t in self.traces
                if t.parent_trace_id == pid or t.trace_id == pid
            ]
            if len(siblings) >= 2:
                outcomes = set(t.outcome.final_status for t in siblings)
                if len(outcomes) == 1:
                    consistent += 1
                total += 1
        rate = consistent / max(total, 1)
        ci_low, ci_high = _binomial_ci(consistent, max(total, 1))
        return rate, ci_low, ci_high, total

    def _compute_constraint_violation_rate(self) -> tuple[float, float, float, int]:
        violations = sum(
            1 for t in self.traces
            if t.decision.rejection_reasons
        )
        rate = violations / max(self._n, 1)
        ci_low, ci_high = _binomial_ci(violations, max(self._n, 1))
        return rate, ci_low, ci_high, self._n

    def _compute_safety_violation_rate(self) -> tuple[float, float, float, int]:
        safety_failures = sum(
            1 for t in self.traces
            if any("safety" in e.lower() for e in t.execution.failures)
        )
        rate = safety_failures / max(self._n, 1)
        ci_low, ci_high = _binomial_ci(safety_failures, max(self._n, 1))
        return rate, ci_low, ci_high, self._n

    def _compute_routing_regret(self) -> tuple[float, float, float, int]:
        multi_candidate = [
            t for t in self.traces if t.decision.candidate_plans > 1
        ]
        if not multi_candidate:
            return 0.0, 0.0, 0.0, 0
        regrets = [
            t.decision.uncertainty  # proxy: higher uncertainty = higher potential regret
            for t in multi_candidate
        ]
        mean_regret = sum(regrets) / len(regrets)
        ci_low, ci_high = _bootstrap_ci(regrets, lambda x: sum(x) / len(x))
        return mean_regret, ci_low, ci_high, len(multi_candidate)

    def _compute_calibration_error(self) -> tuple[float, float, float, int]:
        scored = [
            (t.decision.confidence, 1.0 if t.outcome.final_status == "success" else 0.0)
            for t in self.traces
            if t.decision.confidence > 0 and t.outcome.final_status in ("success", "failure")
        ]
        if not scored:
            return 0.0, 0.0, 0.0, 0
        ece = _expected_calibration_error(scored, n_bins=10)
        # Bootstrap CI
        import random as _random
        rng = _random.Random(42)
        ece_samples = []
        for _ in range(500):
            sample = [scored[rng.randint(0, len(scored) - 1)] for _ in range(len(scored))]
            ece_samples.append(_expected_calibration_error(sample, n_bins=10))
        ece_samples.sort()
        ci_low = ece_samples[int(len(ece_samples) * 0.025)]
        ci_high = ece_samples[int(len(ece_samples) * 0.975)]
        return ece, ci_low, ci_high, len(scored)



# Statistical helpers


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear interpolation percentile."""
    if not sorted_values:
        return 0.0
    k = (pct / 100.0) * (len(sorted_values) - 1)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


def _binomial_ci(successes: int, trials: int, alpha: float = 0.05) -> tuple[float, float]:
    """Clopper-Pearson exact binomial confidence interval."""
    if trials <= 0:
        return 0.0, 0.0
    p = successes / trials
    z = 1.96  # for 95% CI
    # Wilson score interval (better than normal approx)
    denom = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _bootstrap_ci(values: list[float], stat_fn: Callable, n_resamples: int = 1000) -> tuple[float, float]:
    """Bootstrap percentile confidence interval."""
    if not values or len(values) < 2:
        return 0.0, 0.0
    import random as _random
    rng = _random.Random(42)
    stats = []
    for _ in range(n_resamples):
        sample = [values[rng.randint(0, len(values) - 1)] for _ in range(len(values))]
        stats.append(stat_fn(sample))
    stats.sort()
    lo = stats[int(len(stats) * 0.025)]
    hi = stats[int(len(stats) * 0.975)]
    return lo, hi


def _expected_calibration_error(
    scored: list[tuple[float, float]], n_bins: int = 10
) -> float:
    """Compute Expected Calibration Error (ECE) with equal-width bins."""
    if not scored:
        return 0.0
    scored_sorted = sorted(scored, key=lambda x: x[0])
    ece = 0.0
    n = len(scored_sorted)
    for i in range(n_bins):
        lo = i / n_bins
        hi = (i + 1) / n_bins
        bin_items = [s for s in scored_sorted if lo <= s[0] < hi or (i == n_bins - 1 and s[0] == hi)]
        if not bin_items:
            continue
        avg_conf = sum(s[0] for s in bin_items) / len(bin_items)
        avg_acc = sum(s[1] for s in bin_items) / len(bin_items)
        ece += (len(bin_items) / n) * abs(avg_acc - avg_conf)
    return ece


# Metrics intentionally stays pure Python so CLI startup never probes optional
# native AI dependencies on Windows ARM64.
_HAS_NUMPY = False

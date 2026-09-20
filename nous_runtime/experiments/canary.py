# -*- coding: utf-8 -*-
"""Canary Deployment — controlled rollout with automatic rollback triggers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CanaryConfig:
    """Canary deployment configuration."""
    traffic_fraction: float = 0.01   # fraction of traffic to canary
    metrics: list[str] = field(default_factory=lambda: ["success_rate", "latency_p95", "cost_avg"])
    regression_thresholds: dict[str, float] = field(default_factory=lambda: {"success_rate": -0.05, "latency_p95": 0.20, "cost_avg": 0.15})
    min_sample_size: int = 100
    max_duration_hours: int = 24
    auto_rollback: bool = True
    alert_on_regression: bool = True


@dataclass
class CanaryResult:
    """Result of a canary deployment."""
    canary_id: str = ""
    status: str = ""         # running, passed, rolled_back
    canary_score: dict[str, float] = field(default_factory=dict)
    baseline_score: dict[str, float] = field(default_factory=dict)
    regression_detected: bool = False
    regressed_metrics: list[str] = field(default_factory=list)
    sample_size: int = 0
    duration_hours: float = 0.0
    recommendation: str = ""  # promote, rollback, extend


class CanaryController:
    """Controls canary deployment with automatic safety checks."""

    def evaluate(self, config: CanaryConfig, canary_metrics: dict[str, float], baseline_metrics: dict[str, float], sample_size: int) -> CanaryResult:
        """Evaluate canary performance against baseline."""
        result = CanaryResult(
            canary_id=f"canary_{hash(str(canary_metrics))}",
            status="running",
            canary_score=canary_metrics,
            baseline_score=baseline_metrics,
            sample_size=sample_size,
        )

        for metric, threshold in config.regression_thresholds.items():
            base = baseline_metrics.get(metric, 0)
            canary = canary_metrics.get(metric, 0)
            if base != 0:
                change = (canary - base) / abs(base)
                if change < threshold:
                    result.regression_detected = True
                    result.regressed_metrics.append(metric)

        if result.regression_detected and config.auto_rollback:
            result.status = "rolled_back"
            result.recommendation = "rollback"
        elif sample_size < config.min_sample_size:
            result.status = "running"
            result.recommendation = "extend"
        elif result.regression_detected:
            result.status = "running"
            result.recommendation = "extend"
        else:
            result.status = "passed"
            result.recommendation = "promote"

        return result

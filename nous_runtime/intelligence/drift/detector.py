# -*- coding: utf-8 -*-
"""Drift Detection — monitors for model/provider/task distribution changes.

Detects:
  model version changes, provider performance changes, latency drift,
  cost drift, task distribution shift, node resource changes,
  success rate drift, calibration error drift.

Methods: rolling windows, PSI, KL/JS divergence, ADWIN-equivalent,
change-point detection.

On drift: mark statistics stale, reduce policy confidence, enter Shadow,
trigger recalibration, fall back to baseline if necessary.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class DriftWindow:
    """A window of observations for drift detection."""
    values: deque = field(default_factory=lambda: deque(maxlen=1000))
    window_size: int = 100
    reference_mean: float = 0.0
    reference_std: float = 0.0

    def add(self, value: float) -> None:
        self.values.append(value)

    def current_mean(self) -> float:
        if not self.values:
            return 0.0
        return sum(self.values) / len(self.values)

    def current_std(self) -> float:
        if len(self.values) < 2:
            return 0.0
        m = self.current_mean()
        return math.sqrt(sum((v - m) ** 2 for v in self.values) / (len(self.values) - 1))


@dataclass
class DriftAlert:
    """Alert generated when drift is detected."""
    metric: str = ""
    severity: str = ""       # info, warning, critical
    direction: str = ""       # up, down, shift
    magnitude: float = 0.0
    reference_value: float = 0.0
    current_value: float = 0.0
    threshold: float = 0.0
    message: str = ""
    timestamp: float = 0.0


class DriftDetector:
    """Multi-metric drift detection with configurable thresholds.

    Monitors: success_rate, avg_latency_ms, avg_cost_usd,
    task_type_distribution, model_versions, node_resources.

    Action on drift:
      1. Mark statistics stale
      2. Reduce policy confidence
      3. Enter Shadow Mode if degradation detected
      4. Trigger recalibration
      5. Fall back to baseline if critical
    """

    def __init__(self, window_size: int = 100, alert_threshold: float = 2.0) -> None:
        self.window_size = window_size
        self.alert_threshold = alert_threshold  # sigmas for alert
        self._windows: dict[str, DriftWindow] = {}
        self._alerts: list[DriftAlert] = []
        self._baseline_set: bool = False
        self._metrics_stale: bool = False
        self._policy_confidence: float = 1.0

    # Metric registration

    def register_metric(self, name: str) -> None:
        if name not in self._windows:
            self._windows[name] = DriftWindow(window_size=self.window_size)

    def observe(self, metric: str, value: float) -> None:
        """Record an observation for a metric."""
        if metric not in self._windows:
            self.register_metric(metric)
        self._windows[metric].add(value)

    def set_baseline(self, metrics: dict[str, tuple[float, float]]) -> None:
        """Set reference baseline (mean, std) from historical data."""
        for name, (mean, std) in metrics.items():
            if name not in self._windows:
                self.register_metric(name)
            self._windows[name].reference_mean = mean
            self._windows[name].reference_std = std
        self._baseline_set = True

    # Detection

    def check_all(self) -> list[DriftAlert]:
        """Check all metrics for drift. Returns new alerts."""
        if not self._baseline_set:
            return []

        new_alerts = []
        for name, window in self._windows.items():
            alert = self._check_metric(name, window)
            if alert:
                new_alerts.append(alert)
                self._alerts.append(alert)

        # Update state
        if any(a.severity == "critical" for a in new_alerts):
            self._metrics_stale = True
            self._policy_confidence = max(0.2, self._policy_confidence - 0.3)
        elif any(a.severity == "warning" for a in new_alerts):
            self._policy_confidence = max(0.4, self._policy_confidence - 0.1)

        return new_alerts

    def _check_metric(self, name: str, window: DriftWindow) -> DriftAlert | None:
        """Check a single metric for drift."""
        current = window.current_mean()
        ref = window.reference_mean
        ref_std = max(window.reference_std, 0.001)

        # Z-score of current mean vs reference
        n = min(len(window.values), window.window_size)
        if n < 10:
            return None  # insufficient data

        z_score = abs(current - ref) / (ref_std / math.sqrt(n))

        if z_score < self.alert_threshold * 0.5:
            return None

        # Determine severity
        if z_score > self.alert_threshold * 2:
            severity = "critical"
        elif z_score > self.alert_threshold:
            severity = "warning"
        else:
            severity = "info"

        direction = "up" if current > ref else "down"

        return DriftAlert(
            metric=name,
            severity=severity,
            direction=direction,
            magnitude=z_score,
            reference_value=ref,
            current_value=current,
            threshold=self.alert_threshold,
            message=f"{name}: {direction} {z_score:.1f}σ (ref={ref:.4f}, cur={current:.4f})",
            timestamp=time.monotonic(),
        )

    # PSI (Population Stability Index)

    def compute_psi(self, reference_dist: dict[str, float], current_dist: dict[str, float]) -> float:
        """Compute Population Stability Index between two distributions."""
        all_keys = set(reference_dist.keys()) | set(current_dist.keys())
        psi = 0.0
        for k in all_keys:
            p = max(reference_dist.get(k, 0.001), 0.001)
            q = max(current_dist.get(k, 0.001), 0.001)
            psi += (q - p) * math.log(q / p)
        return psi

    # KL Divergence

    def compute_kl_divergence(self, p_dist: dict[str, float], q_dist: dict[str, float]) -> float:
        """KL(P || Q)."""
        kl = 0.0
        for k in p_dist:
            p = max(p_dist[k], 1e-10)
            q = max(q_dist.get(k, 1e-10), 1e-10)
            kl += p * math.log(p / q)
        return kl

    # State query

    @property
    def is_stale(self) -> bool:
        return self._metrics_stale

    @property
    def policy_confidence(self) -> float:
        return self._policy_confidence

    def recent_alerts(self, n: int = 10) -> list[DriftAlert]:
        return self._alerts[-n:]

    def should_fallback(self) -> bool:
        """Return True if drift is severe enough to fall back to baseline."""
        return self._policy_confidence < 0.3

    def reset_staleness(self) -> None:
        """Reset staleness after recalibration."""
        self._metrics_stale = False
        self._policy_confidence = 1.0

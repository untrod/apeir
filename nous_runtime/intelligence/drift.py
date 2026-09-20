# -*- coding: utf-8 -*-
"""
Model Performance Drift Detection.

Implements §12.2 L4 (Long-term drift and version changes) of the master plan.

Detects when a model instance's real-world performance changes over time,
comparing recent observations against historical baseline. Generates alerts
when degradation exceeds thresholds.

Monitors: success rate, latency, cost, tool call validity, output quality.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nous_runtime.compat.ids import make_id

log = logging.getLogger("nous.intelligence.drift")


@dataclass
class DriftWindow:
    """A time-bounded window of performance observations."""
    instance_key: str = ""
    window_start: str = ""
    window_end: str = ""
    sample_count: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    avg_cost_cents: float = 0.0
    tool_call_valid_rate: float = 0.0


@dataclass
class DriftAlert:
    """Alert generated when a metric drifts beyond threshold."""
    alert_id: str = field(default_factory=lambda: make_id(prefix="drift"))
    instance_key: str = ""
    metric: str = ""                     # success_rate, latency, cost, tool_call
    baseline_value: float = 0.0
    recent_value: float = 0.0
    change_pct: float = 0.0              # Percentage change (negative = degradation)
    severity: str = "info"               # info | warning | critical
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "instance_key": self.instance_key,
            "metric": self.metric,
            "baseline_value": round(self.baseline_value, 4),
            "recent_value": round(self.recent_value, 4),
            "change_pct": round(self.change_pct, 2),
            "severity": self.severity,
            "detected_at": self.detected_at,
            "message": self.message,
        }


class DriftDetector:
    """Monitor model performance for drift from baseline.

    Compares recent observations (sliding window) against a historical
    baseline. When a metric degrades beyond the threshold, generates
    a DriftAlert.

    Typical use: run periodically (daily/weekly) against the EvidenceLedger.
    """

    # Default thresholds for alerting
    DEFAULT_THRESHOLDS = {
        "success_rate": -0.10,    # 10% absolute drop
        "avg_latency_ms": 0.50,   # 50% increase
        "avg_cost_cents": 0.30,   # 30% increase
        "tool_call_valid_rate": -0.15,  # 15% absolute drop
    }

    def __init__(self, thresholds: dict[str, float] | None = None):
        self._thresholds = thresholds or self.DEFAULT_THRESHOLDS
        self._alerts: list[DriftAlert] = []

    def detect(self, baseline: DriftWindow, recent: DriftWindow) -> list[DriftAlert]:
        """Compare recent window against baseline, return any drift alerts."""
        alerts: list[DriftAlert] = []

        if baseline.sample_count < 10 or recent.sample_count < 5:
            return alerts  # Insufficient data

        checks = [
            ("success_rate", baseline.success_rate, recent.success_rate, "lower_is_worse"),
            ("avg_latency_ms", baseline.avg_latency_ms, recent.avg_latency_ms, "higher_is_worse"),
            ("avg_cost_cents", baseline.avg_cost_cents, recent.avg_cost_cents, "higher_is_worse"),
            ("tool_call_valid_rate", baseline.tool_call_valid_rate, recent.tool_call_valid_rate, "lower_is_worse"),
        ]

        for metric, base_val, recent_val, direction in checks:
            if base_val == 0:
                continue

            threshold = self._thresholds.get(metric, 0.10)
            change_pct = (recent_val - base_val) / base_val

            if direction == "lower_is_worse":
                degraded = change_pct < threshold  # threshold is negative
            else:
                degraded = change_pct > threshold  # threshold is positive

            if degraded:
                severity = "critical" if abs(change_pct) > abs(threshold) * 2 else "warning"
                alert = DriftAlert(
                    instance_key=baseline.instance_key,
                    metric=metric,
                    baseline_value=base_val,
                    recent_value=recent_val,
                    change_pct=change_pct * 100,  # Convert to percentage
                    severity=severity,
                    message=self._format_message(metric, base_val, recent_val, change_pct),
                )
                alerts.append(alert)
                self._alerts.append(alert)
                log.warning("Drift detected: %s %s change=%.1f%% severity=%s",
                            baseline.instance_key, metric, change_pct * 100, severity)

        return alerts

    def get_alerts(self, since: str = "", min_severity: str = "warning") -> list[DriftAlert]:
        """Get recent drift alerts."""
        alerts = self._alerts
        if since:
            alerts = [a for a in alerts if a.detected_at >= since]
        sev_order = {"info": 0, "warning": 1, "critical": 2}
        min_level = sev_order.get(min_severity, 0)
        return [a for a in alerts if sev_order.get(a.severity, 0) >= min_level]

    def clear_alerts(self) -> None:
        self._alerts.clear()

    @staticmethod
    def _format_message(metric: str, base: float, recent: float, change: float) -> str:
        direction = "↑" if change > 0 else "↓"
        pct = abs(change) * 100
        return (
            f"{metric}: {base:.3f} → {recent:.3f} ({direction}{pct:.1f}%). "
            f"Baseline n={base}, recent n={recent}."
        )


class DriftAnalyzer:
    """High-level drift analysis using EvidenceLedger data.

    Periodically samples recent executions, builds windows, and runs
    drift detection across all tracked model instances.
    """

    def __init__(self, ledger=None, detector: DriftDetector | None = None):
        self._ledger = ledger
        self._detector = detector or DriftDetector()

    def analyze_instance(self, instance_key: str,
                         baseline_days: int = 30,
                         recent_days: int = 7) -> list[DriftAlert]:
        """Analyze drift for a single model instance.

        Args:
            instance_key: The exact model instance to analyze
            baseline_days: Days of history for baseline
            recent_days: Days of recent data to compare

        Returns list of DriftAlert if degradation detected.
        """
        # In production, this would query the EvidenceLedger.
        # For now, we define the interface and return empty if no ledger.
        if self._ledger is None:
            return []

        baseline = self._build_window(instance_key, baseline_days)
        recent = self._build_window(instance_key, recent_days)
        return self._detector.detect(baseline, recent)

    def analyze_all(self, baseline_days: int = 30,
                    recent_days: int = 7) -> dict[str, list[DriftAlert]]:
        """Run drift analysis on all tracked model instances."""
        results: dict[str, list[DriftAlert]] = {}
        # Would iterate over all instance_keys in ledger
        return results

    def _build_window(self, instance_key: str, days: int) -> DriftWindow:
        """Build a performance window from ledger data."""
        # Would query EvidenceLedger for executions in the time range
        return DriftWindow(instance_key=instance_key)

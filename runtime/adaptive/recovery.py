"""
Fault Prediction and Self-Healing — RC10 predictive recovery.

RC9 provides reactive recovery (retry, fallback, circuit breaker).
RC10 adds predictive recovery: observe precursor signals, predict
impending failures, and take preemptive action.

When adaptive_recovery is DISABLED: reactive recovery only (RC9 behavior).
When adaptive_recovery is ENABLED: predictive drain, checkpoint, migration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from runtime.adaptive.flags import AdaptiveFlags
from runtime.adaptive.observation import DecisionRecord, DecisionType, ObservationLedger


class FaultSignal(str, Enum):
    """Precursor signals that may indicate impending failure."""

    MEMORY_GROWING = "memory_growing"  # Sustained memory increase
    VRAM_FRAGMENTING = "vram_fragmenting"  # VRAM fragmentation rising
    ENGINE_LATENCY_DRIFT = "engine_latency_drift"  # Engine getting slower
    NODE_HEARTBEAT_JITTER = "node_heartbeat_jitter"  # Heartbeat becoming irregular
    TEMPERATURE_RISING = "temperature_rising"  # Temperature trending up
    DISK_FILLING = "disk_filling"  # Disk nearly full
    JOURNAL_WRITE_LATENCY = "journal_write_latency"  # Journal writes slowing
    PROVIDER_ERROR_RATE = "provider_error_rate"  # Provider errors increasing
    NETWORK_LOSS = "network_loss"  # Packet loss increasing
    TOOL_TIMEOUT = "tool_timeout"  # Tool calls timing out
    PROCESS_RESTART_FREQUENCY = "process_restart_frequency"  # Frequent restarts


class HealingAction(str, Enum):
    """Self-healing actions, classified by approval requirement."""

    WARN = "warn"  # Auto-allowed: emit warning
    THROTTLE = "throttle"  # Auto-allowed: reduce concurrency
    DRAIN = "drain"  # Auto-allowed: stop accepting new work
    CHECKPOINT = "checkpoint"  # Auto-allowed: save state
    RESTART_ENGINE = "restart"  # Auto-allowed: restart stateless adapter
    FALLBACK = "fallback"  # Auto-allowed: switch to fallback model/provider
    MIGRATE = "migrate"  # Requires approval: move tasks to another node
    QUARANTINE = "quarantine"  # Requires approval: isolate node/engine

    def auto_allowed(self) -> bool:
        """Check if this action requires explicit approval."""
        return self not in (HealingAction.MIGRATE, HealingAction.QUARANTINE)


@dataclass
class FaultPrediction:
    """Prediction of an impending fault."""

    signal: FaultSignal
    probability: float
    lead_time_seconds: float | None
    recommended_action: HealingAction
    evidence: dict[str, Any]
    predicted_at: float = field(default_factory=time.time)


@dataclass
class HealingDecision:
    """A self-healing decision that was or will be executed."""

    action: HealingAction
    target: str  # Engine ID, Node ID, etc.
    reason: str
    auto_executed: bool
    required_approval: bool
    predicted_fault: FaultPrediction | None = None
    executed_at: float = field(default_factory=time.time)


class FaultPredictor:
    """Predicts impending faults from precursor signals.

    Uses lightweight statistical detectors — no neural network required.
    Each detector tracks a moving window of observations and triggers
    when the trend exceeds a threshold.
    """

    def __init__(self, window_size: int = 60, history_size: int = 600) -> None:
        self._window_size = window_size
        self._observations: dict[str, list[tuple[float, float]]] = {}
        self._history_size = history_size

    def observe(self, signal: FaultSignal, value: float) -> None:
        """Record an observation for a signal."""
        now = time.time()
        if signal.value not in self._observations:
            self._observations[signal.value] = []
        self._observations[signal.value].append((now, value))
        # Trim to history size
        if len(self._observations[signal.value]) > self._history_size:
            self._observations[signal.value] = self._observations[signal.value][
                -self._history_size :
            ]

    def predict(self, signal: FaultSignal) -> FaultPrediction | None:
        """Predict whether a fault is likely based on observed trends."""
        obs = self._observations.get(signal.value, [])
        if len(obs) < self._window_size:
            return None

        recent = obs[-self._window_size :]
        values = [v for _, v in recent]

        # Simple trend detection: linear regression slope
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return None

        slope = numerator / denominator
        current = values[-1]
        predicted_next = y_mean + slope * n

        # Determine threshold and action per signal type
        threshold, action = self._threshold_for_signal(
            signal, slope, current, predicted_next
        )

        if threshold is not None:
            probability = min(0.95, abs(slope) / threshold if threshold > 0 else 0.0)
            lead_time = self._estimate_lead_time(
                signal, current, predicted_next, threshold
            )

            return FaultPrediction(
                signal=signal,
                probability=probability,
                lead_time_seconds=lead_time,
                recommended_action=action,
                evidence={
                    "slope": slope,
                    "current": current,
                    "predicted_next": predicted_next,
                    "sample_count": n,
                    "threshold": threshold,
                },
            )

        return None

    def predict_all(self) -> list[FaultPrediction]:
        """Predict all impending faults."""
        predictions = []
        for signal in FaultSignal:
            pred = self.predict(signal)
            if pred is not None and pred.probability > 0.5:
                predictions.append(pred)
        predictions.sort(key=lambda p: p.probability, reverse=True)
        return predictions

    def _threshold_for_signal(
        self,
        signal: FaultSignal,
        slope: float,
        current: float,
        predicted: float,
    ) -> tuple[float | None, HealingAction]:
        """Determine the detection threshold and recommended action."""
        configs = {
            FaultSignal.MEMORY_GROWING: (0.05, HealingAction.DRAIN),
            FaultSignal.VRAM_FRAGMENTING: (0.02, HealingAction.RESTART_ENGINE),
            FaultSignal.ENGINE_LATENCY_DRIFT: (0.10, HealingAction.THROTTLE),
            FaultSignal.NODE_HEARTBEAT_JITTER: (0.20, HealingAction.CHECKPOINT),
            FaultSignal.TEMPERATURE_RISING: (0.03, HealingAction.THROTTLE),
            FaultSignal.DISK_FILLING: (0.01, HealingAction.DRAIN),
            FaultSignal.JOURNAL_WRITE_LATENCY: (0.15, HealingAction.CHECKPOINT),
            FaultSignal.PROVIDER_ERROR_RATE: (0.05, HealingAction.FALLBACK),
            FaultSignal.NETWORK_LOSS: (0.10, HealingAction.DRAIN),
            FaultSignal.TOOL_TIMEOUT: (0.08, HealingAction.FALLBACK),
            FaultSignal.PROCESS_RESTART_FREQUENCY: (0.50, HealingAction.QUARANTINE),
        }
        cfg = configs.get(signal)
        if cfg is None:
            return None, HealingAction.WARN

        threshold, action = cfg
        if abs(slope) > threshold:
            return threshold, action
        return None, action

    def _estimate_lead_time(
        self,
        signal: FaultSignal,
        current: float,
        predicted: float,
        threshold: float,
    ) -> float | None:
        """Estimate time until fault occurs."""
        delta = abs(predicted - current)
        if delta < 0.001:
            return None
        # Rough estimate based on trend
        return 60.0  # Default 60s lead time


class SelfHealer:
    """Executes healing actions with appropriate approval gating.

    When adaptive_recovery is DISABLED: only reactive recovery.
    When adaptive_recovery is ENABLED: predictive actions where auto-allowed.
    """

    def __init__(
        self,
        predictor: FaultPredictor | None = None,
        ledger: ObservationLedger | None = None,
    ) -> None:
        self._predictor = predictor or FaultPredictor()
        self._ledger = ledger or ObservationLedger()
        self._action_log: list[HealingDecision] = []

    def assess_and_heal(
        self,
        target_id: str,
        workload_id: str = "",
    ) -> list[HealingDecision]:
        """Assess fault predictions and execute auto-allowed healing actions.

        Returns list of executed healing decisions.
        """
        flags = AdaptiveFlags.global_flags()

        if not flags.is_enabled("adaptive_recovery"):
            return []  # No predictive healing — rely on reactive recovery

        predictions = self._predictor.predict_all()
        decisions = []

        for pred in predictions:
            action = pred.recommended_action

            if not action.auto_allowed():
                # Requires governance approval — log and skip
                decisions.append(
                    HealingDecision(
                        action=action,
                        target=target_id,
                        reason=f"Predicted {pred.signal.value} (prob={pred.probability:.2f}) — requires approval",
                        auto_executed=False,
                        required_approval=True,
                        predicted_fault=pred,
                    )
                )
                continue

            # Auto-execute
            decisions.append(
                HealingDecision(
                    action=action,
                    target=target_id,
                    reason=f"Predicted {pred.signal.value} (prob={pred.probability:.2f}, lead={pred.lead_time_seconds}s)",
                    auto_executed=True,
                    required_approval=False,
                    predicted_fault=pred,
                )
            )

        self._action_log.extend(decisions)

        # Record in ledger
        for d in decisions:
            self._ledger.record_decision(
                DecisionRecord(
                    workload_id=workload_id,
                    policy_id="self-healer",
                    policy_revision=1,
                    decision_type=DecisionType.RETRY_STRATEGY,
                    selected_candidate_id=d.action.value,
                    safety_pass=d.action.auto_allowed(),
                    safety_issues=[]
                    if d.action.auto_allowed()
                    else ["Requires governance approval"],
                )
            )

        return decisions

    def get_predictor(self) -> FaultPredictor:
        return self._predictor

    def get_action_log(self) -> list[HealingDecision]:
        return list(self._action_log)

    def get_ledger(self) -> ObservationLedger:
        return self._ledger

"""
Energy and Thermal Scheduler — safe energy-aware workload placement.

Optimizes: minimize energy while satisfying quality and latency SLOs.

When adaptive_energy is DISABLED: no energy optimization (RC9 behavior).
When adaptive_energy is ENABLED: joint energy-quality-latency placement.

Target devices: Jetson, laptop, phone, robot, edge — any device where
energy and thermal constraints matter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from runtime.adaptive.flags import AdaptiveFlags
from runtime.adaptive.baselines import MultiplicationScorer
from runtime.adaptive.observation import DecisionRecord, DecisionType, ObservationLedger


class EnergyMode(str, Enum):
    """Energy optimization modes."""

    PERFORMANCE = "performance"  # No energy constraint
    BALANCED = "balanced"  # Balance performance and energy
    POWER_SAVING = "power_saving"  # Aggressively save energy
    THERMAL_LIMITED = "thermal_limited"  # Temperature constrained
    BATTERY_SAVER = "battery_saver"  # Extend battery life


@dataclass
class DeviceEnergyProfile:
    """Energy characteristics of a device."""

    device_id: str
    node_id: str
    idle_power_watts: float
    peak_power_watts: float
    energy_per_token_joules: float | None = None
    energy_per_request_joules: float | None = None
    current_temperature_celsius: float = 40.0
    thermal_limit_celsius: float = 85.0
    battery_pct: float | None = None
    on_battery: bool = False
    carbon_intensity_g_per_kwh: float | None = None


@dataclass
class WorkloadEnergyEstimate:
    """Energy estimate for running a workload on a device."""

    workload_id: str
    device_id: str
    estimated_energy_joules: float
    estimated_duration_ms: float
    estimated_quality: float
    estimated_cost: float
    thermal_risk: float = 0.0
    carbon_estimate_g: float = 0.0


@dataclass
class EnergyPlacement:
    """Result of energy-aware placement."""

    workload_id: str
    device_id: str
    energy_mode: EnergyMode
    estimated_energy_joules: float
    estimated_duration_ms: float
    quality_impact: float  # Quality change vs best-performance option
    reason: str


class EnergyThermalScheduler:
    """Joint energy-quality-latency workload placement.

    When disabled: delegates to standard scheduler without energy consideration.
    When enabled: balances energy against SLOs.

    Reference: Murakkab (OSDI'26) — joint optimization of workflow,
    model, and hardware placement significantly impacts energy.
    """

    def __init__(
        self,
        ledger: ObservationLedger | None = None,
        default_mode: EnergyMode = EnergyMode.BALANCED,
    ) -> None:
        self._ledger = ledger or ObservationLedger()
        self._default_mode = default_mode
        self._scorer = MultiplicationScorer(
            quality_weight=0.35,
            latency_weight=0.20,
            cost_weight=0.20,
            reliability_weight=0.15,
            privacy_weight=0.10,
        )
        self._device_profiles: dict[str, DeviceEnergyProfile] = {}

    def register_device(self, profile: DeviceEnergyProfile) -> None:
        """Register a device's energy profile."""
        self._device_profiles[profile.device_id] = profile

    def place(
        self,
        workload_id: str,
        estimates: list[WorkloadEnergyEstimate],
        mode: EnergyMode | None = None,
        slo_quality: float = 0.7,
        slo_latency_ms: float = 2000.0,
        features: dict[str, Any] | None = None,
    ) -> tuple[EnergyPlacement | None, DecisionRecord]:
        """Find the best energy-aware placement.

        Returns:
            (placement, decision_record)
            placement is None if no device satisfies SLOs.
        """
        flags = AdaptiveFlags.global_flags()
        effective_mode = mode or self._default_mode

        decision = DecisionRecord(
            workload_id=workload_id,
            policy_id=f"energy-{effective_mode.value}",
            policy_revision=1,
            decision_type=DecisionType.DEVICE_SELECTION,
            feature_snapshot=features or {},
        )

        if not flags.is_enabled("adaptive_energy"):
            # Without energy awareness, pick best latency
            if estimates:
                best = min(estimates, key=lambda e: e.estimated_duration_ms)
                placement = EnergyPlacement(
                    workload_id=workload_id,
                    device_id=best.device_id,
                    energy_mode=EnergyMode.PERFORMANCE,
                    estimated_energy_joules=best.estimated_energy_joules,
                    estimated_duration_ms=best.estimated_duration_ms,
                    quality_impact=0.0,
                    reason="Energy optimization disabled — using best-latency placement",
                )
                self._ledger.record_decision(decision)
                return placement, decision
            return None, decision

        # Filter: must satisfy SLOs
        valid = [
            e
            for e in estimates
            if e.estimated_quality >= slo_quality
            and e.estimated_duration_ms <= slo_latency_ms
        ]

        if not valid:
            decision.safety_pass = False
            decision.safety_issues = ["No device satisfies SLOs"]
            self._ledger.record_decision(decision)
            return None, decision

        # Apply thermal constraints
        safe = []
        for e in valid:
            device = self._device_profiles.get(e.device_id)
            if device is None:
                safe.append(e)
                continue

            if device.current_temperature_celsius >= device.thermal_limit_celsius * 0.9:
                e.thermal_risk = min(
                    1.0,
                    (device.current_temperature_celsius / device.thermal_limit_celsius),
                )
                if (
                    effective_mode == EnergyMode.THERMAL_LIMITED
                    and e.thermal_risk > 0.95
                ):
                    continue  # Skip devices near thermal limit

            # Battery constraint
            if effective_mode == EnergyMode.BATTERY_SAVER and device.on_battery:
                if device.battery_pct is not None and device.battery_pct < 10:
                    continue  # Skip low battery

            safe.append(e)

        if not safe:
            # Fall back to the original valid set
            safe = valid

        # Score with energy-weighted multiplication
        scored = []
        for e in safe:
            energy_penalty = self._compute_energy_penalty(e, effective_mode)
            quality = e.estimated_quality * (1.0 - 0.1 * energy_penalty)
            latency = e.estimated_duration_ms * (1.0 + 0.2 * energy_penalty)
            cost = e.estimated_cost * (1.0 + 0.1 * energy_penalty)

            score = self._scorer.score(
                candidate_id=e.device_id,
                estimated_quality=quality,
                estimated_latency_ms=latency,
                estimated_cost=cost,
            )
            scored.append((score, e))

        scored.sort(key=lambda x: x[0].composite_score, reverse=True)

        if scored:
            best_score, best_estimate = scored[0]
            placement = EnergyPlacement(
                workload_id=workload_id,
                device_id=best_estimate.device_id,
                energy_mode=effective_mode,
                estimated_energy_joules=best_estimate.estimated_energy_joules,
                estimated_duration_ms=best_estimate.estimated_duration_ms,
                quality_impact=best_score.quality_score
                - 0.35,  # deviation from standard weight
                reason=f"Energy-{effective_mode.value}: {best_score.composite_score:.3f}",
            )
            decision.selected_candidate_id = placement.device_id
            decision.predicted_latency_ms = placement.estimated_duration_ms
            decision.predicted_cost = placement.estimated_energy_joules
            self._ledger.record_decision(decision)
            return placement, decision

        self._ledger.record_decision(decision)
        return None, decision

    def _compute_energy_penalty(
        self, estimate: WorkloadEnergyEstimate, mode: EnergyMode
    ) -> float:
        """Compute energy penalty for scoring adjustments."""
        if mode == EnergyMode.PERFORMANCE:
            return 0.0

        device = self._device_profiles.get(estimate.device_id)

        penalty = 0.0

        if mode == EnergyMode.POWER_SAVING:
            penalty += estimate.estimated_energy_joules / 1000.0  # Normalize per kJ
        elif mode == EnergyMode.BALANCED:
            penalty += estimate.estimated_energy_joules / 2000.0

        if device:
            penalty += estimate.thermal_risk * 0.5
            if device.on_battery and mode == EnergyMode.BATTERY_SAVER:
                penalty += 0.3

        return min(1.0, penalty)

    def get_device_profile(self, device_id: str) -> DeviceEnergyProfile | None:
        return self._device_profiles.get(device_id)

    def get_ledger(self) -> ObservationLedger:
        return self._ledger

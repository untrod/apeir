"""
RC10 Safe Adaptive Intelligence & Evolution Plane.

ALL features are DISABLED_BY_DEFAULT. When all flags are off, the runtime
behaves exactly as RC9 — Scheduler 1.0/2.0, static model routing, no adaptive behavior.

To enable features, set in nousd.toml:

    [experimental]
    adaptive_routing = true  # or any other feature

Or programmatically:

    from runtime.adaptive.flags import AdaptiveFlags
    AdaptiveFlags.global_flags().enable("adaptive_routing")

Safety invariant:
    No adaptive module may alter Kernel ABI, Capability boundaries,
    Approval rules, or credential policies. See ImmutableBoundaries
    in the safety envelope.
"""

from __future__ import annotations

# Core adaptive modules — all gated behind feature flags
from runtime.adaptive.flags import AdaptiveFlags, ExperimentalConfig
from runtime.adaptive.routing import AdaptiveModelRouter
from runtime.adaptive.scheduling import AdaptiveScheduler
from runtime.adaptive.context_paging import AdaptiveContextPager
from runtime.adaptive.recovery import FaultPredictor, SelfHealer
from runtime.adaptive.energy import EnergyThermalScheduler
from runtime.adaptive.personalization import Personalizer, PersonalizationLevel
from runtime.adaptive.portfolio import ModelPortfolioManager
from runtime.adaptive.observation import ObservationLedger, DecisionRecord
from runtime.adaptive.safety import SafetyEnvelope, ImmutableBoundaries
from runtime.adaptive.baselines import MultiplicationScorer, ParetoRanker

__all__ = [
    "AdaptiveFlags",
    "ExperimentalConfig",
    "AdaptiveModelRouter",
    "AdaptiveScheduler",
    "AdaptiveContextPager",
    "FaultPredictor",
    "SelfHealer",
    "EnergyThermalScheduler",
    "Personalizer",
    "PersonalizationLevel",
    "ModelPortfolioManager",
    "ObservationLedger",
    "DecisionRecord",
    "SafetyEnvelope",
    "ImmutableBoundaries",
    "MultiplicationScorer",
    "ParetoRanker",
]

# Version of the adaptive API
ADAPTIVE_API_VERSION = 1

# All adaptive features start disabled
ALL_ADAPTIVE_DISABLED_BY_DEFAULT = True

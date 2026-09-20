"""
Model Portfolio Manager — manage a portfolio of models as assets.

Nous shouldn't just know "which models exist" — it should manage a portfolio:
- Primary models (general purpose)
- Specialist models (vision, audio, embedding, code)
- Verifier models (check outputs of primary models)
- Local models (privacy-sensitive workloads)
- Remote models (complex reasoning)
- Fallback models (when primary fails)

The portfolio manager helps the Adaptive Router make informed decisions
about which model to use for which workload.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelRole(str, Enum):
    PRIMARY = "primary"  # General-purpose, main workhorse
    SPECIALIST = "specialist"  # Domain-specific (vision, audio, etc.)
    VERIFIER = "verifier"  # Checks outputs of other models
    LOCAL = "local"  # Runs on local device for privacy
    REMOTE = "remote"  # Cloud-based for complex reasoning
    FALLBACK = "fallback"  # Used when primary fails
    EXPERIMENTAL = "experimental"  # Being evaluated, not production
    RETIRED = "retired"  # No longer used


class CapabilityDomain(str, Enum):
    TEXT = "text"
    CODE = "code"
    VISION = "vision"
    AUDIO = "audio"
    EMBEDDING = "embedding"
    TOOL_USE = "tool_use"
    STRUCTURED_OUTPUT = "structured_output"
    MULTIMODAL = "multimodal"
    REASONING = "reasoning"
    RERANKING = "reranking"


@dataclass
class ModelAsset:
    """A model in the portfolio."""

    model_id: str
    provider_id: str
    role: ModelRole
    domains: list[CapabilityDomain]
    max_context_tokens: int
    estimated_quality: float
    estimated_latency_ms: float
    cost_per_1k_input: float
    cost_per_1k_output: float
    local_only: bool = False
    requires_gpu: bool = True
    supported_quantizations: list[str] = field(default_factory=list)
    license_compatible: bool = True
    data_classification_allowed: list[str] = field(default_factory=lambda: ["public"])
    verifier_compatible: bool = False  # Can it verify other models' outputs?
    cascade_capable: bool = False  # Can it be used in a cascade?
    health_status: str = "unknown"
    last_validated: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortfolioStats:
    """Summary statistics for the model portfolio."""

    total_models: int = 0
    active_models: int = 0
    primary_models: int = 0
    specialist_models: int = 0
    verifier_models: int = 0
    local_models: int = 0
    remote_models: int = 0
    fallback_models: int = 0
    experimental_models: int = 0
    retired_models: int = 0
    domains_covered: list[str] = field(default_factory=list)
    estimated_monthly_cost: float = 0.0


class ModelPortfolioManager:
    """Manage a portfolio of AI models as first-class assets.

    The portfolio informs the Adaptive Router, Energy Scheduler,
    and Cost Controller about available models and their characteristics.
    """

    def __init__(self) -> None:
        self._models: dict[str, ModelAsset] = {}
        self._lock = threading.Lock()

    def register(self, model: ModelAsset) -> None:
        """Register a model in the portfolio."""
        with self._lock:
            self._models[model.model_id] = model

    def retire(self, model_id: str, reason: str = "") -> bool:
        """Retire a model from active use."""
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                return False
            model.role = ModelRole.RETIRED
            model.metadata["retirement_reason"] = reason
            return True

    def get_model(self, model_id: str) -> ModelAsset | None:
        """Get a model by ID."""
        with self._lock:
            return self._models.get(model_id)

    def get_by_role(self, role: ModelRole) -> list[ModelAsset]:
        """Get all models with a specific role."""
        with self._lock:
            return [m for m in self._models.values() if m.role == role]

    def get_by_domain(self, domain: CapabilityDomain) -> list[ModelAsset]:
        """Get models that support a specific capability domain."""
        with self._lock:
            return [m for m in self._models.values() if domain in m.domains]

    def get_primary_chain(
        self,
        domain: CapabilityDomain,
        data_classification: str = "public",
    ) -> list[ModelAsset]:
        """Get a chain: primary → verifier → fallback for a domain.

        Returns models in order: [primary, verifier, fallback]
        """
        with self._lock:
            primary = [
                m
                for m in self._models.values()
                if m.role == ModelRole.PRIMARY
                and domain in m.domains
                and data_classification in m.data_classification_allowed
                and m.health_status in ("healthy", "degraded")
            ]
            verifier = [
                m
                for m in self._models.values()
                if m.role == ModelRole.VERIFIER
                and m.verifier_compatible
                and data_classification in m.data_classification_allowed
                and m.health_status in ("healthy", "degraded")
            ]
            fallback = [
                m
                for m in self._models.values()
                if m.role == ModelRole.FALLBACK
                and domain in m.domains
                and data_classification in m.data_classification_allowed
                and m.health_status in ("healthy", "degraded")
            ]

            result = []
            if primary:
                result.append(primary[0])
            if verifier:
                result.append(verifier[0])
            if fallback:
                result.append(fallback[0])

            return result

    def get_local_models(self) -> list[ModelAsset]:
        """Get all models that can run locally (privacy-sensitive workloads)."""
        with self._lock:
            return [m for m in self._models.values() if m.local_only]

    def get_candidates_for_workload(
        self,
        domain: CapabilityDomain,
        data_classification: str = "public",
        max_cost_per_request: float = 1.0,
        require_local: bool = False,
    ) -> list[ModelAsset]:
        """Get eligible models for a workload.

        Filters by domain, classification, cost, and locality requirements.
        """
        with self._lock:
            candidates = [
                m
                for m in self._models.values()
                if m.role not in (ModelRole.RETIRED, ModelRole.EXPERIMENTAL)
                and domain in m.domains
                and data_classification in m.data_classification_allowed
                and m.health_status in ("healthy", "degraded")
                and m.license_compatible
            ]

            if require_local:
                candidates = [m for m in candidates if m.local_only]

            if max_cost_per_request < float("inf"):
                candidates = [
                    m
                    for m in candidates
                    if (m.cost_per_1k_input + m.cost_per_1k_output * 4) / 1000
                    <= max_cost_per_request
                ]

            # Sort by quality descending
            candidates.sort(key=lambda m: m.estimated_quality, reverse=True)
            return candidates

    def compute_stats(self) -> PortfolioStats:
        """Compute portfolio summary statistics."""
        with self._lock:
            models = list(self._models.values())
            stats = PortfolioStats(
                total_models=len(models),
                active_models=sum(1 for m in models if m.role != ModelRole.RETIRED),
                primary_models=sum(1 for m in models if m.role == ModelRole.PRIMARY),
                specialist_models=sum(
                    1 for m in models if m.role == ModelRole.SPECIALIST
                ),
                verifier_models=sum(1 for m in models if m.role == ModelRole.VERIFIER),
                local_models=sum(1 for m in models if m.local_only),
                remote_models=sum(1 for m in models if not m.local_only),
                fallback_models=sum(1 for m in models if m.role == ModelRole.FALLBACK),
                experimental_models=sum(
                    1 for m in models if m.role == ModelRole.EXPERIMENTAL
                ),
                retired_models=sum(1 for m in models if m.role == ModelRole.RETIRED),
            )

            domains: set[str] = set()
            for m in models:
                domains.update(d.value for d in m.domains)
            stats.domains_covered = sorted(domains)

            return stats

    def validate_health(self, model_id: str) -> bool:
        """Placeholder for health validation — checks if model is accessible."""
        with self._lock:
            model = self._models.get(model_id)
            if model is None:
                return False
            # In production, this would probe the model endpoint
            # For RC10: mark as healthy if registered
            model.health_status = "healthy"
            return True

    def list_all(self) -> list[ModelAsset]:
        """List all models in the portfolio."""
        with self._lock:
            return list(self._models.values())

    def clear(self) -> None:
        """Clear the portfolio (for testing)."""
        with self._lock:
            self._models.clear()

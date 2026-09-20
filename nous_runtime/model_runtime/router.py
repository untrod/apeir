"""Explainable hard-constraint and weighted model routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nous_runtime.model_runtime.errors import ModelRoutingError
from nous_runtime.model_runtime.models import (
    CapabilityLevel,
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelModality,
    ModelRequest,
    PrivacyClass,
    RejectedModel,
    RouteDecision,
    RoutingMode,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


@dataclass(frozen=True)
class RoutingWeights:
    capability: float = 0.28
    modality: float = 0.15
    quality: float = 0.18
    availability: float = 0.12
    latency: float = 0.10
    cost: float = 0.07
    privacy: float = 0.10

    def __post_init__(self) -> None:
        total = sum(
            (
                self.capability,
                self.modality,
                self.quality,
                self.availability,
                self.latency,
                self.cost,
                self.privacy,
            )
        )
        if abs(total - 1.0) > 1e-9:
            raise ModelRoutingError("routing weights must sum to 1.0")


_LEVEL_SCORE = {
    CapabilityLevel.NONE: 0.0,
    CapabilityLevel.LOW: 0.33,
    CapabilityLevel.MEDIUM: 0.67,
    CapabilityLevel.HIGH: 1.0,
}

_LOCAL_ENDPOINTS = {
    ModelEndpointType.LOCAL_MODEL,
    ModelEndpointType.LOCAL_SERVICE,
}

_REMOTE_ENDPOINTS = {
    ModelEndpointType.CLOUD_API,
    ModelEndpointType.REMOTE_CLUSTER,
    ModelEndpointType.PROFESSIONAL_AGENT,
}


class ModelRouter:
    """Route requests by safety constraints before weighted preferences."""

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        *,
        weights: RoutingWeights | None = None,
    ) -> None:
        self.registry = registry
        self.weights = weights or RoutingWeights()

    def route(self, request: ModelRequest) -> RouteDecision:
        rejected: list[RejectedModel] = []
        scored: list[
            tuple[float, ModelDescriptor, ModelInstance, tuple[str, ...]]
        ] = []
        for descriptor in self.registry.enabled_descriptors():
            instances = self.registry.instances_for(descriptor.model_id)
            reasons = self._hard_rejections(
                request,
                descriptor,
                instances,
            )
            if reasons:
                rejected.append(
                    RejectedModel(descriptor.model_id, tuple(reasons))
                )
                continue
            instance = self._best_instance(instances)
            if instance is None:
                rejected.append(
                    RejectedModel(
                        descriptor.model_id,
                        ("no usable model instance",),
                    )
                )
                continue
            score, explanations = self._score(
                request,
                descriptor,
                instance,
            )
            scored.append((score, descriptor, instance, explanations))

        if not scored:
            details = "; ".join(
                f"{item.model_id}: {', '.join(item.reasons)}"
                for item in rejected
            )
            raise ModelRoutingError(
                "no model route satisfies hard constraints"
                + (f" ({details})" if details else "")
            )

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].model_id,
                item[2].instance_id,
            )
        )
        best_score, best_model, best_instance, explanations = scored[0]
        return RouteDecision(
            request_id=request.request_id,
            selected_model_id=best_model.model_id,
            selected_instance_id=best_instance.instance_id,
            fallback_model_ids=tuple(
                item[1].model_id for item in scored[1:]
            ),
            score=round(best_score, 6),
            reasons=explanations,
            rejected=tuple(rejected),
            scores={
                descriptor.model_id: round(score, 6)
                for score, descriptor, _, _ in scored
            },
        )

    def _hard_rejections(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instances: list[ModelInstance],
    ) -> list[str]:
        reasons: list[str] = []
        if descriptor.model_id in request.forbidden_models:
            reasons.append("model is forbidden by request")
        record = self.registry.get(descriptor.model_id)
        health_status = str(
            (record.health if record is not None else {}).get("status")
            or ""
        ).lower()
        if health_status in {"down", "failed", "unhealthy"}:
            reasons.append(f"model health is {health_status}")
        if (
            descriptor.license_info.get("approved") is False
            and not request.metadata.get("allow_unapproved_license", False)
        ):
            reasons.append("model license is not approved")
        if not descriptor.supports(
            request.required_capabilities,
            request.required_modalities,
        ):
            missing_capabilities = (
                request.required_capabilities - descriptor.capabilities
            )
            missing_modalities = (
                request.required_modalities - descriptor.modalities
            )
            if missing_capabilities:
                reasons.append(
                    "missing capabilities: "
                    + ", ".join(sorted(missing_capabilities))
                )
            if missing_modalities:
                reasons.append(
                    "missing modalities: "
                    + ", ".join(
                        sorted(item.value for item in missing_modalities)
                    )
                )
        if descriptor.context_length < request.min_context_length:
            reasons.append(
                "context length below required minimum "
                f"({descriptor.context_length} < "
                f"{request.min_context_length})"
            )
        if self._requires_local(request) and not descriptor.is_local:
            reasons.append("privacy or routing policy requires local execution")
        if (
            request.routing_mode is RoutingMode.REMOTE_ONLY
            and descriptor.endpoint_type not in _REMOTE_ENDPOINTS
        ):
            reasons.append("routing mode requires remote execution")
        if request.required_location:
            declared_locations = {
                str(descriptor.metadata.get("location") or "").lower(),
                str(descriptor.metadata.get("region") or "").lower(),
                *(item.node_id.lower() for item in instances),
            }
            declared_locations.discard("")
            local_match = (
                request.required_location == "local"
                and descriptor.is_local
            )
            if (
                not local_match
                and request.required_location not in declared_locations
            ):
                reasons.append(
                    "model is outside required execution location"
                )
        if request.routing_mode is RoutingMode.LOCKED:
            if not request.preferred_models:
                reasons.append("locked routing requires a preferred model")
            elif descriptor.model_id not in request.preferred_models:
                reasons.append("model is outside locked preference")
        latency = descriptor.metadata.get("latency_ms")
        if (
            request.max_latency_ms is not None
            and latency is not None
            and float(latency) > request.max_latency_ms
        ):
            reasons.append("estimated latency exceeds request limit")
        cost = descriptor.metadata.get("estimated_cost_usd")
        if (
            request.max_cost_usd is not None
            and cost is not None
            and float(cost) > request.max_cost_usd
        ):
            reasons.append("estimated cost exceeds request budget")
        if self._quality(descriptor, request) < request.quality_target:
            reasons.append("model quality is below request target")
        usable = [
            item
            for item in instances
            if item.state
            not in {
                ModelInstanceState.DISABLED,
                ModelInstanceState.FAILED,
                ModelInstanceState.UNLOADING,
            }
        ]
        if not usable:
            reasons.append("no enabled model instance")
        return reasons

    def _score(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
    ) -> tuple[float, tuple[str, ...]]:
        capability_score = (
            len(request.required_capabilities & descriptor.capabilities)
            / len(request.required_capabilities)
            if request.required_capabilities
            else 1.0
        )
        modality_score = (
            len(request.required_modalities & descriptor.modalities)
            / len(request.required_modalities)
            if request.required_modalities
            else 1.0
        )
        quality_score = self._quality(descriptor, request)
        availability_score = self._availability(instance)
        latency_score = _LEVEL_SCORE[descriptor.latency_level]
        cost_score = _LEVEL_SCORE[descriptor.cost_level]
        privacy_score = self._privacy_score(request, descriptor)
        score = (
            capability_score * self.weights.capability
            + modality_score * self.weights.modality
            + quality_score * self.weights.quality
            + availability_score * self.weights.availability
            + latency_score * self.weights.latency
            + cost_score * self.weights.cost
            + privacy_score * self.weights.privacy
        )
        explanations = [
            "all hard constraints satisfied",
            f"capability={capability_score:.2f}",
            f"modality={modality_score:.2f}",
            f"quality={quality_score:.2f}",
            f"availability={availability_score:.2f}",
            f"latency={latency_score:.2f}",
            f"cost={cost_score:.2f}",
            f"privacy={privacy_score:.2f}",
        ]
        if (
            request.routing_mode is RoutingMode.PREFERRED
            and descriptor.model_id in request.preferred_models
        ):
            score += 0.05
            explanations.append("preferred model bonus")
        return min(score, 1.0), tuple(explanations)

    @staticmethod
    def _best_instance(
        instances: Iterable[ModelInstance],
    ) -> ModelInstance | None:
        usable = [
            item
            for item in instances
            if item.state
            not in {
                ModelInstanceState.DISABLED,
                ModelInstanceState.FAILED,
                ModelInstanceState.UNLOADING,
            }
        ]
        if not usable:
            return None
        return min(
            usable,
            key=lambda item: (
                item.active_requests / item.max_concurrency,
                item.instance_id,
            ),
        )

    @staticmethod
    def _availability(instance: ModelInstance) -> float:
        if instance.state is ModelInstanceState.READY:
            return 1.0
        if instance.state is ModelInstanceState.BUSY:
            return max(
                0.2,
                1.0 - instance.active_requests / instance.max_concurrency,
            )
        if instance.state is ModelInstanceState.SATURATED:
            return 0.1
        if instance.state is ModelInstanceState.NOT_LOADED:
            return 0.55
        if instance.state is ModelInstanceState.LOADING:
            return 0.4
        return 0.0

    @staticmethod
    def _quality(
        descriptor: ModelDescriptor,
        request: ModelRequest,
    ) -> float:
        explicit = descriptor.metadata.get("quality_score")
        if explicit is not None:
            return max(0.0, min(1.0, float(explicit)))
        relevant = [descriptor.reasoning_level]
        if "coding" in request.required_capabilities:
            relevant.append(descriptor.coding_level)
        if ModelModality.IMAGE in request.required_modalities:
            relevant.append(descriptor.vision_level)
        return sum(_LEVEL_SCORE[item] for item in relevant) / len(relevant)

    @staticmethod
    def _requires_local(request: ModelRequest) -> bool:
        return (
            request.routing_mode
            in {RoutingMode.LOCAL_ONLY, RoutingMode.OFFLINE}
            or request.privacy_policy
            in {PrivacyClass.PRIVATE, PrivacyClass.RESTRICTED}
        )

    @staticmethod
    def _privacy_score(
        request: ModelRequest,
        descriptor: ModelDescriptor,
    ) -> float:
        if descriptor.is_local:
            return 1.0
        if request.privacy_policy is PrivacyClass.PUBLIC:
            return 0.8
        if request.privacy_policy is PrivacyClass.STANDARD:
            return 0.6
        return 0.0


__all__ = ["ModelRouter", "RoutingWeights"]

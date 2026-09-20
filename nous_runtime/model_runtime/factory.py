"""Build a unified gateway from existing Nous Provider registrations."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Iterable
from typing import Any

from nous_runtime.artifact import ArtifactRegistry
from nous_runtime.model_runtime.adapters import (
    LegacyProviderAdapter,
    ModelAdapterRegistry,
)
from nous_runtime.model_runtime.errors import ModelRuntimeError
from nous_runtime.model_runtime.cost_control import CostController
from nous_runtime.model_runtime.gateway import ModelGateway, NKIEnabledModelGateway
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelModality,
    PrivacyClass,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry

_LEGACY_GATEWAY_CAPABILITIES: dict[str, frozenset[str]] = {
    "reason": frozenset(
        {
            "chat",
            "completion",
            "reasoning",
            "planning",
            "review",
            "verification",
        }
    ),
    "code": frozenset({"chat", "coding", "completion"}),
    "embed": frozenset({"embedding"}),
    "vision": frozenset({"vision"}),
    "rerank": frozenset({"rerank"}),
    "transcribe": frozenset({"audio"}),
    "structured": frozenset({"structured_output"}),
    "tool": frozenset({"tool_calling"}),
}


def _gateway_capabilities(capabilities: Iterable[str]) -> frozenset[str]:
    """Translate legacy Provider capability IDs to Gateway capabilities."""
    normalized: set[str] = set()
    for capability in capabilities:
        item = str(capability).removeprefix("model.")
        normalized.add(item)
        normalized.update(_LEGACY_GATEWAY_CAPABILITIES.get(item, ()))
    return frozenset(normalized)


def build_gateway_from_providers(
    providers: Iterable[Any] | None = None,
    *,
    artifact_registry: ArtifactRegistry | None = None,
    allow_direct: bool = False,
) -> ModelGateway:
    """Place existing Provider objects behind the unified Gateway.

    Kernel execution is the production default. The direct provider path is
    retained only for explicit compatibility callers and isolated tests.
    """
    from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

    provider_objects = [] if no_intelligence_enabled() else (
        list(providers) if providers is not None else _installed_providers()
    )
    registry = ModelRuntimeRegistry()
    adapters = ModelAdapterRegistry()
    for provider in provider_objects:
        provider_id = str(getattr(provider, "provider_id", "") or "").strip()
        if not provider_id:
            raise ModelRuntimeError("existing Provider is missing provider_id")
        adapter = LegacyProviderAdapter(
            provider,
            backend_id=provider_id,
        )
        adapters.register(adapter)
        model_name = str(getattr(provider, "model", "") or provider_id)
        capabilities = tuple(str(item) for item in provider.list_capabilities())
        normalized_capabilities = _gateway_capabilities(capabilities)
        model_capabilities: dict[str, set[str]] = {
            model_name: set(normalized_capabilities)
        }
        for capability, target_model in dict(
            getattr(provider, "capability_models", {}) or {}
        ).items():
            target = str(target_model).strip()
            if not target:
                continue
            mapped = set(_gateway_capabilities((str(capability),)))
            routed = set(mapped)
            if routed & {"reasoning", "coding", "tool_calling", "structured_output"}:
                routed.add("chat")
            model_capabilities.setdefault(target, set()).update(routed)
            if target != model_name:
                model_capabilities[model_name].difference_update(mapped)

        is_local = _provider_is_local(provider)
        provider_name = str(getattr(provider, "provider_name", "") or provider_id)
        for routed_model, routed_capabilities in model_capabilities.items():
            model_id = (
                routed_model
                if "/" in routed_model
                else f"{provider_id}/{routed_model}"
            )
            modalities = {ModelModality.TEXT}
            if "vision" in routed_capabilities:
                modalities.add(ModelModality.IMAGE)
            if "audio" in routed_capabilities:
                modalities.add(ModelModality.AUDIO)
            if "embedding" in routed_capabilities:
                modalities.add(ModelModality.EMBEDDING)
            if "rerank" in routed_capabilities:
                modalities.add(ModelModality.RERANK)
            descriptor = ModelDescriptor(
                model_id=model_id,
                display_name=(
                    provider_name
                    if routed_model == model_name
                    else f"{provider_name} ({routed_model})"
                ),
                provider_id=provider_id,
                endpoint_type=(
                    ModelEndpointType.LOCAL_SERVICE
                    if is_local
                    else ModelEndpointType.CLOUD_API
                ),
                modalities=frozenset(modalities),
                capabilities=frozenset(routed_capabilities),
                context_length=int(getattr(provider, "context_window", 0) or 0),
                tool_calling="tool_calling" in routed_capabilities,
                structured_output="structured_output" in routed_capabilities,
                privacy_class=(
                    PrivacyClass.PRIVATE if is_local else PrivacyClass.STANDARD
                ),
                metadata={
                    "legacy_provider": True,
                    "provider_model": routed_model,
                    "default_provider_model": routed_model == model_name,
                },
            )
            registry.register(descriptor)
            registry.enable(model_id)
            suffix = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:12]
            registry.register_instance(
                ModelInstance(
                    instance_id=(
                        f"{provider_id}-default"
                        if routed_model == model_name
                        else f"{provider_id}-{suffix}"
                    ),
                    model_id=model_id,
                    node_id="local" if is_local else "remote",
                    backend=provider_id,
                    state=ModelInstanceState.READY,
                    max_concurrency=int(
                        getattr(provider, "max_concurrency", 1) or 1
                    ),
                )
            )
    if allow_direct:
        return ModelGateway(registry, adapters, artifact_registry=artifact_registry)
    endpoint = os.environ.get("NOUS_KERNEL_ENDPOINT", "").strip() or None
    return NKIEnabledModelGateway(
        registry,
        adapters,
        artifact_registry=artifact_registry,
        nki_endpoint=endpoint,
        strict_nki=True,
        cost_controller=CostController.from_environment(),
    )


def _installed_providers() -> list[Any]:
    from nous_runtime.compat.provider import get_provider, list_providers

    providers = []
    for item in list_providers():
        provider_id = str(item.get("provider_id") or item.get("name") or "")
        provider = get_provider(provider_id)
        if provider is not None:
            providers.append(provider)
    return providers


def _provider_is_local(provider: Any) -> bool:
    locality = str(getattr(provider, "locality", "") or "").lower()
    if locality:
        return locality in {"local", "embedded", "on_device"}
    provider_id = str(getattr(provider, "provider_id", "") or "").lower()
    endpoint = str(getattr(provider, "endpoint", "") or "").lower()
    return any(
        marker in provider_id or marker in endpoint
        for marker in (
            "ollama",
            "llama.cpp",
            "localhost",
            "127.0.0.1",
            "local",
        )
    )


class ModelGatewayService:
    """Process-level gateway holder for incremental subsystem migration."""

    def __init__(self) -> None:
        self._gateway: ModelGateway | None = None
        self._lock = threading.RLock()

    def configure(self, gateway: ModelGateway) -> ModelGateway:
        if not isinstance(gateway, ModelGateway):
            raise ModelRuntimeError("gateway must be a ModelGateway")
        with self._lock:
            self._gateway = gateway
        return gateway

    def get(self, *, required: bool = True) -> ModelGateway | None:
        with self._lock:
            gateway = self._gateway
        if gateway is None and required:
            raise ModelRuntimeError("unified model gateway is not configured")
        return gateway

    def configure_from_providers(
        self,
        providers: Iterable[Any] | None = None,
        *,
        artifact_registry: ArtifactRegistry | None = None,
        allow_direct: bool = False,
    ) -> ModelGateway:
        return self.configure(
            build_gateway_from_providers(
                providers,
                artifact_registry=artifact_registry,
                allow_direct=allow_direct,
            )
        )

    def clear(self) -> None:
        with self._lock:
            self._gateway = None


gateway_service = ModelGatewayService()


__all__ = [
    "ModelGatewayService",
    "build_gateway_from_providers",
    "gateway_service",
]

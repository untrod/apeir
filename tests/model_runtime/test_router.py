from __future__ import annotations

import pytest

from nous_runtime.model_runtime import (
    CapabilityLevel,
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelModality,
    ModelRequest,
    ModelRouter,
    ModelRoutingError,
    ModelRuntimeRegistry,
    PrivacyClass,
    RoutingMode,
)


def add_model(
    registry: ModelRuntimeRegistry,
    model_id: str,
    *,
    local: bool,
    quality: CapabilityLevel,
    backend: str = "mock",
) -> None:
    registry.register(
        ModelDescriptor(
            model_id=model_id,
            display_name=model_id,
            provider_id=backend,
            endpoint_type=(
                ModelEndpointType.LOCAL_SERVICE
                if local
                else ModelEndpointType.CLOUD_API
            ),
            modalities=frozenset({ModelModality.TEXT}),
            capabilities=frozenset({"reasoning", "coding"}),
            context_length=128_000,
            reasoning_level=quality,
            coding_level=quality,
            privacy_class=(
                PrivacyClass.PRIVATE
                if local
                else PrivacyClass.STANDARD
            ),
        )
    )
    registry.enable(model_id)
    registry.register_instance(
        ModelInstance(
            instance_id=f"{model_id}-0",
            model_id=model_id,
            node_id="node",
            backend=backend,
            state=ModelInstanceState.READY,
            max_concurrency=2,
        )
    )


def test_router_applies_privacy_as_hard_constraint() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "cloud", local=False, quality=CapabilityLevel.HIGH)
    add_model(registry, "local", local=True, quality=CapabilityLevel.MEDIUM)
    decision = ModelRouter(registry).route(
        ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            privacy_policy=PrivacyClass.PRIVATE,
        )
    )
    assert decision.selected_model_id == "local"
    assert decision.rejected[0].model_id == "cloud"
    assert "requires local" in decision.rejected[0].reasons[0]


def test_router_is_explainable_and_honors_preference() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "a", local=False, quality=CapabilityLevel.HIGH)
    add_model(registry, "b", local=False, quality=CapabilityLevel.HIGH)
    decision = ModelRouter(registry).route(
        ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"coding"}),
            preferred_models=("b",),
            routing_mode=RoutingMode.PREFERRED,
        )
    )
    assert decision.selected_model_id == "b"
    assert "preferred model bonus" in decision.reasons
    assert set(decision.scores) == {"a", "b"}


def test_router_reports_hard_constraint_failures() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "text", local=True, quality=CapabilityLevel.HIGH)
    with pytest.raises(ModelRoutingError, match="missing modalities"):
        ModelRouter(registry).route(
            ModelRequest(
                task_id="task",
                required_modalities=frozenset({ModelModality.VIDEO}),
                routing_mode=RoutingMode.OFFLINE,
            )
        )


def test_router_rejects_unhealthy_unapproved_and_wrong_location() -> None:
    registry = ModelRuntimeRegistry()
    registry.register(
        ModelDescriptor(
            model_id="unsafe",
            display_name="unsafe",
            provider_id="mock",
            endpoint_type=ModelEndpointType.CLOUD_API,
            capabilities=frozenset({"reasoning"}),
            license_info={"approved": False},
            metadata={"region": "us"},
        )
    )
    registry.enable("unsafe")
    registry.register_instance(
        ModelInstance(
            instance_id="unsafe-0",
            model_id="unsafe",
            node_id="us",
            backend="mock",
            state=ModelInstanceState.READY,
        )
    )
    registry.update_health("unsafe", {"status": "down"})
    with pytest.raises(ModelRoutingError) as error:
        ModelRouter(registry).route(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
                required_location="eu",
            )
        )
    message = str(error.value)
    assert "health is down" in message
    assert "license is not approved" in message
    assert "outside required execution location" in message

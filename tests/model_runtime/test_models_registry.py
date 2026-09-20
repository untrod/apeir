from __future__ import annotations

import json

import pytest

from nous_runtime.model_runtime import (
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelLifecycleState,
    ModelModality,
    ModelRegistryError,
    ModelRequest,
    ModelRuntimeRegistry,
    ModelRuntimeError,
    PrivacyClass,
    ResourceRequirements,
    RoutingMode,
)


def descriptor(model_id: str = "local-code") -> ModelDescriptor:
    return ModelDescriptor(
        model_id=model_id,
        display_name="Local Code",
        provider_id="ollama",
        endpoint_type=ModelEndpointType.LOCAL_SERVICE,
        modalities=frozenset(
            {ModelModality.TEXT, ModelModality.IMAGE}
        ),
        capabilities=frozenset({"reasoning", "coding"}),
        context_length=32_000,
        tool_calling=True,
        structured_output=True,
        privacy_class=PrivacyClass.PRIVATE,
        resource_requirements=ResourceRequirements(
            memory_mb=4096,
            vram_mb=2048,
            disk_mb=8192,
        ),
    )


def test_descriptor_and_request_round_trip() -> None:
    original = descriptor()
    restored = ModelDescriptor.from_dict(original.to_dict())
    assert restored == original
    assert restored.is_local is True
    assert restored.supports(
        {"coding"},
        {ModelModality.TEXT},
    )

    request = ModelRequest(
        task_id="task-1",
        required_capabilities=frozenset({"coding"}),
        required_modalities=frozenset({"text", "image"}),
        messages=({"role": "user", "content": "hello"},),
        preferred_models=("local-code",),
        routing_mode=RoutingMode.PREFERRED,
        privacy_policy=PrivacyClass.PRIVATE,
    )
    assert ModelRequest.from_dict(request.to_dict()) == request
    zero_quality = ModelRequest(task_id="task-0", quality_target=0.0)
    assert (
        ModelRequest.from_dict(zero_quality.to_dict()).quality_target
        == 0.0
    )


def test_registry_lifecycle_instances_and_persistence(tmp_path) -> None:
    path = tmp_path / "models.json"
    registry = ModelRuntimeRegistry(path)
    registry.register(descriptor())
    registry.enable("local-code")
    instance = registry.register_instance(
        ModelInstance(
            instance_id="local-code-0",
            model_id="local-code",
            node_id="desktop",
            backend="ollama",
            state=ModelInstanceState.READY,
        )
    )
    registry.update_health("local-code", {"status": "ok"})

    restored = ModelRuntimeRegistry(path)
    assert restored.require("local-code").state is ModelLifecycleState.ENABLED
    assert restored.require("local-code").health == {"status": "ok"}
    assert restored.get_instance(instance.instance_id) is not None
    assert [
        item.instance_id
        for item in restored.instances_for("local-code")
    ] == ["local-code-0"]
    restored.remove_instance("local-code-0")
    assert restored.instances_for("local-code") == []
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_registry_rejects_invalid_lifecycle_transition() -> None:
    registry = ModelRuntimeRegistry()
    registry.register(
        descriptor(),
        state=ModelLifecycleState.DISCOVERED,
    )
    with pytest.raises(ModelRegistryError):
        registry.enable("local-code")


def test_deserialization_does_not_hide_invalid_zero_limits() -> None:
    with pytest.raises(ModelRuntimeError, match="max_concurrency"):
        ModelInstance.from_dict(
            {
                "instance_id": "instance",
                "model_id": "model",
                "node_id": "node",
                "backend": "mock",
                "max_concurrency": 0,
            }
        )
    with pytest.raises(ModelRuntimeError, match="timeout_s"):
        ModelRequest.from_dict({"task_id": "task", "timeout_s": 0})


def test_registry_recovers_transient_instance_state_after_restart(
    tmp_path,
) -> None:
    path = tmp_path / "models.json"
    registry = ModelRuntimeRegistry(path)
    registry.register(descriptor())
    registry.enable("local-code")
    instance = registry.register_instance(
        ModelInstance(
            instance_id="local-code-0",
            model_id="local-code",
            node_id="desktop",
            backend="mock",
            state=ModelInstanceState.SATURATED,
            active_requests=1,
        )
    )
    registry.flush()
    assert instance.active_requests == 1

    recovered = ModelRuntimeRegistry(path).get_instance("local-code-0")
    assert recovered is not None
    assert recovered.state is ModelInstanceState.READY
    assert recovered.active_requests == 0
    assert recovered.metadata["recovered_transient_state"] is True

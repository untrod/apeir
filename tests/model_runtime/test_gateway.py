from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from nous_runtime.artifact import ArtifactRegistry, ArtifactType
from nous_runtime.model_runtime import (
    CapabilityLevel,
    MockModelAdapter,
    ModelAdapterRegistry,
    ModelDescriptor,
    ModelEndpointType,
    ModelGateway,
    ModelInstance,
    ModelInstanceState,
    ModelInvocationError,
    ModelModality,
    ModelRequest,
    ModelRuntimeRegistry,
    ParallelInvocationPolicy,
    PrivacyClass,
    build_gateway_from_providers,
    capture_model_runtime,
)


def add_model(
    registry: ModelRuntimeRegistry,
    model_id: str,
    backend: str,
) -> None:
    registry.register(
        ModelDescriptor(
            model_id=model_id,
            display_name=model_id,
            provider_id=backend,
            endpoint_type=ModelEndpointType.LOCAL_SERVICE,
            modalities=frozenset({ModelModality.TEXT}),
            capabilities=frozenset({"reasoning"}),
            reasoning_level=CapabilityLevel.HIGH,
        )
    )
    registry.enable(model_id)
    registry.register_instance(
        ModelInstance(
            instance_id=f"{model_id}-0",
            model_id=model_id,
            node_id="desktop",
            backend=backend,
            state=ModelInstanceState.NOT_LOADED,
        )
    )


def test_gateway_falls_back_and_records_safe_observability() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "a", "failing")
        add_model(registry, "b", "working")
        failing = MockModelAdapter(failures_before_success=10)
        failing.backend_id = "failing"
        working = MockModelAdapter(content="done")
        working.backend_id = "working"
        adapters = ModelAdapterRegistry()
        adapters.register(failing)
        adapters.register(working)
        artifacts = ArtifactRegistry()
        gateway = ModelGateway(
            registry,
            adapters,
            artifact_registry=artifacts,
            max_attempts=2,
        )
        response = await gateway.invoke(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
                messages=(
                    {"role": "user", "content": "private prompt"},
                ),
            )
        )
        assert response.model_id == "b"
        assert response.content == "done"
        assert any(
            event.event_type == "model.invoke.failed"
            for event in gateway.events
        )
        request_artifact = artifacts.list(ArtifactType.MODEL_REQUEST)[0]
        assert "private prompt" not in str(request_artifact.metadata)
        assert artifacts.list(ArtifactType.ROUTE_DECISION)
        assert artifacts.list(ArtifactType.MODEL_METRICS)

    asyncio.run(scenario())


def test_gateway_timeout_cancels_adapter_and_releases_lease() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "slow", "slow")
        adapter = MockModelAdapter(content="late", delay_s=0.1)
        adapter.backend_id = "slow"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        request = ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            timeout_s=0.01,
        )
        with pytest.raises(ModelInvocationError, match="timed out"):
            await gateway.invoke(request)
        assert request.request_id in adapter.cancelled
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_gateway_retries_same_model_before_fallback() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "retry", "retry")
        adapter = MockModelAdapter(
            content="recovered",
            failures_before_success=1,
        )
        adapter.backend_id = "retry"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)
        gateway = ModelGateway(
            registry,
            adapters,
            max_retries_per_model=1,
        )
        response = await gateway.invoke(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
            )
        )
        assert response.content == "recovered"
        assert len(adapter.invocations) == 2

    asyncio.run(scenario())


def test_observability_failure_is_recorded_without_losing_response() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "model", "mock")
        adapters = ModelAdapterRegistry()
        adapters.register(MockModelAdapter(content="ok"))

        def failing_sink(_event) -> None:
            raise RuntimeError("sink unavailable")

        gateway = ModelGateway(
            registry,
            adapters,
            event_sink=failing_sink,
        )
        response = await gateway.invoke(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
            )
        )
        assert response.content == "ok"
        assert any(
            item.event_type == "model.observability.failed"
            for item in gateway.events
        )

    asyncio.run(scenario())


def test_gateway_stream_holds_one_route() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "stream", "stream")
        adapter = MockModelAdapter(content="one two")
        adapter.backend_id = "stream"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        chunks = [
            chunk
            async for chunk in gateway.stream(
                ModelRequest(
                    task_id="task",
                    required_capabilities=frozenset({"reasoning"}),
                    stream=True,
                )
            )
        ]
        assert chunks == ["one", "two"]
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_closing_stream_cancels_backend_and_releases_lease() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "stream", "stream")
        adapter = MockModelAdapter(content="one two")
        adapter.backend_id = "stream"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        request = ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            stream=True,
        )
        stream = gateway.stream(request)
        assert await anext(stream) == "one"
        await stream.aclose()
        assert request.request_id in adapter.cancelled
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_gateway_parallel_fan_out_is_bounded_and_ordered() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        adapters = ModelAdapterRegistry()
        for model_id, delay in (("a", 0.0), ("b", 0.0), ("c", 0.2)):
            add_model(registry, model_id, model_id)
            adapter = MockModelAdapter(
                content=model_id,
                delay_s=delay,
            )
            adapter.backend_id = model_id
            adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        result = await gateway.invoke_parallel(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
                timeout_s=1,
            ),
            policy=ParallelInvocationPolicy(
                max_candidates=3,
                max_concurrency=3,
                timeout_s=0.05,
                min_successes=2,
            ),
        )
        assert [item.model_id for item in result.responses] == ["a", "b"]
        assert result.cancelled_models == ("c",)
        assert result.successful is True

    asyncio.run(scenario())


def test_gateway_parallel_cancels_remaining_work_at_budget() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        adapters = ModelAdapterRegistry()
        for model_id in ("a", "b"):
            add_model(registry, model_id, model_id)
            adapter = MockModelAdapter(
                content=model_id,
                cost_usd=1.0,
            )
            adapter.backend_id = model_id
            adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        result = await gateway.invoke_parallel(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
            ),
            policy=ParallelInvocationPolicy(
                max_candidates=2,
                max_concurrency=1,
                max_total_cost_usd=1.0,
            ),
        )
        assert [item.model_id for item in result.responses] == ["a"]
        assert result.cancelled_models == ("b",)
        assert result.total_cost_usd == 1.0
        assert "budget exhausted" in result.failures[-1]

    asyncio.run(scenario())


def test_existing_provider_executes_behind_unified_gateway() -> None:
    class ExistingProvider:
        provider_id = "existing"
        provider_name = "Existing"
        model = "reasoner"
        locality = "local"

        @staticmethod
        def list_capabilities() -> list[str]:
            return ["model.reason"]

        @staticmethod
        def health() -> dict[str, str]:
            return {"status": "ok"}

        @staticmethod
        def invoke(capability_id: str, **params):
            return {
                "ok": True,
                "content": (
                    capability_id,
                    params["messages"][0]["content"],
                ),
            }

    async def scenario() -> None:
        gateway = build_gateway_from_providers(
            [ExistingProvider()], allow_direct=True
        )
        response = await gateway.invoke(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reason"}),
                messages=({"role": "user", "content": "hello"},),
                privacy_policy=PrivacyClass.PRIVATE,
            )
        )
        assert response.model_id == "existing/reasoner"
        assert response.content == ("model.reason", "hello")

    asyncio.run(scenario())


def test_gateway_sync_boundary_supports_repeated_calls() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "sync", "sync")
    adapter = MockModelAdapter(content="ok")
    adapter.backend_id = "sync"
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    gateway = ModelGateway(registry, adapters)
    def request(task_id: str) -> ModelRequest:
        return ModelRequest(
            task_id=task_id,
            required_capabilities=frozenset({"reasoning"}),
        )

    assert gateway.invoke_sync(request("one")).content == "ok"
    assert gateway.invoke_sync(request("two")).content == "ok"
    gateway.close_sync_bridge()


def test_gateway_sync_boundary_is_safe_for_concurrent_callers() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "sync", "sync")
    instance = registry.get_instance("sync-0")
    instance.max_concurrency = 2
    adapter = MockModelAdapter(content="ok", delay_s=0.01)
    adapter.backend_id = "sync"
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    gateway = ModelGateway(registry, adapters)

    def invoke(index: int) -> str:
        return gateway.invoke_sync(
            ModelRequest(
                task_id=f"task-{index}",
                required_capabilities=frozenset({"reasoning"}),
            )
        ).content

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert list(pool.map(invoke, range(4))) == ["ok"] * 4
    finally:
        gateway.close_sync_bridge()


def test_gateway_history_is_bounded_and_inspector_reports_metrics() -> None:
    registry = ModelRuntimeRegistry()
    add_model(registry, "inspect", "inspect")
    adapter = MockModelAdapter(
        content="ok",
        cost_usd=0.25,
        total_tokens=12,
    )
    adapter.backend_id = "inspect"
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    gateway = ModelGateway(
        registry,
        adapters,
        event_history_limit=2,
    )
    gateway.invoke_sync(
        ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
        )
    )
    snapshot = capture_model_runtime(gateway)
    assert len(gateway.events) == 2
    assert snapshot.healthy is True
    assert snapshot.metrics["requests"] == 1
    assert snapshot.metrics["responses"] == 1
    assert snapshot.metrics["tokens"] == 12
    assert snapshot.metrics["cost_usd"] == 0.25
    assert snapshot.active_request_ids == ()

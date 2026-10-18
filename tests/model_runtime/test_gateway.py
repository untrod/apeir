from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import nous_runtime.model_runtime.gateway as gateway_module

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


@pytest.mark.parametrize(
    "field,invalid",
    [
        (field, invalid)
        for field in ("max_candidates", "max_concurrency", "min_successes")
        for invalid in (True, 0, -1, 1.5, "2")
    ]
    + [
        (field, invalid)
        for field in ("max_total_cost_usd", "timeout_s")
        for invalid in (True, float("nan"), float("inf"), float("-inf"), "1")
    ]
    + [("max_total_tokens", invalid) for invalid in (True, -1, 1.5, "2")],
)
def test_parallel_policy_rejects_ambiguous_numeric_bounds(field, invalid):
    with pytest.raises(ModelInvocationError):
        ParallelInvocationPolicy(**{field: invalid})


@pytest.mark.parametrize("field", ["max_total_cost_usd", "max_total_tokens"])
def test_parallel_zero_budget_prevents_first_provider_dispatch(field):
    async def scenario():
        registry = ModelRuntimeRegistry()
        add_model(registry, "a", "a")
        adapters = ModelAdapterRegistry()
        adapter = MockModelAdapter(content="must not execute")
        adapter.backend_id = "a"
        adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        result = await gateway.invoke_parallel(
            ModelRequest(task_id="zero-budget"),
            policy=ParallelInvocationPolicy(**{field: 0}),
        )
        assert adapter.invocations == []
        assert gateway.scheduler.active_leases() == ()
        assert not result.successful and result.responses == ()
        assert result.cancelled_models == ("a",)
        assert result.total_cost_usd == result.total_tokens == 0
        assert "parallel invocation budget exhausted" in result.failures

    asyncio.run(scenario())


def test_gateway_falls_back_and_records_safe_observability() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "a", "failing")
        add_model(registry, "b", "working")

        class SetupFailingAdapter(MockModelAdapter):
            async def load(self, instance):
                raise ConnectionError("fake setup failed before dispatch")

        failing = SetupFailingAdapter()
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
                messages=({"role": "user", "content": "private prompt"},),
            )
        )
        assert response.model_id == "b"
        assert response.content == "done"
        assert failing.invocations == []
        assert len(working.invocations) == 1
        assert any(
            event.event_type == "model.invoke.failed" for event in gateway.events
        )
        request_artifact = artifacts.list(ArtifactType.MODEL_REQUEST)[0]
        assert "private prompt" not in str(request_artifact.metadata)
        assert artifacts.list(ArtifactType.ROUTE_DECISION)
        assert artifacts.list(ArtifactType.MODEL_METRICS)

    asyncio.run(scenario())


def test_gateway_timeout_cancels_adapter_and_releases_lease(monkeypatch) -> None:
    # This case targets an in-flight provider deadline, not variable routing I/O.
    # Only Gateway accounting is controlled; asyncio's 10ms timeout remains real.
    clock = {"now": 0.0}
    monkeypatch.setattr(
        gateway_module, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )

    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "slow", "slow")
        adapter = MockModelAdapter(content="late", delay_s=0.1)
        adapter.backend_id = "slow"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)

        def provider_timeout_exhausts_deadline(event):
            if event.event_type == "model.invoke.failed":
                clock["now"] = 0.02

        gateway = ModelGateway(
            registry, adapters, event_sink=provider_timeout_exhausts_deadline
        )
        request = ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            timeout_s=0.01,
        )
        with pytest.raises(ModelInvocationError, match="timed out"):
            await gateway.invoke(request)
        assert adapter.invocations == [request.request_id]
        assert request.request_id in adapter.cancelled
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_gateway_expired_before_dispatch_never_invokes_or_leases(monkeypatch) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(
        gateway_module, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )

    async def scenario():
        registry = ModelRuntimeRegistry()
        add_model(registry, "not-dispatched", "not-dispatched")
        adapter = MockModelAdapter(content="must not execute")
        adapter.backend_id = "not-dispatched"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)

        def routing_exhausts_deadline(event):
            if event.event_type == "model.route.selected":
                clock["now"] = 0.02

        gateway = ModelGateway(registry, adapters, event_sink=routing_exhausts_deadline)
        request = ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            timeout_s=0.01,
        )
        with pytest.raises(ModelInvocationError, match="timed out"):
            await gateway.invoke(request)
        assert adapter.invocations == []
        assert adapter.cancelled == set()
        assert gateway.scheduler.active_leases() == ()
        assert not any(
            event.event_type == "model.invoke.completed" for event in gateway.events
        )

    asyncio.run(scenario())


def test_gateway_retries_same_model_before_fallback() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        add_model(registry, "retry", "retry")
        adapter = MockModelAdapter(content="recovered")
        adapter.backend_id = "retry"
        adapters = ModelAdapterRegistry()
        adapters.register(adapter)
        gateway = ModelGateway(
            registry,
            adapters,
            max_retries_per_model=1,
        )
        prepare = gateway._ensure_loaded
        preparation_calls = 0

        async def fail_first_preparation(instance, selected):
            nonlocal preparation_calls
            preparation_calls += 1
            if preparation_calls == 1:
                raise ConnectionError("fake setup failed before dispatch")
            await prepare(instance, selected)

        gateway._ensure_loaded = fail_first_preparation
        response = await gateway.invoke(
            ModelRequest(
                task_id="task",
                required_capabilities=frozenset({"reasoning"}),
            )
        )
        assert response.content == "recovered"
        assert preparation_calls == 2
        assert len(adapter.invocations) == 1

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
            item.event_type == "model.observability.failed" for item in gateway.events
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
        release_first = asyncio.Event()
        active = peak_active = 0
        completion_order = []
        child_request_ids = set()
        original_request = ModelRequest(
            task_id="task",
            required_capabilities=frozenset({"reasoning"}),
            timeout_s=1,
            metadata={"work_id": "original-work"},
        )

        class OrderedAdapter(MockModelAdapter):
            async def invoke(self, request, descriptor, instance):
                nonlocal active, peak_active
                active += 1
                peak_active = max(peak_active, active)
                child_request_ids.add(request.request_id)
                assert request.request_id != original_request.request_id
                assert request.metadata == {
                    "work_id": "original-work",
                    "parent_request_id": original_request.request_id,
                }
                assert request.task_id == original_request.task_id
                assert 0 < request.timeout_s <= original_request.timeout_s
                try:
                    if descriptor.model_id == "a":
                        await release_first.wait()
                    response = await super().invoke(request, descriptor, instance)
                    completion_order.append(descriptor.model_id)
                    if descriptor.model_id == "c":
                        release_first.set()
                    return response
                finally:
                    active -= 1

        for model_id in ("a", "b", "c"):
            add_model(registry, model_id, model_id)
            adapter = OrderedAdapter(content=model_id)
            adapter.backend_id = model_id
            adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        result = await gateway.invoke_parallel(
            original_request,
            policy=ParallelInvocationPolicy(
                max_candidates=3,
                max_concurrency=2,
                min_successes=3,
            ),
        )
        # Ordering/concurrency are coordinated by events, not an assumption that
        # routing, loading and callbacks finish within a 50ms wall-clock budget.
        assert completion_order == ["b", "c", "a"]
        assert peak_active == 2
        assert active == 0
        assert len(child_request_ids) == 3
        assert original_request.metadata == {"work_id": "original-work"}
        assert original_request.timeout_s == 1
        assert [item.model_id for item in result.responses] == ["a", "b", "c"]
        assert result.cancelled_models == ()
        assert result.failures == ()
        assert result.successful is True
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_gateway_parallel_deadline_cancels_pending_and_releases_leases() -> None:
    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        adapters = ModelAdapterRegistry()

        class WaitingAdapter(MockModelAdapter):
            async def invoke(self, request, descriptor, instance):
                self.invocations.append(request.request_id)
                await asyncio.Event().wait()
                raise AssertionError("pending invocation must be cancelled")

        for model_id in ("a", "b", "c"):
            add_model(registry, model_id, model_id)
            adapter = WaitingAdapter()
            adapter.backend_id = model_id
            adapters.register(adapter)
        gateway = ModelGateway(registry, adapters)
        result = await gateway.invoke_parallel(
            ModelRequest(task_id="task", timeout_s=1),
            policy=ParallelInvocationPolicy(
                max_candidates=3,
                max_concurrency=3,
                timeout_s=0.05,
                min_successes=2,
            ),
        )
        assert result.responses == ()
        terminal_models = set(result.cancelled_models)
        terminal_models.update(
            failure.split(":", 1)[0]
            for failure in result.failures
            if ":" in failure and "timed out" in failure
        )
        assert terminal_models == {"a", "b", "c"}
        assert "parallel invocation did not reach minimum successes" in result.failures
        assert result.successful is False
        for adapter in adapters.list():
            assert adapter.cancelled == set(adapter.invocations)
        assert gateway.scheduler.active_leases() == ()
        assert gateway._active == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("model_ids", [("a",), ("a", "b", "c")])
def test_gateway_parallel_expired_during_routing_never_dispatches(
    monkeypatch, model_ids
) -> None:
    clock = {"now": 0.0}
    monkeypatch.setattr(
        gateway_module, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )

    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        adapters = ModelAdapterRegistry()
        for model_id in model_ids:
            add_model(registry, model_id, model_id)
            adapter = MockModelAdapter(
                content="must not dispatch after parallel expiry"
            )
            adapter.backend_id = model_id
            adapters.register(adapter)

        def exhaust_parallel_deadline(event):
            if event.event_type == "model.route.selected":
                clock["now"] = 0.075

        gateway = ModelGateway(registry, adapters, event_sink=exhaust_parallel_deadline)
        result = await gateway.invoke_parallel(
            ModelRequest(task_id="task", timeout_s=1),
            policy=ParallelInvocationPolicy(max_candidates=3, timeout_s=0.05),
        )
        assert result.responses == ()
        assert result.successful is False
        for adapter in adapters.list():
            assert adapter.invocations == []
            assert adapter.cancelled == set()
        assert gateway.scheduler.active_leases() == ()
        assert not any(
            event.event_type == "model.invoke.completed" for event in gateway.events
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("minimum, successful", [(1, True), (2, False)])
def test_gateway_parallel_partial_result_honors_minimum(
    tmp_path, minimum, successful
) -> None:
    from nous_runtime.model_runtime.cost_control import (
        CostController,
        Pricing,
        PricingCatalog,
    )

    async def scenario() -> None:
        registry = ModelRuntimeRegistry()
        adapters = ModelAdapterRegistry()
        add_model(registry, "a", "a")
        add_model(registry, "b", "b")
        working = MockModelAdapter(content="partial", cost_usd=0.25, total_tokens=7)
        working.backend_id = "a"
        adapters.register(working)

        class SetupFailingAdapter(MockModelAdapter):
            async def load(self, instance):
                raise ConnectionError("controlled failure before Provider dispatch")

        failing = SetupFailingAdapter()
        failing.backend_id = "b"
        adapters.register(failing)
        controller = CostController(
            tmp_path / "usage.sqlite3",
            pricing=PricingCatalog({"a/a": Pricing(1, 2), "b/b": Pricing(1, 2)}),
        )
        gateway = ModelGateway(
            registry, adapters, max_retries_per_model=0, cost_controller=controller
        )
        result = await gateway.invoke_parallel(
            ModelRequest(task_id="task"),
            policy=ParallelInvocationPolicy(min_successes=minimum),
        )
        assert result.successful is successful
        assert [response.model_id for response in result.responses] == ["a"]
        assert result.selected_response.content == "partial"
        assert result.total_cost_usd == 0.25
        assert result.total_tokens == 7
        assert failing.invocations == []
        assert gateway.scheduler.active_leases() == ()
        assert (
            "parallel invocation did not reach minimum successes" in result.failures
        ) is (not successful)
        completed = next(
            event
            for event in gateway.events
            if event.event_type == "model.parallel.completed"
        )
        assert completed.payload["success_count"] == 1
        assert completed.payload["min_successes"] == minimum
        assert completed.payload["successful"] is successful

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
        gateway = build_gateway_from_providers([ExistingProvider()], allow_direct=True)
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

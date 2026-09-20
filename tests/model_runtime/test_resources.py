from __future__ import annotations

import asyncio

import pytest

from nous_runtime.model_runtime import (
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelResourceError,
    ModelResourceScheduler,
    ModelRuntimeRegistry,
)


def runtime(
    *,
    state: ModelInstanceState = ModelInstanceState.NOT_LOADED,
    memory_mb: int = 512,
) -> tuple[ModelRuntimeRegistry, ModelResourceScheduler]:
    registry = ModelRuntimeRegistry()
    registry.register(
        ModelDescriptor(
            model_id="model",
            display_name="Model",
            provider_id="mock",
            endpoint_type=ModelEndpointType.LOCAL_MODEL,
            capabilities=frozenset({"reasoning"}),
        )
    )
    registry.enable("model")
    registry.register_instance(
        ModelInstance(
            instance_id="instance",
            model_id="model",
            node_id="node",
            backend="mock",
            state=state,
            max_concurrency=1,
            memory_mb=memory_mb,
        )
    )
    return registry, ModelResourceScheduler(
        registry,
        memory_capacity_mb=1024,
    )


def test_scheduler_loads_leases_queues_and_releases() -> None:
    async def scenario() -> None:
        registry, scheduler = runtime()
        loaded: list[str] = []

        async def loader(instance: ModelInstance) -> None:
            loaded.append(instance.instance_id)

        await scheduler.ensure_loaded("instance", loader)
        first = await scheduler.acquire(
            request_id="first",
            instance_id="instance",
            timeout_s=1,
            priority=50,
        )
        waiter = asyncio.create_task(
            scheduler.acquire(
                request_id="second",
                instance_id="instance",
                timeout_s=1,
                priority=80,
            )
        )
        await asyncio.sleep(0)
        assert not waiter.done()
        await first.release()
        second = await waiter
        await second.release()
        assert loaded == ["instance"]
        assert registry.get_instance("instance").state is ModelInstanceState.READY
        assert scheduler.resource_usage()["active_leases"] == 0

    asyncio.run(scenario())


def test_scheduler_enforces_resource_capacity() -> None:
    async def scenario() -> None:
        _, scheduler = runtime(memory_mb=2048)
        with pytest.raises(ModelResourceError, match="insufficient memory"):
            await scheduler.ensure_loaded("instance")

    asyncio.run(scenario())


def test_waiting_instance_does_not_block_capacity_on_another_instance() -> None:
    async def scenario() -> None:
        registry, scheduler = runtime(state=ModelInstanceState.READY)
        registry.register_instance(
            ModelInstance(
                instance_id="other",
                model_id="model",
                node_id="node",
                backend="mock",
                state=ModelInstanceState.READY,
                max_concurrency=1,
            )
        )
        held = await scheduler.acquire(
            request_id="held",
            instance_id="instance",
            timeout_s=1,
        )
        blocked = asyncio.create_task(
            scheduler.acquire(
                request_id="blocked",
                instance_id="instance",
                timeout_s=1,
                priority=100,
            )
        )
        await asyncio.sleep(0)
        other = await scheduler.acquire(
            request_id="other",
            instance_id="other",
            timeout_s=0.1,
            priority=1,
        )
        await other.release()
        await held.release()
        await (await blocked).release()

    asyncio.run(scenario())

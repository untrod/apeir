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


@pytest.mark.parametrize("phase", ["loading", "publishing"])
def test_cancelled_load_fails_closed_and_wakes_shared_waiters(phase) -> None:
    async def scenario() -> None:
        registry, scheduler = runtime()
        entered = asyncio.Event()
        finish = asyncio.Event()
        calls = []

        async def loader(instance):
            calls.append(instance.instance_id)
            entered.set()
            await finish.wait()

        owner = asyncio.create_task(scheduler.ensure_loaded("instance", loader))
        await entered.wait()
        waiters = [
            asyncio.create_task(scheduler.ensure_loaded("instance", loader))
            for _ in range(2)
        ]
        await asyncio.sleep(0)
        if phase == "publishing":
            async with scheduler._condition:
                finish.set()
                await asyncio.sleep(0)
                owner.cancel()
        else:
            owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        results = await asyncio.wait_for(
            asyncio.gather(*waiters, return_exceptions=True), timeout=1
        )
        assert all(isinstance(result, ModelResourceError) for result in results)
        assert registry.get_instance("instance").state is ModelInstanceState.FAILED
        assert scheduler.active_leases() == ()
        assert calls == ["instance"]
        with pytest.raises(ModelResourceError, match="cannot be loaded"):
            await scheduler.ensure_loaded("instance", loader)

    asyncio.run(scenario())


def test_cancelling_a_shared_waiter_does_not_cancel_the_original_load() -> None:
    async def scenario() -> None:
        registry, scheduler = runtime()
        entered = asyncio.Event()
        finish = asyncio.Event()
        calls = []

        async def loader(instance):
            calls.append(instance.instance_id)
            entered.set()
            await finish.wait()

        owner = asyncio.create_task(scheduler.ensure_loaded("instance", loader))
        await entered.wait()
        waiter = asyncio.create_task(scheduler.ensure_loaded("instance", loader))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert registry.get_instance("instance").state is ModelInstanceState.LOADING
        finish.set()
        await asyncio.wait_for(owner, timeout=1)
        assert registry.get_instance("instance").state is ModelInstanceState.READY
        assert calls == ["instance"]

    asyncio.run(scenario())


def test_failed_load_wakes_waiters_even_when_registry_persistence_fails(monkeypatch):
    async def scenario() -> None:
        registry, scheduler = runtime()
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def loader(_instance):
            entered.set()
            await finish.wait()
            raise ValueError("controlled load refusal")

        owner = asyncio.create_task(scheduler.ensure_loaded("instance", loader))
        await entered.wait()
        waiter = asyncio.create_task(scheduler.ensure_loaded("instance", loader))
        await asyncio.sleep(0)

        def failed_flush():
            raise OSError("controlled persistence refusal")

        monkeypatch.setattr(registry, "flush", failed_flush)
        finish.set()
        with pytest.raises(OSError, match="persistence refusal"):
            await owner
        with pytest.raises(ModelResourceError, match="failed to load"):
            await asyncio.wait_for(waiter, timeout=1)
        assert registry.get_instance("instance").state is ModelInstanceState.FAILED

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "state",
    [
        ModelInstanceState.DISABLED,
        ModelInstanceState.FAILED,
        ModelInstanceState.UNLOADING,
    ],
)
def test_old_lease_release_cannot_revive_an_unavailable_instance(state):
    async def scenario():
        registry, scheduler = runtime(state=ModelInstanceState.READY)
        lease = await scheduler.acquire(
            request_id="old", instance_id="instance", timeout_s=1
        )
        registry.get_instance("instance").state = state
        await lease.release()
        assert registry.get_instance("instance").state is state
        assert registry.get_instance("instance").active_requests == 0
        assert scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_forced_unload_retires_old_capacity_without_releasing_new_requests():
    async def scenario():
        registry, scheduler = runtime(state=ModelInstanceState.READY)
        old = await scheduler.acquire(
            request_id="old", instance_id="instance", timeout_s=1
        )
        await scheduler.unload("instance", force=True)
        assert registry.get_instance("instance").state is ModelInstanceState.NOT_LOADED
        assert scheduler.active_leases() == ()
        await scheduler.ensure_loaded("instance")
        new = await scheduler.acquire(
            request_id="new", instance_id="instance", timeout_s=1
        )
        await old.release()
        assert scheduler.active_leases() == (new,)
        assert registry.get_instance("instance").active_requests == 1
        assert registry.get_instance("instance").state is ModelInstanceState.SATURATED
        await new.release()
        assert registry.get_instance("instance").state is ModelInstanceState.READY

    asyncio.run(scenario())


def test_cancelled_force_unload_is_failed_not_ready_after_original_completion():
    async def scenario():
        registry, scheduler = runtime(state=ModelInstanceState.READY)
        lease = await scheduler.acquire(
            request_id="original", instance_id="instance", timeout_s=1
        )
        entered = asyncio.Event()

        async def unloader(_instance):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(scheduler.unload("instance", unloader, force=True))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await lease.release()
        assert registry.get_instance("instance").state is ModelInstanceState.FAILED
        assert scheduler.active_leases() == ()

    asyncio.run(scenario())


@pytest.mark.parametrize("force", [False, True])
@pytest.mark.parametrize(
    "state", [ModelInstanceState.LOADING, ModelInstanceState.UNLOADING]
)
def test_unload_cannot_race_another_lifecycle_transition(state, force):
    async def scenario():
        registry, scheduler = runtime(state=state)
        calls = []
        with pytest.raises(ModelResourceError, match="lifecycle transition"):
            await scheduler.unload(
                "instance", lambda _: calls.append("unload"), force=force
            )
        assert registry.get_instance("instance").state is state
        assert calls == []

    asyncio.run(scenario())

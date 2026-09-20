"""Concurrency, loading and lease ownership for model instances."""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from nous_runtime.model_runtime.errors import ModelResourceError
from nous_runtime.model_runtime.models import (
    ModelInstance,
    ModelInstanceState,
    utc_now,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


LoadHandler = Callable[[ModelInstance], Awaitable[None] | None]


@dataclass
class ModelLease:
    lease_id: str
    request_id: str
    instance_id: str
    model_id: str
    acquired_at: str
    _scheduler: "ModelResourceScheduler" = field(
        repr=False,
        compare=False,
    )
    _released: bool = field(default=False, repr=False, compare=False)

    @property
    def released(self) -> bool:
        return self._released

    async def release(self) -> None:
        if not self._released:
            self._released = True
            await self._scheduler.release(self)

    async def __aenter__(self) -> "ModelLease":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.release()


class ModelResourceScheduler:
    """Own model capacity and issue mandatory per-request leases."""

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        *,
        memory_capacity_mb: int = 0,
        vram_capacity_mb: int = 0,
    ) -> None:
        if memory_capacity_mb < 0 or vram_capacity_mb < 0:
            raise ModelResourceError(
                "resource capacities must be non-negative"
            )
        self.registry = registry
        self.memory_capacity_mb = memory_capacity_mb
        self.vram_capacity_mb = vram_capacity_mb
        self._condition = asyncio.Condition()
        self._waiters: list[tuple[int, int, str, str]] = []
        self._sequence = 0
        self._active_leases: dict[str, ModelLease] = {}

    async def ensure_loaded(
        self,
        instance_id: str,
        loader: LoadHandler | None = None,
    ) -> ModelInstance:
        instance = self._require_instance(instance_id)
        async with self._condition:
            if instance.state in {
                ModelInstanceState.READY,
                ModelInstanceState.BUSY,
                ModelInstanceState.SATURATED,
            }:
                return instance
            if instance.state in {
                ModelInstanceState.DISABLED,
                ModelInstanceState.FAILED,
                ModelInstanceState.UNLOADING,
            }:
                raise ModelResourceError(
                    f"instance cannot be loaded from {instance.state.value}"
                )
            if instance.state is ModelInstanceState.LOADING:
                while instance.state is ModelInstanceState.LOADING:
                    await self._condition.wait()
                if instance.state not in {
                    ModelInstanceState.READY,
                    ModelInstanceState.BUSY,
                    ModelInstanceState.SATURATED,
                }:
                    raise ModelResourceError(
                        f"instance failed to load: {instance.instance_id}"
                    )
                return instance
            self._ensure_resource_capacity(instance)
            instance.state = ModelInstanceState.LOADING
        try:
            if loader is not None:
                result = loader(instance)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            async with self._condition:
                instance.state = ModelInstanceState.FAILED
                self.registry.flush()
                self._condition.notify_all()
            raise ModelResourceError(
                f"failed to load instance {instance.instance_id}: {exc}"
            ) from exc
        async with self._condition:
            instance.state = ModelInstanceState.READY
            instance.loaded_at = utc_now()
            self.registry.flush()
            self._condition.notify_all()
        return instance

    async def acquire(
        self,
        *,
        request_id: str,
        instance_id: str,
        timeout_s: float,
        priority: int = 50,
    ) -> ModelLease:
        if timeout_s <= 0:
            raise ModelResourceError("lease timeout must be positive")
        instance = self._require_instance(instance_id)
        ticket = f"waiter_{uuid.uuid4().hex}"
        deadline = time.monotonic() + timeout_s
        async with self._condition:
            self._sequence += 1
            self._waiters.append(
                (
                    -int(priority),
                    self._sequence,
                    ticket,
                    instance.instance_id,
                )
            )
            self._waiters.sort()
            try:
                while True:
                    if instance.state in {
                        ModelInstanceState.DISABLED,
                        ModelInstanceState.FAILED,
                        ModelInstanceState.UNLOADING,
                    }:
                        raise ModelResourceError(
                            "model instance became unavailable while queued"
                        )
                    instance_head = next(
                        (
                            item
                            for item in self._waiters
                            if item[3] == instance.instance_id
                        ),
                        None,
                    )
                    is_head = (
                        instance_head is not None
                        and instance_head[2] == ticket
                    )
                    if is_head and instance.has_capacity:
                        self._waiters = [
                            item
                            for item in self._waiters
                            if item[2] != ticket
                        ]
                        instance.active_requests += 1
                        instance.last_used_at = utc_now()
                        instance.state = (
                            ModelInstanceState.SATURATED
                            if instance.active_requests
                            >= instance.max_concurrency
                            else ModelInstanceState.BUSY
                        )
                        lease = ModelLease(
                            lease_id=f"lease_{uuid.uuid4().hex}",
                            request_id=request_id,
                            instance_id=instance.instance_id,
                            model_id=instance.model_id,
                            acquired_at=utc_now(),
                            _scheduler=self,
                        )
                        self._active_leases[lease.lease_id] = lease
                        return lease
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ModelResourceError(
                            "timed out waiting for model capacity"
                        )
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(),
                            timeout=remaining,
                        )
                    except asyncio.TimeoutError as exc:
                        raise ModelResourceError(
                            "timed out waiting for model capacity"
                        ) from exc
            finally:
                self._waiters = [
                    item for item in self._waiters if item[2] != ticket
                ]

    async def release(self, lease: ModelLease) -> None:
        async with self._condition:
            active = self._active_leases.pop(lease.lease_id, None)
            if active is None:
                return
            instance = self._require_instance(lease.instance_id)
            instance.active_requests = max(
                0,
                instance.active_requests - 1,
            )
            instance.last_used_at = utc_now()
            instance.state = (
                ModelInstanceState.READY
                if instance.active_requests == 0
                else ModelInstanceState.BUSY
            )
            self._condition.notify_all()

    async def unload(
        self,
        instance_id: str,
        unloader: LoadHandler | None = None,
        *,
        force: bool = False,
    ) -> ModelInstance:
        instance = self._require_instance(instance_id)
        async with self._condition:
            if instance.active_requests and not force:
                raise ModelResourceError(
                    "cannot unload an instance with active requests"
                )
            if instance.state is ModelInstanceState.NOT_LOADED:
                return instance
            instance.state = ModelInstanceState.UNLOADING
        try:
            if unloader is not None:
                result = unloader(instance)
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            async with self._condition:
                instance.state = ModelInstanceState.FAILED
                self.registry.flush()
                self._condition.notify_all()
            raise ModelResourceError(
                f"failed to unload instance {instance.instance_id}: {exc}"
            ) from exc
        async with self._condition:
            instance.active_requests = 0
            instance.loaded_at = ""
            instance.state = ModelInstanceState.NOT_LOADED
            self.registry.flush()
            self._condition.notify_all()
        return instance

    async def unload_idle(
        self,
        idle_seconds: float,
        *,
        unloader: LoadHandler | None = None,
    ) -> list[str]:
        if idle_seconds < 0:
            raise ModelResourceError(
                "idle_seconds must be non-negative"
            )
        now = datetime.now(timezone.utc)
        unloaded: list[str] = []
        for instance in self.registry.list_instances():
            if (
                instance.state is not ModelInstanceState.READY
                or instance.active_requests
                or not instance.last_used_at
            ):
                continue
            try:
                last_used = datetime.fromisoformat(
                    instance.last_used_at.replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if (now - last_used).total_seconds() >= idle_seconds:
                await self.unload(instance.instance_id, unloader)
                unloaded.append(instance.instance_id)
        return unloaded

    def active_leases(self) -> tuple[ModelLease, ...]:
        return tuple(self._active_leases.values())

    def resource_usage(self) -> dict[str, int]:
        loaded_states = {
            ModelInstanceState.LOADING,
            ModelInstanceState.READY,
            ModelInstanceState.BUSY,
            ModelInstanceState.SATURATED,
        }
        loaded = [
            item
            for item in self.registry.list_instances()
            if item.state in loaded_states
        ]
        return {
            "memory_mb": sum(item.memory_mb for item in loaded),
            "vram_mb": sum(item.vram_mb for item in loaded),
            "active_requests": sum(
                item.active_requests for item in loaded
            ),
            "active_leases": len(self._active_leases),
        }

    def _require_instance(self, instance_id: str) -> ModelInstance:
        instance = self.registry.get_instance(instance_id)
        if instance is None:
            raise ModelResourceError(
                f"model instance not found: {instance_id}"
            )
        return instance

    def _ensure_resource_capacity(self, instance: ModelInstance) -> None:
        usage = self.resource_usage()
        if (
            self.memory_capacity_mb
            and usage["memory_mb"] + instance.memory_mb
            > self.memory_capacity_mb
        ):
            raise ModelResourceError(
                "insufficient memory capacity for model instance"
            )
        if (
            self.vram_capacity_mb
            and usage["vram_mb"] + instance.vram_mb
            > self.vram_capacity_mb
        ):
            raise ModelResourceError(
                "insufficient VRAM capacity for model instance"
            )


__all__ = ["LoadHandler", "ModelLease", "ModelResourceScheduler"]

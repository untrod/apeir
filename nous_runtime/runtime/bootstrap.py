"""Single, idempotent bootstrap boundary for the Nous Runtime."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from nous_runtime.artifact import ArtifactRegistry
from nous_runtime.artifact import registry as artifact_registry
from nous_runtime.core.events import EventEnvelope
from nous_runtime.core.state import RuntimeState
from nous_runtime.model_runtime.factory import gateway_service
from nous_runtime.model_runtime.gateway import ModelGateway
from nous_runtime.provider.registry import ProviderRegistry


class RuntimeBootstrapState(str, Enum):
    NEW = "new"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    DEGRADED = "degraded"
    STOPPED = "stopped"


@dataclass(frozen=True)
class RuntimeBootstrapSnapshot:
    state: RuntimeBootstrapState
    workspace_root: str
    provider_count: int
    model_count: int
    gateway_configured: bool
    router_ready: bool
    scheduler_ready: bool
    policy_ready: bool
    metrics_ready: bool
    trace_ready: bool
    context_ready: bool
    intelligence_enabled: bool = True
    warnings: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state in {
            RuntimeBootstrapState.READY,
            RuntimeBootstrapState.DEGRADED,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "ready": self.ready,
            "workspace_root": self.workspace_root,
            "provider_count": self.provider_count,
            "model_count": self.model_count,
            "gateway_configured": self.gateway_configured,
            "router_ready": self.router_ready,
            "scheduler_ready": self.scheduler_ready,
            "policy_ready": self.policy_ready,
            "metrics_ready": self.metrics_ready,
            "trace_ready": self.trace_ready,
            "context_ready": self.context_ready,
            "intelligence_enabled": self.intelligence_enabled,
            "warnings": list(self.warnings),
        }


@dataclass
class RuntimeComponents:
    state: RuntimeState
    artifacts: ArtifactRegistry
    providers: ProviderRegistry
    gateway: ModelGateway
    router: Any
    scheduler: Any
    policy: Any = None
    context_builder: Callable[..., Any] | None = None
    trace_factory: Callable[..., Any] | None = None
    metrics: Callable[[], dict[str, float | int]] | None = None


class NousRuntime:
    """Own the process-level Runtime composition root.

    Existing subsystem registries remain authoritative.  Bootstrap only wires
    them together behind one lifecycle boundary and is safe to call repeatedly.
    """

    _current: ClassVar["NousRuntime | None"] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        *,
        workspace_root: str = "",
        provider_loader: Callable[[], int] | None = None,
        no_intelligence: bool | None = None,
    ) -> None:
        self.workspace_root = str(
            Path(workspace_root).resolve() if workspace_root else Path.cwd()
        )
        self.provider_loader = provider_loader
        if no_intelligence is None:
            from nous_runtime.runtime.no_intelligence import no_intelligence_enabled

            no_intelligence = no_intelligence_enabled()
        self.no_intelligence = bool(no_intelligence)
        self.state = RuntimeBootstrapState.NEW
        self.components: RuntimeComponents | None = None
        self.warnings: list[str] = []
        self.events: deque[EventEnvelope] = deque(maxlen=1000)
        self._lock = threading.RLock()

    @classmethod
    def bootstrap(
        cls,
        *,
        workspace_root: str = "",
        provider_loader: Callable[[], int] | None = None,
        no_intelligence: bool | None = None,
        force: bool = False,
    ) -> "NousRuntime":
        requested_root = str(
            Path(workspace_root).resolve() if workspace_root else Path.cwd()
        )
        with cls._class_lock:
            current = cls._current
            reusable = (
                current is not None
                and current.state
                in {
                    RuntimeBootstrapState.READY,
                    RuntimeBootstrapState.DEGRADED,
                }
                and current.workspace_root == requested_root
                and provider_loader is None
                and (
                    no_intelligence is None
                    or current.no_intelligence == bool(no_intelligence)
                )
            )
            if reusable and not force:
                return current
            if current is not None and force:
                current.stop()
            runtime = cls(
                workspace_root=requested_root,
                provider_loader=provider_loader,
                no_intelligence=no_intelligence,
            )
            runtime._start()
            cls._current = runtime
            return runtime

    @classmethod
    def current(cls, *, required: bool = True) -> "NousRuntime | None":
        with cls._class_lock:
            runtime = cls._current
        if runtime is None and required:
            return cls.bootstrap()
        return runtime

    @classmethod
    def reset_for_testing(cls) -> None:
        with cls._class_lock:
            current = cls._current
            cls._current = None
        if current is not None:
            current.stop()
        gateway_service.clear()

    def _start(self) -> None:
        with self._lock:
            if self.state is not RuntimeBootstrapState.NEW:
                return
            self.state = RuntimeBootstrapState.BOOTSTRAPPING
            self._emit("runtime.bootstrap.started", {})

            if self.no_intelligence:
                from nous_runtime.runtime.no_intelligence import activate_no_intelligence

                activate_no_intelligence()
            else:
                loader = self.provider_loader
                if loader is None:
                    from nous_runtime.cli.provider_setup import (
                        load_providers_from_config,
                    )

                    loader = load_providers_from_config
                try:
                    loader()
                except Exception as exc:
                    self.warnings.append(f"provider loading degraded: {exc}")

            gateway = gateway_service.configure_from_providers(
                artifact_registry=artifact_registry
            )
            gateway.event_sink = self._record_gateway_event
            runtime_state = RuntimeState()
            providers = ProviderRegistry()
            for item in providers.list_all():
                provider_id = str(item.get("id") or "")
                provider = providers.get(provider_id)
                if provider_id and provider is not None:
                    runtime_state.register(
                        "providers",
                        provider_id,
                        provider,
                    )
            runtime_state.register(
                "artifacts",
                "registry",
                artifact_registry,
            )

            policy = None
            try:
                from nous_runtime.governance import get_gate

                policy = get_gate()
            except Exception as exc:
                self.warnings.append(f"policy loading degraded: {exc}")

            from nous_runtime.context.builder import build_context
            from nous_runtime.runtime.trace import RuntimeTrace

            self.components = RuntimeComponents(
                state=runtime_state,
                artifacts=artifact_registry,
                providers=providers,
                gateway=gateway,
                router=gateway.router,
                scheduler=gateway.scheduler,
                policy=policy,
                context_builder=build_context,
                trace_factory=RuntimeTrace,
                metrics=gateway.metrics_snapshot,
            )
            self.state = (
                RuntimeBootstrapState.DEGRADED
                if self.warnings
                else RuntimeBootstrapState.READY
            )
            self._emit(
                "runtime.bootstrap.ready",
                self.snapshot().to_dict(),
            )

    def snapshot(self) -> RuntimeBootstrapSnapshot:
        components = self.components
        gateway = components.gateway if components is not None else None
        provider_count = (
            len(components.providers.list_all())
            if components is not None
            else 0
        )
        model_count = (
            len(gateway.registry.list())
            if gateway is not None
            else 0
        )
        return RuntimeBootstrapSnapshot(
            state=self.state,
            workspace_root=self.workspace_root,
            provider_count=provider_count,
            model_count=model_count,
            gateway_configured=gateway is not None,
            router_ready=bool(components and components.router),
            scheduler_ready=bool(components and components.scheduler),
            policy_ready=bool(components and components.policy),
            metrics_ready=bool(components and components.metrics),
            trace_ready=bool(components and components.trace_factory),
            context_ready=bool(components and components.context_builder),
            intelligence_enabled=not self.no_intelligence,
            warnings=tuple(self.warnings),
        )

    def stop(self) -> None:
        with self._lock:
            if self.state is RuntimeBootstrapState.STOPPED:
                return
            if self.components is not None:
                self.components.gateway.close_sync_bridge()
            self.state = RuntimeBootstrapState.STOPPED
            self._emit("runtime.bootstrap.stopped", {})

    def _record_gateway_event(self, event: EventEnvelope) -> None:
        if isinstance(event, EventEnvelope):
            self.events.append(event)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append(
            EventEnvelope(
                event_type=event_type,
                source="runtime.bootstrap",
                payload=payload,
            )
        )


__all__ = [
    "NousRuntime",
    "RuntimeBootstrapSnapshot",
    "RuntimeBootstrapState",
    "RuntimeComponents",
]

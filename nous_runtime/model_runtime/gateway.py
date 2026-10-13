"""Provider-neutral invocation boundary for model execution."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import inspect
import ipaddress
import json
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from nous_runtime.artifact import Artifact, ArtifactRegistry, ArtifactType
from nous_runtime.core.events import EventEnvelope
from nous_runtime.model_runtime.adapters import (
    ModelAdapterRegistry,
    ModelBackendAdapter,
    _provider_cost,
    _safe_provider_error_code,
)
from nous_runtime.model_runtime.cost_control import (
    CostController,
    CostLimitExceeded,
    Reservation,
)
from nous_runtime.model_runtime.errors import (
    ModelInvocationError,
    ModelProviderResponseError,
    ModelResourceError,
)
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelInstance,
    ModelInstanceState,
    ModelRequest,
    ModelResponse,
    RouteDecision,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.model_runtime.resources import ModelResourceScheduler
from nous_runtime.model_runtime.router import ModelRouter


EventSink = Callable[[EventEnvelope], Any]


@dataclass(frozen=True)
class ParallelInvocationPolicy:
    max_candidates: int = 2
    max_concurrency: int = 2
    max_total_cost_usd: float | None = None
    max_total_tokens: int | None = None
    timeout_s: float | None = None
    min_successes: int = 1

    def __post_init__(self) -> None:
        if self.max_candidates < 1 or self.max_concurrency < 1:
            raise ModelInvocationError(
                "parallel candidate and concurrency limits must be positive"
            )
        if self.min_successes < 1:
            raise ModelInvocationError("parallel min_successes must be positive")
        if self.max_total_cost_usd is not None and self.max_total_cost_usd < 0:
            raise ModelInvocationError("parallel cost budget must be non-negative")
        if self.max_total_tokens is not None and self.max_total_tokens < 0:
            raise ModelInvocationError("parallel token budget must be non-negative")
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ModelInvocationError("parallel timeout must be positive")


@dataclass(frozen=True)
class ParallelInvocationResult:
    route_decision: RouteDecision
    responses: tuple[ModelResponse, ...]
    failures: tuple[str, ...]
    cancelled_models: tuple[str, ...]
    total_cost_usd: float | None
    total_tokens: int | None

    @property
    def successful(self) -> bool:
        return bool(self.responses)

    @property
    def selected_response(self) -> ModelResponse | None:
        return self.responses[0] if self.responses else None


@dataclass(frozen=True)
class _ProviderFailure:
    category: str
    retryable: bool
    evidence: dict[str, Any]
    explanation: str


class ModelGateway:
    """Normalize, route, lease, invoke, observe, and safely fall back."""

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        adapters: ModelAdapterRegistry,
        *,
        router: ModelRouter | None = None,
        scheduler: ModelResourceScheduler | None = None,
        artifact_registry: ArtifactRegistry | None = None,
        event_sink: EventSink | None = None,
        max_attempts: int = 3,
        max_retries_per_model: int = 1,
        strict_observability: bool = False,
        event_history_limit: int = 1000,
        use_nki: bool = False,
        nki_endpoint: str | None = None,
        nki_connect_timeout: float = 5.0,
        strict_nki: bool = False,
        cost_controller: CostController | None = None,
    ) -> None:
        if not use_nki:
            logging.warning(
                "ModelGateway initialized without NKI. This explicit compatibility "
                "mode is not used by APEIR product construction."
            )
        else:
            logging.debug(
                "ModelGateway initialized with NKI — routing through the Nous Kernel."
            )
        if max_attempts < 1:
            raise ModelInvocationError("max_attempts must be at least 1")
        if max_retries_per_model < 0:
            raise ModelInvocationError("max_retries_per_model must be non-negative")
        if event_history_limit < 1:
            raise ModelInvocationError("event_history_limit must be positive")
        self.registry = registry
        self.adapters = adapters
        self.router = router or ModelRouter(registry)
        self.scheduler = scheduler or ModelResourceScheduler(registry)
        self.artifacts = artifact_registry
        self.event_sink = event_sink
        self.max_attempts = max_attempts
        self.max_retries_per_model = max_retries_per_model
        self.strict_observability = strict_observability
        self.events: deque[EventEnvelope] = deque(maxlen=event_history_limit)
        self._active: dict[str, ModelBackendAdapter] = {}
        self._metrics_lock = threading.RLock()
        self._metrics: dict[str, float | int] = {
            "requests": 0,
            "responses": 0,
            "failed_requests": 0,
            "cost_usd": 0.0,
            "tokens": 0,
            "latency_ms": 0,
        }
        self._sync_bridge_lock = threading.RLock()
        self._sync_loop: asyncio.AbstractEventLoop | None = None
        self._sync_thread: threading.Thread | None = None
        self._sync_ready: threading.Event | None = None

        # Kernel execution state.
        self._use_nki = use_nki
        self._strict_nki = strict_nki
        self._nki_endpoint = nki_endpoint
        self._nki_connect_timeout = nki_connect_timeout
        self._nki_client: Any = None  # NKIClient, lazy-init
        self._nki_available: bool | None = None  # Tri-state: None=unchecked
        self._nki_lock = threading.RLock()
        self._nki_workloads: dict[str, str] = {}  # request_id → workload_id
        self._cost_controller = cost_controller

    async def invoke(self, request: ModelRequest) -> ModelResponse:
        if not isinstance(request, ModelRequest):
            raise ModelInvocationError("request must be a ModelRequest")
        self._add_metrics(requests=1)
        started = time.monotonic()

        # NKI mode is fail-closed. There is no automatic provider fallback.
        use_kernel = self._use_nki
        if self._use_nki:
            nki_available = await self._ensure_nki_available()
            if not nki_available:
                raise ModelInvocationError(
                    "APEIR Kernel is unavailable; direct provider execution is disabled"
                )

        decision = self.router.route(request)
        await self._emit(
            "model.route.selected",
            request,
            {
                "decision": decision.to_dict(),
                "execution_path": "kernel" if use_kernel else "legacy_direct",
            },
        )
        self._record_artifact(
            ArtifactType.MODEL_REQUEST,
            request.request_id,
            self._safe_request(request),
        )
        self._record_artifact(
            ArtifactType.ROUTE_DECISION,
            decision.decision_id,
            decision.to_dict(),
        )

        errors: list[str] = []
        blocked_providers: dict[str, ModelProviderResponseError] = {}
        last_blocking_error: ModelProviderResponseError | None = None
        routed_candidates = (
            decision.selected_model_id,
            *decision.fallback_model_ids,
        )[: self.max_attempts]
        retry_count = int(
            request.metadata.get(
                "max_retries_per_model",
                self.max_retries_per_model,
            )
        )
        retry_count = max(0, min(retry_count, 10))
        candidates = tuple(
            model_id for model_id in routed_candidates for _ in range(retry_count + 1)
        )
        for attempt_number, model_id in enumerate(candidates, start=1):
            remaining = request.timeout_s - (time.monotonic() - started)
            if remaining <= 0:
                errors.append("overall request timed out")
                break
            candidate_provider_id = ""
            reservation: Reservation | None = None
            dispatched = False

            def before_dispatch() -> None:
                nonlocal dispatched
                if (
                    reservation is not None
                    and not reservation.replayed
                    and self._cost_controller is not None
                ):
                    self._cost_controller.mark_dispatched(reservation)
                dispatched = True

            try:
                descriptor, instance = self._resolve_candidate(
                    model_id,
                    decision,
                )
                candidate_provider_id = descriptor.provider_id
                if candidate_provider_id in blocked_providers:
                    errors.append(
                        f"{model_id}: skipped because Provider "
                        f"{candidate_provider_id} has a non-retryable failure"
                    )
                    continue
                adapter = self.adapters.require(instance.backend)
                guarded_request = request
                if self._cost_controller is not None:
                    provider = getattr(adapter, "provider", None)
                    provider_model = str(
                        descriptor.metadata.get("provider_model")
                        or getattr(provider, "model", "")
                        or descriptor.model_id
                    )
                    reservation = self._cost_controller.authorize(
                        request,
                        provider_id=candidate_provider_id,
                        model_id=provider_model,
                        credential_ref=str(
                            getattr(provider, "credential_ref", "") or ""
                        ),
                        attempt=attempt_number,
                        context_window=descriptor.context_length
                        or getattr(provider, "context_window", None),
                        output_window=descriptor.metadata.get(
                            "output_window", getattr(provider, "output_window", None)
                        ),
                        kernel_binding=self._kernel_accounting_binding(provider)
                        if use_kernel
                        else None,
                    )
                    guarded_request = reservation.request
                if use_kernel:
                    response = await self._nki_execute(
                        guarded_request,
                        descriptor,
                        instance,
                        adapter,
                        before_dispatch=before_dispatch,
                        reconcile_only=reservation is not None and reservation.replayed,
                    )
                else:
                    await self._ensure_loaded(instance, adapter)
                    lease = await self.scheduler.acquire(
                        request_id=request.request_id,
                        instance_id=instance.instance_id,
                        timeout_s=remaining,
                        priority=int(request.metadata.get("priority", 50)),
                    )
                    async with lease:
                        before_dispatch()
                        self._active[request.request_id] = adapter
                        response = await asyncio.wait_for(
                            adapter.invoke(guarded_request, descriptor, instance),
                            timeout=max(
                                0.001,
                                request.timeout_s - (time.monotonic() - started),
                            ),
                        )
                if reservation is not None and self._cost_controller is not None:
                    response, _receipt = self._cost_controller.commit(
                        reservation, response
                    )
                self._active.pop(request.request_id, None)
                self.registry.record_usage(model_id)
                self._record_provider_recovery(candidate_provider_id)
                self._add_metrics(
                    responses=1,
                    cost_usd=response.cost_usd,
                    unknown_cost_responses=int(
                        self._cost_measurement(response) == "unknown"
                    ),
                    unknown_usage_responses=int(
                        response.usage.get("total_tokens") is None
                    ),
                    tokens=int(
                        response.usage.get("total_tokens")
                        or response.usage.get("tokens")
                        or 0
                    ),
                    latency_ms=response.latency_ms,
                )
                await self._emit(
                    "model.invoke.completed",
                    request,
                    self._safe_response(response),
                )
                self._record_artifact(
                    ArtifactType.MODEL_RESPONSE,
                    response.response_id,
                    self._safe_response(response),
                )
                self._record_artifact(
                    ArtifactType.MODEL_METRICS,
                    f"metrics-{response.response_id}",
                    {
                        "model_id": response.model_id,
                        "instance_id": response.instance_id,
                        "usage": dict(response.usage),
                        "cost_usd": self._safe_response(response)["cost_usd"],
                        "cost_measurement": self._cost_measurement(response),
                        "latency_ms": response.latency_ms,
                    },
                )
                # Record successful kernel completion.
                return response
            except asyncio.TimeoutError:
                if reservation is not None and self._cost_controller is not None:
                    self._cost_controller.fail(
                        reservation, reason="timeout", dispatched=dispatched
                    )
                adapter = (
                    self._active.pop(request.request_id, None) if dispatched else None
                )
                if adapter is not None:
                    await adapter.cancel(request.request_id)
                message = f"{model_id}: invocation timed out"
                errors.append(message)
                await self._emit(
                    "model.invoke.failed",
                    request,
                    {
                        "model_id": model_id,
                        "error": "timeout",
                        "attempt": attempt_number,
                    },
                )
                if dispatched and (not use_kernel or self._cost_controller is None):
                    break
            except asyncio.CancelledError:
                if reservation is not None and self._cost_controller is not None:
                    self._cost_controller.fail(
                        reservation, reason="cancelled", dispatched=dispatched
                    )
                adapter = (
                    self._active.pop(request.request_id, None) if dispatched else None
                )
                if adapter is not None:
                    await adapter.cancel(request.request_id)
                await self._emit(
                    "model.invoke.cancelled",
                    request,
                    {
                        "model_id": model_id,
                        "attempt": attempt_number,
                    },
                )
                raise
            except CostLimitExceeded:
                if dispatched:
                    self._active.pop(request.request_id, None)
                if reservation is not None and self._cost_controller is not None:
                    self._cost_controller.fail(
                        reservation,
                        reason="cost policy rejected request",
                        dispatched=dispatched,
                    )
                self._add_metrics(failed_requests=1)
                raise
            except Exception as exc:
                if dispatched:
                    self._active.pop(request.request_id, None)
                failure = self._classify_provider_failure(
                    exc,
                    provider_id=candidate_provider_id,
                    model_id=model_id,
                )
                errors.append(f"{model_id}: {failure.explanation}")
                if reservation is not None and self._cost_controller is not None:
                    self._cost_controller.fail(
                        reservation,
                        reason=failure.explanation,
                        balance_exhausted=failure.category == "budget_exceeded",
                        dispatched=dispatched,
                    )
                self._record_provider_failure(candidate_provider_id, failure)
                if failure.category in {
                    "authentication",
                    "authorization",
                    "budget_exceeded",
                }:
                    last_blocking_error = ModelProviderResponseError(
                        failure.explanation,
                        provider_error_code=str(
                            failure.evidence.get("provider_error_code") or ""
                        ),
                        http_status=failure.evidence.get("http_status"),
                        retryable=False,
                    )
                    blocked_providers[candidate_provider_id] = last_blocking_error
                await self._emit(
                    "model.invoke.failed",
                    request,
                    {
                        "model_id": model_id,
                        "error": failure.explanation,
                        "failure_category": failure.category,
                        "http_status": failure.evidence.get("http_status"),
                        "provider_error_code": failure.evidence.get(
                            "provider_error_code", ""
                        ),
                        "retryable": failure.retryable,
                        "attempt": attempt_number,
                    },
                )
                if dispatched and (not use_kernel or self._cost_controller is None):
                    break

        self._add_metrics(failed_requests=1)
        # Record the kernel failure.
        if last_blocking_error is not None:
            raise ModelProviderResponseError(
                "all safe model routes failed: " + "; ".join(errors),
                provider_error_code=last_blocking_error.provider_error_code,
                http_status=last_blocking_error.http_status,
                retryable=False,
            )
        raise ModelInvocationError("all safe model routes failed: " + "; ".join(errors))

    async def invoke_parallel(
        self,
        request: ModelRequest,
        *,
        policy: ParallelInvocationPolicy | None = None,
    ) -> ParallelInvocationResult:
        """Fan out to bounded safe candidates and cancel excess work."""
        active_policy = policy or ParallelInvocationPolicy()
        decision = self.router.route(request)
        candidates = (
            decision.selected_model_id,
            *decision.fallback_model_ids,
        )[: active_policy.max_candidates]
        model_for_task: dict[asyncio.Task[ModelResponse], str] = {}

        async def invoke_locked(model_id: str) -> ModelResponse:
            payload = request.to_dict()
            payload["request_id"] = f"modelreq_{uuid.uuid4().hex}"
            payload["preferred_models"] = [model_id]
            payload["routing_mode"] = "locked"
            metadata = dict(payload.get("metadata") or {})
            metadata["parent_request_id"] = request.request_id
            payload["metadata"] = metadata
            locked_request = ModelRequest.from_dict(payload)
            return await self.invoke(locked_request)

        timeout = min(
            request.timeout_s,
            active_policy.timeout_s
            if active_policy.timeout_s is not None
            else request.timeout_s,
        )
        deadline = time.monotonic() + timeout
        remaining_models = list(candidates)
        pending: set[asyncio.Task[ModelResponse]] = set()

        def launch_available() -> None:
            while remaining_models and len(pending) < active_policy.max_concurrency:
                model_id = remaining_models.pop(0)
                task = asyncio.create_task(invoke_locked(model_id))
                model_for_task[task] = model_id
                pending.add(task)

        launch_available()
        responses_by_model: dict[str, ModelResponse] = {}
        failures: list[str] = []
        total_cost = 0.0
        total_tokens = 0
        unknown_cost = unknown_tokens = False
        budget_exhausted = False
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            completed, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not completed:
                break
            for task in completed:
                model_id = model_for_task[task]
                try:
                    response = task.result()
                except Exception as exc:
                    failures.append(f"{model_id}: {exc}")
                    continue
                responses_by_model[model_id] = response
                total_cost += response.cost_usd
                unknown_cost |= self._cost_measurement(response) == "unknown"
                unknown_tokens |= (
                    response.usage.get("total_tokens", response.usage.get("tokens"))
                    is None
                )
                total_tokens += int(
                    response.usage.get("total_tokens")
                    or response.usage.get("tokens")
                    or 0
                )
            budget_exhausted = (
                active_policy.max_total_cost_usd is not None
                and (unknown_cost or total_cost >= active_policy.max_total_cost_usd)
            ) or (
                active_policy.max_total_tokens is not None
                and (unknown_tokens or total_tokens >= active_policy.max_total_tokens)
            )
            if budget_exhausted:
                break
            launch_available()

        cancelled_models = list(remaining_models)
        for task in pending:
            model_id = model_for_task[task]
            cancelled_models.append(model_id)
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if budget_exhausted:
            failures.append(
                "parallel invocation budget is unknown"
                if unknown_cost or unknown_tokens
                else "parallel invocation budget exhausted"
            )
        candidate_order = {model_id: index for index, model_id in enumerate(candidates)}
        cancelled_models.sort(key=candidate_order.__getitem__)
        ordered_responses = tuple(
            responses_by_model[model_id]
            for model_id in candidates
            if model_id in responses_by_model
        )
        if len(ordered_responses) < active_policy.min_successes:
            failures.append("parallel invocation did not reach minimum successes")
        await self._emit(
            "model.parallel.completed",
            request,
            {
                "candidate_count": len(candidates),
                "success_count": len(ordered_responses),
                "failure_count": len(failures),
                "cancelled_models": cancelled_models,
                "total_cost_usd": None if unknown_cost else total_cost,
                "total_tokens": None if unknown_tokens else total_tokens,
            },
        )
        return ParallelInvocationResult(
            route_decision=decision,
            responses=ordered_responses,
            failures=tuple(failures),
            cancelled_models=tuple(cancelled_models),
            total_cost_usd=None if unknown_cost else total_cost,
            total_tokens=None if unknown_tokens else total_tokens,
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[Any]:
        """Stream one selected route while retaining its lease."""
        if self._use_nki:
            # The current NKI operation returns a complete response. Reuse its
            # admitted invocation rather than silently opening a direct stream.
            response = await self.invoke(request)
            yield response.content
            return
        decision = self.router.route(request)
        descriptor, instance = self._resolve_candidate(
            decision.selected_model_id,
            decision,
        )
        adapter = self.adapters.require(instance.backend)
        reservation: Reservation | None = None
        guarded_request = request
        if self._cost_controller is not None:
            provider = getattr(adapter, "provider", None)
            reservation = self._cost_controller.authorize(
                request,
                provider_id=descriptor.provider_id,
                model_id=str(
                    descriptor.metadata.get("provider_model")
                    or getattr(provider, "model", "")
                    or descriptor.model_id
                ),
                credential_ref=str(getattr(provider, "credential_ref", "") or ""),
                context_window=descriptor.context_length
                or getattr(provider, "context_window", None),
                output_window=descriptor.metadata.get(
                    "output_window", getattr(provider, "output_window", None)
                ),
            )
            guarded_request = reservation.request
        started = time.monotonic()
        dispatched = False
        finished = False
        iterator = None
        failure: ModelInvocationError | None = None
        try:
            await self._ensure_loaded(instance, adapter)
            lease = await self.scheduler.acquire(
                request_id=request.request_id,
                instance_id=instance.instance_id,
                timeout_s=request.timeout_s,
                priority=int(request.metadata.get("priority", 50)),
            )
            await self._emit(
                "model.stream.started", request, {"decision": decision.to_dict()}
            )
            async with lease:
                if reservation is not None and self._cost_controller is not None:
                    self._cost_controller.mark_dispatched(reservation)
                dispatched = True
                self._active[request.request_id] = adapter
                iterator = adapter.stream(guarded_request, descriptor, instance)
                while True:
                    remaining = request.timeout_s - (time.monotonic() - started)
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        item = await asyncio.wait_for(
                            anext(iterator),
                            timeout=remaining,
                        )
                    except StopAsyncIteration:
                        finished = True
                        break
                    yield item
        except asyncio.TimeoutError:
            failure = ModelInvocationError("model stream timed out")
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = ModelInvocationError(
                "model stream failed; usage remains uncertain"
                if dispatched
                else "model stream failed before dispatch"
            )
        finally:
            if reservation is not None and self._cost_controller is not None:
                # The stream contract supplies content chunks, not terminal
                # usage. Exhaustion or close cannot establish free execution.
                self._cost_controller.fail(
                    reservation,
                    reason="stream has no terminal usage evidence",
                    dispatched=dispatched,
                )
            if dispatched and not finished:
                try:
                    await adapter.cancel(request.request_id)
                except Exception:
                    logging.warning("Model stream cancellation failed")
            if iterator is not None and hasattr(iterator, "aclose"):
                try:
                    await iterator.aclose()
                except Exception:
                    logging.warning("Model stream cleanup failed")
            self._active.pop(request.request_id, None)
            await self._emit(
                "model.stream.finished",
                request,
                {
                    "model_id": descriptor.model_id,
                    "instance_id": instance.instance_id,
                },
            )
        if failure is not None:
            raise failure

    # Kernel integration.

    async def _ensure_nki_available(self) -> bool:
        """Check if nousd is reachable. Caches result for 30 seconds."""
        with self._nki_lock:
            if self._nki_available is True and self._nki_client is not None:
                return True
        try:
            client = await self._get_nki_client()
            result = await asyncio.wait_for(
                client.health_check(deep=False),
                timeout=self._nki_connect_timeout,
            )
            available = self._nki_health_is_ready(result)
            if not available:
                journal = (result.get("components") or {}).get("journal") or {}
                logging.warning(
                    "NKI readiness probe reported an unhealthy kernel (journal: %s)",
                    journal.get("message", "unknown"),
                )
        except Exception:
            logging.warning("NKI readiness probe failed")
            available = False
        with self._nki_lock:
            self._nki_available = available
            if not available:
                self._nki_client = None
        return available

    @staticmethod
    def _nki_health_is_ready(result: dict[str, Any]) -> bool:
        """Accept both kernel-health and Runtime-ready NKI contracts."""
        if result.get("healthy") is True:
            return True
        node = result.get("node") or {}
        return (
            str(result.get("state") or "").upper() == "READY"
            and str(node.get("connection") or "").upper() == "CONNECTED"
        )

    async def _new_nki_client(self) -> Any:
        """Create an independent client so cancellation cannot corrupt an active frame."""
        client_type, default_endpoint = self._load_nki_client_type()
        endpoint = self._nki_endpoint or os.environ.get(
            "NOUS_KERNEL_ENDPOINT", default_endpoint or "tcp://127.0.0.1:8771"
        )
        client = client_type(endpoint)
        await client._connect()
        return client

    @staticmethod
    def _load_nki_client_type() -> tuple[Any, str]:
        import_errors = []
        for import_path in ("compat.nki_client", "nous_runtime.compat.nki_client"):
            try:
                module = __import__(
                    import_path,
                    fromlist=["NKIClient", "DEFAULT_ENDPOINT"],
                )
                return module.NKIClient, module.DEFAULT_ENDPOINT
            except ImportError as exc:
                import_errors.append(f"{import_path}: {exc}")
        raise ModelInvocationError(
            "NKI client is unavailable: " + "; ".join(import_errors)
        )

    async def _get_nki_client(self) -> Any:
        """Get or create the NKI client singleton."""
        if self._nki_client is not None:
            return self._nki_client
        client_type, default_endpoint = self._load_nki_client_type()
        endpoint = self._nki_endpoint or os.environ.get(
            "NOUS_KERNEL_ENDPOINT", default_endpoint or "tcp://127.0.0.1:8771"
        )
        client = client_type(endpoint)
        await client._connect()
        self._nki_client = client
        return client

    async def _nki_execute(
        self,
        request: ModelRequest,
        descriptor: ModelDescriptor,
        instance: ModelInstance,
        adapter: Any,
        *,
        before_dispatch: Callable[[], None] | None = None,
        reconcile_only: bool = False,
    ) -> ModelResponse:
        """Execute the selected model inside the production Runtime path."""
        provider = getattr(adapter, "provider", None)
        if provider is None:
            raise ModelInvocationError(
                "the selected adapter cannot be represented as a Runtime provider"
            )
        provider_id = str(getattr(provider, "provider_id", "") or instance.backend)
        endpoint = self._kernel_endpoint(provider)
        backend = self._kernel_backend(provider_id, endpoint)
        credential_env = self._kernel_credential_reference(provider, backend)
        model = str(
            descriptor.metadata.get("provider_model")
            or getattr(provider, "model", "")
            or descriptor.model_id
        )
        capability = (
            "embedding" if "embedding" in request.required_capabilities else "chat"
        )
        response_format = request.metadata.get("response_format")
        response_schema = dict(request.metadata.get("response_schema") or {})
        if response_format is None and response_schema:
            if getattr(provider, "structured_output_mode", "json_schema") == (
                "json_object"
            ):
                response_format = {"type": "json_object"}
            else:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "nous_response",
                        "schema": response_schema,
                    },
                }
        model_input = {
            "schema_version": 1,
            "capability": capability,
            "messages": [dict(message) for message in request.messages],
            "input": request.metadata.get("input"),
            "tools": list(request.metadata.get("tools") or ()),
            "response_format": response_format,
            "max_output_tokens": request.metadata.get("max_tokens"),
            "temperature": request.metadata.get("temperature"),
        }
        thinking = request.metadata.get("thinking")
        if thinking is not None:
            model_input["thinking"] = thinking
        reasoning_effort = request.metadata.get("reasoning_effort")
        if reasoning_effort is not None:
            model_input["reasoning_effort"] = reasoning_effort
        encoded_input = json.dumps(
            model_input, separators=(",", ":"), ensure_ascii=False
        )
        digest = hashlib.sha256(
            f"{request.request_id}\n{provider_id}\n{model}\n{encoded_input}".encode()
        ).hexdigest()
        operation_id = f"model-{digest}"
        workload_id = f"workload-{operation_id}"
        operation = {
            "operation_id": operation_id,
            "workload_id": workload_id,
            "step_id": "model-invoke",
            "backend": backend,
            "execution_domain": "local" if backend == "ollama" else "remote",
            "model": model,
            "endpoint": endpoint,
            "credential_env": credential_env,
            "provider_entrypoint": "",
            "input": encoded_input,
            "delivery": "AT_MOST_ONCE",
            "snapshot": {
                "model_revision": model,
                "provider_revision": f"{provider_id}-runtime-v1",
                "prompt_revision": str(
                    request.metadata.get("prompt_revision") or "runtime"
                ),
                "tool_revision": str(
                    request.metadata.get("tool_revision") or "runtime"
                ),
                "knowledge_revision": str(
                    request.metadata.get("knowledge_revision") or "runtime"
                ),
                "policy_revision": str(
                    request.metadata.get("policy_revision") or "runtime"
                ),
                "capability_revision": capability,
                "context_revision": str(
                    request.metadata.get("context_revision") or "runtime"
                ),
            },
            "timeout_ms": max(1, int(request.timeout_s * 1000)),
        }
        self._nki_workloads[request.request_id] = workload_id
        started = time.perf_counter()
        client = None
        try:
            client = await self._new_nki_client()
            original_receipt = (
                await self._nki_original_receipt(client, operation, request.timeout_s)
                if reconcile_only
                else None
            )
            if before_dispatch is not None:
                before_dispatch()
            execution = await asyncio.wait_for(
                client.execute_operation(operation, idempotency_key=request.request_id),
                timeout=request.timeout_s,
            )
            expected = {
                **self._nki_receipt_binding(operation),
                "workload_id": workload_id,
                **(original_receipt or {}),
            }
            if (
                not isinstance(execution, dict)
                or any(execution.get(key) != value for key, value in expected.items())
                or not isinstance(execution.get("result"), str)
                or not isinstance(execution.get("output_digest"), str)
                or hashlib.sha256(execution["result"].encode("utf-8")).hexdigest()
                != execution["output_digest"]
            ):
                raise CostLimitExceeded(
                    "original Kernel result does not match its bound receipt"
                )
        finally:
            self._nki_workloads.pop(request.request_id, None)
            if client is not None:
                await client.close()
        try:
            output = json.loads(str(execution.get("result") or ""))
        except json.JSONDecodeError:
            raise ModelInvocationError(
                "Runtime returned an invalid model response"
            ) from None
        if output.get("schema_version") != 1:
            raise ModelInvocationError("Runtime returned an unsupported model response")
        metadata = dict(output.get("metadata") or {})
        metadata.update(
            {
                "execution_path": "kernel",
                "workload_id": workload_id,
                "operation_id": operation_id,
                "decision_trace": execution.get("decision_trace", {}),
            }
        )
        content: Any = output.get("content")
        tool_calls = output.get("tool_calls") or metadata.get("tool_calls") or ()
        if tool_calls:
            content = {"content": content, "tool_calls": list(tool_calls)}
        cost, measurement = _provider_cost(output)
        metadata["cost_measurement"] = measurement
        return ModelResponse(
            request_id=request.request_id,
            model_id=descriptor.model_id,
            instance_id=instance.instance_id,
            content=content,
            usage=dict(output.get("usage") or {}),
            cost_usd=cost,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=str(output.get("finish_reason") or "completed"),
            metadata=metadata,
        )

    def _kernel_accounting_binding(self, provider: Any) -> dict[str, str]:
        if provider is None:
            raise ModelInvocationError(
                "the selected adapter cannot be represented as a Runtime provider"
            )
        endpoint = self._kernel_endpoint(provider)
        backend = self._kernel_backend(
            str(getattr(provider, "provider_id", "")), endpoint
        )
        return {
            "kernel_endpoint": self._nki_endpoint
            or os.environ.get("NOUS_KERNEL_ENDPOINT", "tcp://127.0.0.1:8771"),
            "provider_endpoint": endpoint,
            "backend": backend,
            "credential_env": self._kernel_credential_reference(provider, backend),
        }

    @staticmethod
    def _nki_receipt_binding(operation: dict[str, Any]) -> dict[str, str]:
        return {
            "operation_id": operation["operation_id"],
            "input_digest": hashlib.sha256(
                operation["input"].encode("utf-8")
            ).hexdigest(),
            "snapshot_digest": hashlib.sha256(
                json.dumps(
                    operation["snapshot"], separators=(",", ":"), ensure_ascii=False
                ).encode("utf-8")
            ).hexdigest(),
            "provider_revision": operation["snapshot"]["provider_revision"],
        }

    @staticmethod
    async def _nki_original_receipt(
        client: Any, operation: dict[str, Any], timeout_s: float
    ) -> dict[str, str]:
        """Prove a committed original result before requesting its cached bytes.

        The frozen Kernel's ExplainExecution projects receipt digests, while
        SubmitWorkload returns committed bytes before Provider execution. A
        missing receipt never justifies resubmitting an uncertain model call.
        """
        query = getattr(client, "_request", None)
        if not callable(query):
            raise CostLimitExceeded("original Kernel receipt query is unavailable")
        selector = {
            "workload_id": operation["workload_id"],
        }
        # The frozen projection combines selectors with OR. Select only the
        # workload used by committed_receipt, then bind its StepCommit below.
        failure = None
        try:
            projection = await asyncio.wait_for(
                query("ExplainExecution", selector), timeout=timeout_s
            )
        except Exception:
            failure = CostLimitExceeded(
                "original Kernel receipt query failed; usage remains uncertain"
            )
        if failure is not None:
            raise failure
        expected = ModelGateway._nki_receipt_binding(operation)
        if (
            isinstance(projection, dict)
            and all(projection.get(key) == value for key, value in selector.items())
            and projection.get("operation_id") is None
            and isinstance(projection.get("facts"), list)
        ):
            for entry in projection["facts"]:
                if not isinstance(entry, dict):
                    continue
                fact = entry.get("fact")
                if (
                    entry.get("object_type") == "StepCommit"
                    and entry.get("object_id") == operation["operation_id"]
                    and entry.get("phase") == "COMMITTED"
                    and isinstance(fact, dict)
                    and all(fact.get(key) == value for key, value in expected.items())
                    and isinstance(fact.get("output_digest"), str)
                    and re.fullmatch(r"[0-9a-f]{64}", fact["output_digest"])
                ):
                    return {**expected, "output_digest": fact["output_digest"]}
        raise CostLimitExceeded(
            "original Kernel receipt is unavailable or mismatched; "
            "usage reconciliation is required"
        )

    @staticmethod
    def _kernel_endpoint(provider: Any) -> str:
        endpoint = str(
            getattr(provider, "endpoint", "") or os.environ.get("NOUS_LLM_API_URL", "")
        ).rstrip("/")
        for suffix in (
            "/chat/completions",
            "/embeddings",
            "/api/chat",
            "/api/generate",
        ):
            if endpoint.endswith(suffix):
                endpoint = endpoint[: -len(suffix)]
                break
        if not endpoint:
            raise ModelInvocationError("provider endpoint is not configured")
        return endpoint

    @staticmethod
    def _kernel_backend(provider_id: str, endpoint: str) -> str:
        normalized = f"{provider_id} {endpoint}".lower()
        parsed = urlsplit(endpoint)
        hostname = (parsed.hostname or "").casefold()
        if parsed.path.rstrip("/").endswith("/v1"):
            try:
                if hostname and ipaddress.ip_address(hostname).is_loopback:
                    return "edge-openai-compatible"
            except ValueError:
                if hostname == "localhost":
                    return "edge-openai-compatible"
        if "ollama" in normalized or ":11434" in normalized:
            return "ollama"
        if hostname == "localhost":
            return "edge-openai-compatible"
        try:
            if hostname and ipaddress.ip_address(hostname).is_loopback:
                return "edge-openai-compatible"
        except ValueError:
            pass
        return "openai-compatible"

    @staticmethod
    def _kernel_credential_reference(provider: Any, backend: str) -> str:
        reference = str(getattr(provider, "credential_ref", "") or "").strip()
        if reference.startswith("env:"):
            reference = reference[4:]
        if not reference:
            if backend == "ollama" or (
                backend == "edge-openai-compatible"
                and getattr(provider, "authentication_required", None) is False
            ):
                return ""
            reference = "NOUS_LLM_API_KEY"
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", reference):
            raise ModelInvocationError(
                "kernel execution requires an environment-variable credential reference"
            )
        return reference

    async def _nki_submit_workload(self, request: ModelRequest) -> str:
        """Build a WorkloadSpec from ModelRequest and submit via NKI."""
        client = await self._get_nki_client()
        spec = {
            "workload_id": "",  # Let kernel assign
            "idempotency_key": request.request_id,
            "goal": request.metadata.get("goal", ""),
            "workload_type": "CHAT",
            "model_requirements": {
                "allowed_model_families": request.metadata.get("allowed_models", []),
                "max_tokens_per_request": int(request.metadata.get("max_tokens", 4096)),
                "min_context_length": int(
                    request.metadata.get("min_context_length", 0)
                ),
            },
            "resource_requirements": {
                "minimum": {
                    "cpu_cores_millis": 100,
                    "ram_bytes": 256 * 1024 * 1024,
                },
                "priority": "INTERACTIVE"
                if request.metadata.get("priority", 50) > 70
                else "BATCH",
            },
            "security_requirements": {
                "data_classification": "INTERNAL",
                "allow_network_access": False,
                "allow_file_access": False,
                "allow_side_effects": False,
            },
            "output_contract": {
                "format": "TEXT",
                "max_output_tokens": int(request.metadata.get("max_tokens", 4096)),
            },
            "retry_policy": {
                "max_retries": 1,
                "initial_backoff_ms": 100,
                "max_backoff_ms": 1000,
                "backoff_multiplier": 2.0,
                "retry_on_timeout": True,
            },
            "checkpoint_policy": {
                "enabled": False,
                "strategy": "NONE",
            },
            "cancellation_policy": {
                "cancellable": True,
                "graceful": True,
                "grace_period_seconds": 5,
            },
        }
        result = await client.submit_workload(spec, idempotency_key=request.request_id)
        workload_id = result.get("workload_id", "")
        # C3 fix: submit_workload already grants a lease — extract it directly.
        # Calling reserve_resources again on the same workload_id always fails
        # with AlreadyExists (double-lease bug). Use the lease from submit response.
        lease = result.get("lease", {})
        if not lease.get("lease_id"):
            lease = {
                "lease_id": result.get("lease_id", f"wl-lease-{workload_id}"),
                "workload_id": workload_id,
                "granted_at": result.get("granted_at", 0),
                "expires_at": result.get("expires_at", 0),
            }
        self._nki_workloads[request.request_id] = workload_id
        await self._emit(
            "nki.workload.submitted",
            request,
            {
                "workload_id": workload_id,
                "phase": result.get("phase"),
                "lease_id": lease.get("lease_id"),
            },
        )
        return workload_id, lease

    async def _nki_acquire_lease(
        self, workload_id: str, request: ModelRequest
    ) -> dict[str, Any]:
        """Reserve resources for a workload via NKI."""
        client = await self._get_nki_client()
        resources = {
            "cpu_cores_millis": 500,
            "ram_bytes": 512 * 1024 * 1024,
            "device_memory_bytes": int(request.metadata.get("min_vram_bytes", 0)),
        }
        result = await client.reserve_resources(workload_id, resources)
        return result.get("lease", {})

    async def _nki_report_completion(
        self,
        workload_id: str,
        response: ModelResponse | None = None,
        error: str | None = None,
    ) -> None:
        """Report workload completion or failure to nousd."""
        try:
            client = await self._get_nki_client()
            if error:
                # Mark failed via cancel with force
                await client.cancel_workload(workload_id, reason=error, force=True)
                await self._emit(
                    "nki.workload.failed",
                    None,
                    {"workload_id": workload_id, "error": error},
                )
            else:
                await self._emit(
                    "nki.workload.completed",
                    None,
                    {"workload_id": workload_id},
                )
        except Exception as exc:
            logging.debug("NKI completion report failed (non-fatal): %s", exc)

    async def _nki_close(self) -> None:
        """Close the NKI client connection."""
        with self._nki_lock:
            if self._nki_client is not None:
                try:
                    asyncio.ensure_future(self._nki_client.close())
                except Exception:
                    pass
                self._nki_client = None
                self._nki_available = None

    async def cancel(self, request_id: str) -> bool:
        workload_id = self._nki_workloads.get(str(request_id))
        if workload_id:
            client = await self._new_nki_client()
            try:
                await client.cancel_workload(
                    workload_id,
                    reason="cancelled by application",
                    force=False,
                )
            finally:
                await client.close()
            return True
        adapter = self._active.get(str(request_id))
        if adapter is None:
            return False
        await adapter.cancel(str(request_id))
        return True

    def metrics_snapshot(self) -> dict[str, float | int]:
        with self._metrics_lock:
            return dict(self._metrics)

    def active_request_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self._active) | set(self._nki_workloads)))

    def invoke_sync(self, request: ModelRequest) -> ModelResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop = self._ensure_sync_loop()
            future = asyncio.run_coroutine_threadsafe(
                self.invoke(request),
                loop,
            )
            try:
                return future.result(timeout=request.timeout_s + 5.0)
            except concurrent.futures.TimeoutError as exc:
                future.cancel()
                raise ModelInvocationError(
                    "synchronous model invocation timed out"
                ) from exc
        raise ModelInvocationError("invoke_sync cannot run inside an active event loop")

    def close_sync_bridge(self, timeout_s: float = 5.0) -> None:
        """Stop the optional daemon loop used by synchronous callers."""
        with self._sync_bridge_lock:
            loop = self._sync_loop
            thread = self._sync_thread
            self._sync_loop = None
            self._sync_thread = None
            self._sync_ready = None
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=max(0.0, timeout_s))
        # Release kernel request state.
        if self._nki_client is not None:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._nki_close())
            except RuntimeError:
                pass

    def _resolve_candidate(
        self,
        model_id: str,
        decision: RouteDecision,
    ) -> tuple[ModelDescriptor, ModelInstance]:
        record = self.registry.require(model_id)
        instances = [
            item
            for item in self.registry.instances_for(model_id)
            if item.state
            not in {
                ModelInstanceState.DISABLED,
                ModelInstanceState.FAILED,
                ModelInstanceState.UNLOADING,
            }
        ]
        if not instances:
            raise ModelResourceError(f"no usable instance for model: {model_id}")
        selected_id = (
            decision.selected_instance_id
            if model_id == decision.selected_model_id
            else ""
        )
        instance = next(
            (item for item in instances if item.instance_id == selected_id),
            min(
                instances,
                key=lambda item: (
                    item.active_requests / item.max_concurrency,
                    item.instance_id,
                ),
            ),
        )
        return record.descriptor, instance

    def _ensure_sync_loop(self) -> asyncio.AbstractEventLoop:
        with self._sync_bridge_lock:
            if (
                self._sync_loop is not None
                and self._sync_thread is not None
                and self._sync_thread.is_alive()
            ):
                return self._sync_loop
            if (
                self._sync_thread is not None
                and self._sync_thread.is_alive()
                and self._sync_ready is not None
            ):
                ready = self._sync_ready
            else:
                ready = threading.Event()
                self._sync_ready = ready

                def run_loop() -> None:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    with self._sync_bridge_lock:
                        self._sync_loop = loop
                    ready.set()
                    try:
                        loop.run_forever()
                    finally:
                        loop.run_until_complete(loop.shutdown_asyncgens())
                        loop.close()

                thread = threading.Thread(
                    target=run_loop,
                    name="nous-model-gateway",
                    daemon=True,
                )
                self._sync_thread = thread
                thread.start()
        if not ready.wait(timeout=5.0):
            raise ModelInvocationError("failed to start synchronous model gateway loop")
        with self._sync_bridge_lock:
            if self._sync_loop is None:
                raise ModelInvocationError(
                    "synchronous model gateway loop is unavailable"
                )
            return self._sync_loop

    async def _ensure_loaded(
        self,
        instance: ModelInstance,
        adapter: ModelBackendAdapter,
    ) -> None:
        loader = getattr(adapter, "load", None)
        await self.scheduler.ensure_loaded(
            instance.instance_id,
            loader if callable(loader) else None,
        )

    async def _emit(
        self,
        event_type: str,
        request: ModelRequest | None,
        payload: dict[str, Any],
    ) -> None:
        event = EventEnvelope(
            event_type=event_type,
            source="model_gateway",
            payload=payload,
            metadata={
                "request_id": request.request_id if request else "",
                "task_id": request.task_id if request else "",
            },
        )
        self.events.append(event)
        if self.event_sink is not None:
            try:
                result = self.event_sink(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                if self.strict_observability:
                    raise
                self.events.append(
                    EventEnvelope(
                        event_type="model.observability.failed",
                        source="model_gateway",
                        payload={
                            "failed_event_type": event_type,
                            "error": "model event publication failed",
                        },
                        metadata={
                            "request_id": request.request_id,
                            "task_id": request.task_id,
                        },
                    )
                )

    def _record_artifact(
        self,
        artifact_type: ArtifactType,
        name: str,
        metadata: dict[str, Any],
    ) -> None:
        if self.artifacts is None:
            return
        try:
            artifact = Artifact(
                type=artifact_type,
                name=name,
                creator="model_gateway",
                metadata=metadata,
            )
            self.artifacts.register(artifact)
        except Exception:
            if self.strict_observability:
                raise
            self.events.append(
                EventEnvelope(
                    event_type="model.observability.failed",
                    source="model_gateway",
                    payload={
                        "failed_artifact_type": artifact_type.value,
                        "error": "model artifact publication failed",
                    },
                )
            )

    def _add_metrics(self, **values: float | int) -> None:
        with self._metrics_lock:
            for name, value in values.items():
                self._metrics[name] = self._metrics.get(name, 0) + value

    @staticmethod
    def _classify_provider_failure(
        error: Exception,
        *,
        provider_id: str,
        model_id: str,
    ):
        message = str(error)
        http_status = getattr(error, "http_status", None)
        if http_status is None and "http" in message.casefold():
            match = re.search(r"\bHTTP\s+(\d{3})\b", message, re.IGNORECASE)
            if match is None:
                match = re.search(r"\((\d{3})\s+[^)]*\)", message)
            if match is not None:
                http_status = int(match.group(1))
        if type(http_status) is not int or not 100 <= http_status <= 599:
            http_status = None
        provider_error_code = str(
            getattr(error, "provider_error_code", "")
            or getattr(error, "code", "")
            or ""
        )
        if http_status == 402:
            provider_error_code = "NOUS_PROVIDER_BALANCE_EXHAUSTED"
        code_lower = provider_error_code.casefold()
        if http_status == 402 or any(
            marker in code_lower
            for marker in ("balance", "billing", "budget", "credit", "payment")
        ):
            category, retryable = "budget_exceeded", False
        elif http_status == 401 or any(
            marker in code_lower for marker in ("auth", "unauthorized", "key")
        ):
            category, retryable = "authentication", False
        elif http_status == 403:
            category, retryable = "authorization", False
        elif http_status == 429 or any(
            marker in code_lower for marker in ("rate", "quota", "limit")
        ):
            category, retryable = "rate_limit", True
        elif http_status == 408 or "timeout" in code_lower:
            category, retryable = "timeout", True
        elif http_status in {500, 502, 503, 504}:
            category, retryable = "server_error", True
        else:
            category, retryable = "unknown", True
        explicit_retryable = getattr(error, "retryable", None)
        if isinstance(explicit_retryable, bool):
            retryable = explicit_retryable
        evidence = {
            "http_status": http_status,
            "provider_error_code": _safe_provider_error_code(provider_error_code),
        }
        return _ProviderFailure(
            category=category,
            retryable=retryable,
            evidence=evidence,
            explanation=(
                f"Classified as {category}"
                + (f"; HTTP {http_status}" if http_status else "")
                + (
                    f"; code={evidence['provider_error_code']}"
                    if evidence["provider_error_code"]
                    else ""
                )
            ),
        )

    def _record_provider_failure(self, provider_id: str, failure: Any) -> None:
        if not provider_id:
            return
        health = {
            "status": "degraded",
            "source": "model_gateway",
            "category": failure.category,
            "retryable": failure.retryable,
            "http_status": failure.evidence.get("http_status"),
            "provider_error_code": failure.evidence.get("provider_error_code", ""),
            "message": failure.explanation,
        }
        for record in self.registry.list():
            if record.descriptor.provider_id == provider_id:
                self.registry.update_health(record.descriptor.model_id, health)

    def _record_provider_recovery(self, provider_id: str) -> None:
        if not provider_id:
            return
        for record in self.registry.list():
            if (
                record.descriptor.provider_id == provider_id
                and record.health.get("source") == "model_gateway"
            ):
                self.registry.update_health(
                    record.descriptor.model_id,
                    {"status": "healthy", "source": "model_gateway"},
                )

    @staticmethod
    def _safe_request(request: ModelRequest) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "task_id": request.task_id,
            "required_capabilities": sorted(request.required_capabilities),
            "required_modalities": sorted(
                item.value for item in request.required_modalities
            ),
            "message_count": len(request.messages),
            "attachment_count": len(request.attachments),
            "routing_mode": request.routing_mode.value,
            "privacy_policy": request.privacy_policy.value,
            "required_location": request.required_location,
            "metadata_keys": sorted(str(key) for key in request.metadata),
        }

    @staticmethod
    def _cost_measurement(response: ModelResponse) -> str:
        marker = response.metadata.get("cost_measurement")
        if isinstance(marker, str) and marker in {
            "reported",
            "estimated",
            "derived",
            "unknown",
        }:
            return marker
        return "reported" if response.cost_usd > 0 else "unknown"

    @staticmethod
    def _safe_response(response: ModelResponse) -> dict[str, Any]:
        return {
            "response_id": response.response_id,
            "request_id": response.request_id,
            "model_id": response.model_id,
            "instance_id": response.instance_id,
            "content_type": type(response.content).__name__,
            "usage": dict(response.usage),
            "cost_usd": response.cost_usd
            if ModelGateway._cost_measurement(response) != "unknown"
            else None,
            "cost_measurement": ModelGateway._cost_measurement(response),
            "latency_ms": response.latency_ms,
            "finish_reason": response.finish_reason,
        }


class NKIEnabledModelGateway(ModelGateway):
    """Route model execution through the APEIR Kernel interface."""

    def __init__(
        self,
        registry: ModelRuntimeRegistry,
        adapters: ModelAdapterRegistry,
        *,
        router: ModelRouter | None = None,
        scheduler: ModelResourceScheduler | None = None,
        artifact_registry: ArtifactRegistry | None = None,
        event_sink: EventSink | None = None,
        max_attempts: int = 3,
        max_retries_per_model: int = 1,
        strict_observability: bool = False,
        event_history_limit: int = 1000,
        nki_endpoint: str | None = None,
        nki_connect_timeout: float = 5.0,
        strict_nki: bool = True,
        cost_controller: CostController | None = None,
    ) -> None:
        super().__init__(
            registry=registry,
            adapters=adapters,
            router=router,
            scheduler=scheduler,
            artifact_registry=artifact_registry,
            event_sink=event_sink,
            max_attempts=max_attempts,
            max_retries_per_model=max_retries_per_model,
            strict_observability=strict_observability or strict_nki,
            event_history_limit=event_history_limit,
            use_nki=True,
            nki_endpoint=nki_endpoint,
            nki_connect_timeout=nki_connect_timeout,
            strict_nki=strict_nki,
            cost_controller=cost_controller,
        )


__all__ = [
    "EventSink",
    "ModelGateway",
    "NKIEnabledModelGateway",
    "ParallelInvocationPolicy",
    "ParallelInvocationResult",
]

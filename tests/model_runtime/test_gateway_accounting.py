"""Exercise usage admission and uncertain dispatch through the real Gateway."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import traceback
from dataclasses import replace
from types import SimpleNamespace

import pytest

from compat.nki_client import NKIClient

from nous_runtime.model_runtime.adapters import (
    LegacyProviderAdapter,
    MockModelAdapter,
    ModelAdapterRegistry,
)
from nous_runtime.model_runtime.cost_control import (
    CostController,
    CostLimitExceeded,
    CostPolicy,
    Pricing,
    PricingCatalog,
)
from nous_runtime.model_runtime.errors import ModelInvocationError
from nous_runtime.model_runtime.gateway import ModelGateway, ParallelInvocationPolicy
from nous_runtime.model_runtime.factory import build_gateway_from_providers
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelRequest,
    ModelResponse,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry


class RecordingAdapter(MockModelAdapter):
    backend_id = "fake-accounting"

    def __init__(self):
        super().__init__()
        self.requests = []
        self.stream_closed = False

    async def invoke(self, request, descriptor, instance):
        self.requests.append(request)
        return ModelResponse(
            request_id=request.request_id,
            model_id=descriptor.model_id,
            instance_id=instance.instance_id,
            content="fake complete response",
            usage={"input_tokens": 100, "output_tokens": 2},
        )

    async def stream(self, request, descriptor, instance):
        self.requests.append(request)
        try:
            yield "one"
            yield "two"
        finally:
            self.stream_closed = True


def build_gateway(
    tmp_path,
    *,
    adapter=None,
    kernel=False,
    retries=0,
    context=0,
    output=None,
    price=True,
):
    adapter = adapter or RecordingAdapter()
    registry = ModelRuntimeRegistry()
    registry.register(
        ModelDescriptor(
            model_id="model",
            display_name="Fake model",
            provider_id="provider",
            endpoint_type=ModelEndpointType.CLOUD_API,
            capabilities=frozenset({"chat"}),
            context_length=context,
            metadata={"output_window": output},
        )
    )
    registry.enable("model")
    registry.register_instance(
        ModelInstance(
            instance_id="fake-instance",
            model_id="model",
            node_id="fake-node",
            backend=adapter.backend_id,
            state=ModelInstanceState.READY,
        )
    )
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    controller = CostController(
        tmp_path / "usage.sqlite3",
        policy=CostPolicy(max_output_tokens=32),
        pricing=PricingCatalog({"provider/model": Pricing(1, 2)})
        if price
        else PricingCatalog(),
    )
    gateway = ModelGateway(
        registry,
        adapters,
        cost_controller=controller,
        use_nki=kernel,
        max_retries_per_model=retries,
    )
    return gateway, adapter, controller


def request():
    return ModelRequest(
        task_id="original-fake-task",
        messages=({"role": "user", "content": "original"},),
        metadata={"estimated_input_tokens": 100, "max_tokens": 8},
    )


def kernel_provider(adapter):
    adapter.provider = SimpleNamespace(
        provider_id="provider",
        model="model",
        endpoint="https://fake.example/v1",
        credential_ref="env:APEIR_FAKE_API_KEY",
    )


def fake_kernel_receipt(operation, output):
    body = json.dumps(output)
    return {
        "operation_id": operation["operation_id"],
        "workload_id": operation["workload_id"],
        "input_digest": hashlib.sha256(operation["input"].encode()).hexdigest(),
        "snapshot_digest": hashlib.sha256(
            json.dumps(
                operation["snapshot"], separators=(",", ":"), ensure_ascii=False
            ).encode()
        ).hexdigest(),
        "provider_revision": operation["snapshot"]["provider_revision"],
        "output_digest": hashlib.sha256(body.encode()).hexdigest(),
        "result": body,
    }


def test_kernel_stream_uses_admitted_operation_and_model_windows(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(
            tmp_path, kernel=True, context=107, output=64
        )
        kernel_provider(adapter)
        operations = []

        async def available():
            return True

        class Client:
            async def execute_operation(self, operation, idempotency_key=""):
                operations.append(operation)
                return fake_kernel_receipt(
                    operation,
                    {
                        "schema_version": 1,
                        "content": "kernel chunk",
                        "usage": {"input_tokens": 100, "output_tokens": 2},
                    },
                )

            async def close(self):
                pass

        async def new_client():
            return Client()

        gateway._ensure_nki_available = available
        gateway._new_nki_client = new_client
        assert [chunk async for chunk in gateway.stream(request())] == ["kernel chunk"]
        assert adapter.requests == [] and len(operations) == 1
        assert json.loads(operations[0]["input"])["max_output_tokens"] == 7
        assert (
            controller.summary()["total_tokens"] == 102
            and controller.summary()["reserved_tokens"] == 0
        )

    asyncio.run(scenario())


def test_unavailable_kernel_stream_never_invokes_direct_adapter(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True)

        async def unavailable():
            return False

        gateway._ensure_nki_available = unavailable
        with pytest.raises(
            ModelInvocationError, match="direct provider execution is disabled"
        ):
            await anext(gateway.stream(request()))
        assert adapter.requests == [] and controller.summary()["reservations"] == []

    asyncio.run(scenario())


@pytest.mark.parametrize("dispatched", [False, True])
def test_kernel_failure_releases_only_confirmed_predispatch_attempt(
    tmp_path, dispatched
):
    private = "FAKE-UNREGISTERED-PRIVATE-PROVIDER-TEXT"

    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True)
        kernel_provider(adapter)
        operations = []

        async def available():
            return True

        class Client:
            async def execute_operation(self, operation, idempotency_key=""):
                operations.append(operation)
                raise RuntimeError(private)

            async def close(self):
                pass

        async def new_client():
            if not dispatched:
                raise RuntimeError(private)
            return Client()

        gateway._ensure_nki_available = available
        gateway._new_nki_client = new_client
        with pytest.raises(ModelInvocationError) as caught:
            await gateway.invoke(request())
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert private not in "".join(traceback.format_exception(caught.value))
        assert private not in str([event.to_dict() for event in gateway.events])
        assert private not in str([record.health for record in gateway.registry.list()])
        summary = controller.summary()
        assert len(operations) == int(dispatched)
        assert summary["reserved_tokens"] == (108 if dispatched else 0)
        assert summary["receipts"][0]["status"] == (
            "uncertain" if dispatched else "not_dispatched"
        )
        assert (
            private not in str(summary)
            and private.encode() not in controller.database.read_bytes()
        )

    asyncio.run(scenario())


def test_unconsumed_stream_does_not_reserve_or_dispatch(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path)
        stream = gateway.stream(request())
        await stream.aclose()
        assert adapter.requests == [] and controller.summary()["reservations"] == []
        assert controller.summary()["requests"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("partial", [False, True])
def test_completed_or_closed_direct_stream_keeps_unknown_usage(tmp_path, partial):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path)
        stream = gateway.stream(request())
        if partial:
            assert await anext(stream) == "one"
            await stream.aclose()
        else:
            assert [chunk async for chunk in stream] == ["one", "two"]
        summary = controller.summary()
        assert summary["requests"] == summary["uncertain_calls"] == 1
        assert summary["reserved_tokens"] == 108 and summary["total_tokens"] is None
        assert summary["total_cost_usd"] is None and summary[
            "reserved_cost_usd"
        ] == pytest.approx(0.000116)
        assert adapter.stream_closed and gateway.scheduler.active_leases() == ()
        assert bool(adapter.cancelled) is partial
        assert summary["receipts"][0]["request_id"] == adapter.requests[0].request_id

    asyncio.run(scenario())


@pytest.mark.parametrize("dispatched", [False, True])
def test_stream_cancellation_preserves_dispatch_state(tmp_path, dispatched):
    async def scenario():
        entered = asyncio.Event()
        never = asyncio.Event()

        class HeldAdapter(RecordingAdapter):
            async def load(self, instance):
                if not dispatched:
                    entered.set()
                    await never.wait()

            async def stream(self, value, descriptor, instance):
                self.requests.append(value)
                entered.set()
                await never.wait()
                yield "unreachable"

        gateway, adapter, controller = build_gateway(tmp_path, adapter=HeldAdapter())
        if not dispatched:
            gateway.registry.get_instance(
                "fake-instance"
            ).state = ModelInstanceState.NOT_LOADED
        stream = gateway.stream(request())
        task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(entered.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await stream.aclose()
        summary = controller.summary()
        assert summary["reserved_tokens"] == (108 if dispatched else 0)
        assert summary["receipts"][0]["status"] == (
            "uncertain" if dispatched else "not_dispatched"
        )
        assert (
            bool(adapter.requests) is dispatched
            and bool(adapter.cancelled) is dispatched
        )
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())


def test_unknown_pricing_stream_is_rejected_before_provider(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, price=False)
        with pytest.raises(CostLimitExceeded, match="pricing"):
            await anext(gateway.stream(request()))
        assert adapter.requests == [] and controller.summary()["reservations"] == []

    asyncio.run(scenario())


def test_dispatched_failure_retains_one_original_uncertain_budget(tmp_path):
    async def scenario():
        class FailingAdapter(RecordingAdapter):
            async def invoke(self, value, descriptor, instance):
                self.requests.append(value)
                raise RuntimeError("FAKE-UNREGISTERED-PRIVATE-RETRY-TEXT")

        gateway, adapter, controller = build_gateway(
            tmp_path, adapter=FailingAdapter(), retries=1
        )
        with pytest.raises(ModelInvocationError) as caught:
            await gateway.invoke(request())
        summary = controller.summary()
        assert "FAKE-UNREGISTERED-PRIVATE-RETRY-TEXT" not in str(caught.value)
        assert (
            len(adapter.requests)
            == summary["requests"]
            == summary["uncertain_calls"]
            == 1
        )
        assert summary["reserved_tokens"] == 108
        assert {receipt["attempt"] for receipt in summary["receipts"]} == {1}
        assert len({receipt["request_id"] for receipt in summary["receipts"]}) == 1
        assert len({receipt["reservation_id"] for receipt in summary["receipts"]}) == 1

    asyncio.run(scenario())


def test_legacy_parameters_cannot_replace_admitted_payload_or_output_limit(tmp_path):
    async def scenario():
        params = []

        class Provider:
            model = "model"

            def invoke(self, capability_id, **value):
                params.append(value)
                return {
                    "ok": True,
                    "content": "fake",
                    "usage": {"input_tokens": 100, "output_tokens": 2},
                    "cost_usd": 0,
                }

        adapter = LegacyProviderAdapter(Provider(), backend_id="fake-accounting")
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter)
        value = request()
        value = replace(
            value,
            metadata={
                **dict(value.metadata),
                "legacy_params": {
                    "messages": [{"content": "replacement"}],
                    "max_tokens": 900,
                    "max_output_tokens": 900,
                    "max_completion_tokens": 900,
                },
            },
        )
        result = await gateway.invoke(value)
        assert params[0]["messages"] == list(value.messages)
        assert {
            params[0][name]
            for name in ("max_tokens", "max_output_tokens", "max_completion_tokens")
        } == {8}
        assert (
            result.metadata["cost_measurement"] == "reported"
            and controller.summary()["reported_cost_usd"] == 0
        )

    asyncio.run(scenario())


def test_parallel_unknown_billing_stops_later_budgeted_routes(tmp_path):
    async def scenario():
        class UnmeteredAdapter(RecordingAdapter):
            async def invoke(self, value, descriptor, instance):
                self.requests.append(value)
                return ModelResponse(
                    request_id=value.request_id,
                    model_id=descriptor.model_id,
                    instance_id=instance.instance_id,
                    content="unmetered fake response",
                )

        gateway, adapter, controller = build_gateway(
            tmp_path, adapter=UnmeteredAdapter()
        )
        gateway.registry.register(
            ModelDescriptor(
                model_id="second",
                display_name="Second fake model",
                provider_id="provider",
                endpoint_type=ModelEndpointType.CLOUD_API,
                capabilities=frozenset({"chat"}),
            )
        )
        gateway.registry.enable("second")
        gateway.registry.register_instance(
            ModelInstance(
                instance_id="second-instance",
                model_id="second",
                node_id="fake-node",
                backend=adapter.backend_id,
                state=ModelInstanceState.READY,
            )
        )
        controller.pricing = PricingCatalog(
            {"provider/model": Pricing(1, 2), "provider/second": Pricing(1, 2)}
        )
        result = await gateway.invoke_parallel(
            request(),
            policy=ParallelInvocationPolicy(
                max_candidates=2, max_concurrency=1, max_total_cost_usd=1
            ),
        )
        assert len(adapter.requests) == 1 and result.cancelled_models == ("second",)
        assert result.total_cost_usd is None and result.total_tokens is None
        assert "parallel invocation budget is unknown" in result.failures
        assert (
            controller.summary()["uncertain_calls"] == 1
            and controller.summary()["reserved_tokens"] == 108
        )
        event = next(
            item
            for item in gateway.events
            if item.event_type == "model.parallel.completed"
        )
        assert (
            event.payload["total_cost_usd"] is None
            and event.payload["total_tokens"] is None
        )

    asyncio.run(scenario())


def test_usage_violation_releases_gateway_tracking_but_preserves_actual_receipt(
    tmp_path,
):
    async def scenario():
        class OverrunAdapter(RecordingAdapter):
            async def invoke(self, value, descriptor, instance):
                return ModelResponse(
                    request_id=value.request_id,
                    model_id=descriptor.model_id,
                    instance_id=instance.instance_id,
                    usage={"input_tokens": 100, "output_tokens": 9},
                )

        gateway, _, controller = build_gateway(tmp_path, adapter=OverrunAdapter())
        value = request()
        with pytest.raises(CostLimitExceeded, match="provider response"):
            await gateway.invoke(value)
        summary = controller.summary()
        assert (
            value.request_id not in gateway._active
            and gateway.scheduler.active_leases() == ()
        )
        assert summary["total_tokens"] == 109 and summary["reserved_tokens"] == 0
        assert summary["receipts"][0]["status"] == "policy_violation"

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["priced", "token-only", "unconfigured"])
def test_product_factory_loads_real_accounting_environment(tmp_path, monkeypatch, mode):
    monkeypatch.delenv("APEIR_MODEL_PRICING_FILE", raising=False)
    monkeypatch.delenv("APEIR_MAX_DAILY_COST_USD", raising=False)
    monkeypatch.delenv("APEIR_MAX_RETRY_COST_USD", raising=False)
    if mode == "priced":
        prices = tmp_path / "fake-verified-pricing.json"
        prices.write_text(
            json.dumps(
                {
                    "models": {
                        "provider/model": {
                            "input_per_million_usd": 1,
                            "output_per_million_usd": 2,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("APEIR_MODEL_PRICING_FILE", str(prices))
    elif mode == "token-only":
        monkeypatch.setenv("APEIR_MAX_DAILY_COST_USD", "none")
        monkeypatch.setenv("APEIR_MAX_RETRY_COST_USD", "none")

    class Provider:
        provider_id = "provider"
        provider_name = "Fake Provider"
        model = "model"
        endpoint = "https://fake.example/v1"
        credential_ref = "env:APEIR_FAKE_API_KEY"

        @staticmethod
        def list_capabilities():
            return ["model.reason"]

        @staticmethod
        def invoke(*args, **kwargs):
            raise AssertionError("product factory must use NKI")

    async def scenario():
        gateway = build_gateway_from_providers([Provider()])
        operations = []

        async def available():
            return True

        class Client:
            async def execute_operation(self, operation, idempotency_key=""):
                operations.append(operation)
                return fake_kernel_receipt(
                    operation,
                    {
                        "schema_version": 1,
                        "content": "fake",
                        "usage": {"input_tokens": 3, "output_tokens": 2},
                    },
                )

            async def close(self):
                pass

        async def new_client():
            return Client()

        gateway._ensure_nki_available = available
        gateway._new_nki_client = new_client
        if mode == "unconfigured":
            with pytest.raises(CostLimitExceeded, match="APEIR_MODEL_PRICING_FILE"):
                await gateway.invoke(request())
            assert (
                operations == []
                and gateway._cost_controller.summary()["reservations"] == []
            )
            return
        result = await gateway.invoke(request())
        summary = gateway._cost_controller.summary()
        assert len(operations) == 1 and summary["total_tokens"] == 5
        if mode == "priced":
            assert result.metadata["cost_measurement"] == "estimated"
            assert summary["estimated_cost_usd"] == pytest.approx(0.000007)
        else:
            assert (
                result.metadata["cost_measurement"] == "unknown"
                and summary["total_cost_usd"] is None
            )
            assert (
                summary["policy"]["max_daily_cost_usd"] is None
                and summary["policy"]["max_retry_cost_usd"] is None
            )

    asyncio.run(scenario())


class FakeKernelJournal:
    """Use the real client envelope with the frozen Kernel's receipt projections."""

    def __init__(self, *, lost_ack=True, committed=True, damage=""):
        self.lost_ack = lost_ack
        self.committed = committed
        self.damage = damage
        self.operations = []
        self.queries = []
        self.effects = 0
        self.execution = None
        self.original = None
        self.entered = asyncio.Event()
        self.hold = None

    def client(self):
        journal = self

        class Client(NKIClient):
            async def _send(self, envelope):
                return await journal.send(envelope.method, envelope.payload)

            async def close(self):
                pass

        return Client("tcp://fake-kernel:8771")

    async def send(self, method, payload):
        if method == "ExplainExecution":
            self.queries.append(payload)
            if self.damage == "unsupported_query":
                raise RuntimeError("FAKE-PRIVATE-UNSUPPORTED-KERNEL-QUERY")
            facts = []
            if self.execution is not None and (
                payload.get("operation_id") == self.original["operation_id"]
                or payload.get("workload_id")
                == (
                    self.original["workload_id"]
                    if self.damage != "different_workload"
                    else "another-journal-workload"
                )
            ):
                fact = {
                    key: value
                    for key, value in self.execution.items()
                    if key not in {"result", "workload_id"}
                }
                if self.damage in fact:
                    fact[self.damage] = "changed-original-binding"
                facts.append(
                    {
                        "object_id": self.original["operation_id"],
                        "object_type": "StepCommit",
                        "phase": "COMMITTED"
                        if self.damage != "uncommitted"
                        else "RECEIVED",
                        "fact": fact,
                    }
                )
            result = {**payload, "facts": facts}
            if self.damage in {"selector_operation", "selector_workload"}:
                result[self.damage.removeprefix("selector_") + "_id"] = "changed"
            if self.damage == "malformed_facts":
                result["facts"] = "unavailable"
            return result
        assert method == "SubmitWorkload"
        self.operations.append(payload)
        if self.original is None:
            self.original = copy.deepcopy(payload)
            self.effects += 1
            self.entered.set()
            if self.hold is not None:
                await self.hold.wait()
            if self.committed:
                body = json.dumps(
                    {
                        "schema_version": 1,
                        "content": "original cached fake response",
                        "usage": {"input_tokens": 100, "output_tokens": 2},
                        "cost_usd": 0.000104,
                    }
                )
                self.execution = {
                    "operation_id": payload["operation_id"],
                    "workload_id": payload["workload_id"],
                    "input_digest": hashlib.sha256(
                        payload["input"].encode()
                    ).hexdigest(),
                    "snapshot_digest": hashlib.sha256(
                        json.dumps(
                            payload["snapshot"],
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode()
                    ).hexdigest(),
                    "provider_revision": payload["snapshot"]["provider_revision"],
                    "output_digest": hashlib.sha256(body.encode()).hexdigest(),
                    "result": body,
                }
            if self.lost_ack or not self.committed:
                raise ConnectionError(
                    "fake response lost after the original model effect"
                )
        assert payload == self.original
        assert self.execution is not None, (
            "an unproven effect must never be resubmitted"
        )
        result = copy.deepcopy(self.execution)
        if self.damage.startswith("initial_"):
            result[self.damage.removeprefix("initial_")] = "changed-original-receipt"
        elif self.damage == "returned_result":
            result["result"] = json.dumps({"schema_version": 1, "content": "changed"})
        elif self.damage == "returned_receipt":
            result["operation_id"] = "another-effect"
        return result


def configure_fake_journal(gateway, adapter, journal):
    kernel_provider(adapter)

    async def available():
        return True

    async def new_client():
        return journal.client()

    gateway._ensure_nki_available = available
    gateway._new_nki_client = new_client


def test_lost_kernel_acknowledgement_reconciles_one_original_charge(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True, retries=1)
        journal = FakeKernelJournal()
        configure_fake_journal(gateway, adapter, journal)
        response = await gateway.invoke(request())
        summary = controller.summary()
        assert response.content == "original cached fake response"
        assert journal.effects == 1 and len(journal.operations) == 2
        assert len(journal.queries) == 1
        assert journal.operations[0]["delivery"] == "AT_MOST_ONCE"
        assert summary["requests"] == 1 and summary["uncertain_calls"] == 0
        assert summary["total_tokens"] == 102 and summary["reserved_tokens"] == 0
        assert summary["reported_cost_usd"] == pytest.approx(0.000104)
        assert summary["receipts"][0]["attempt"] == 1
        assert summary["receipts"][0]["reconciled_at"]
        assert (
            summary["receipts"][0]["receipt_id"]
            == response.metadata["usage_receipt"]["receipt_id"]
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "damage",
    [
        "operation_id",
        "input_digest",
        "snapshot_digest",
        "provider_revision",
        "output_digest",
        "selector_operation",
        "selector_workload",
        "uncommitted",
        "malformed_facts",
        "different_workload",
        "unsupported_query",
        "returned_result",
        "returned_receipt",
    ],
)
def test_invalid_original_kernel_evidence_cannot_settle_or_dispatch(tmp_path, damage):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True, retries=1)
        journal = FakeKernelJournal(damage=damage)
        configure_fake_journal(gateway, adapter, journal)
        with pytest.raises(CostLimitExceeded, match="original Kernel") as caught:
            await gateway.invoke(request())
        assert caught.value.__context__ is None and caught.value.__cause__ is None
        assert "FAKE-PRIVATE-UNSUPPORTED-KERNEL-QUERY" not in "".join(
            traceback.format_exception(caught.value)
        )
        summary = controller.summary()
        assert journal.effects == 1
        assert len(journal.operations) == (2 if damage.startswith("returned_") else 1)
        assert summary["requests"] == summary["uncertain_calls"] == 1
        assert summary["reserved_tokens"] == 108 and summary["total_cost_usd"] is None
        assert summary["reserved_cost_usd"] == pytest.approx(0.000116)

    asyncio.run(scenario())


def test_uncertain_kernel_effect_without_receipt_never_reexecutes(tmp_path):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True, retries=1)
        journal = FakeKernelJournal(committed=False)
        configure_fake_journal(gateway, adapter, journal)
        with pytest.raises(CostLimitExceeded, match="usage reconciliation"):
            await gateway.invoke(request())
        assert journal.effects == len(journal.operations) == 1
        assert controller.summary()["reserved_tokens"] == 108
        assert controller.summary()["requests"] == 1

    asyncio.run(scenario())


def test_kernel_original_charge_reconciles_after_restart_and_completed_replay(tmp_path):
    async def scenario():
        value = request()
        journal = FakeKernelJournal()
        first, adapter, controller = build_gateway(tmp_path, kernel=True)
        configure_fake_journal(first, adapter, journal)
        with pytest.raises(ModelInvocationError):
            await first.invoke(value)
        receipt_id = controller.summary()["receipts"][0]["receipt_id"]
        for _ in range(2):
            reopened, adapter, controller = build_gateway(tmp_path, kernel=True)
            configure_fake_journal(reopened, adapter, journal)
            await reopened.invoke(value)
            summary = controller.summary()
            assert summary["requests"] == 1 and summary["reserved_tokens"] == 0
            assert summary["receipts"][0]["receipt_id"] == receipt_id
            assert summary["reported_cost_usd"] == pytest.approx(0.000104)
        assert journal.effects == 1 and len(journal.operations) == 3
        assert len(journal.queries) == 2

    asyncio.run(scenario())


def test_concurrent_kernel_replay_cannot_dispatch_or_release_original(tmp_path):
    async def scenario():
        value = request()
        journal = FakeKernelJournal(lost_ack=False)
        journal.hold = asyncio.Event()
        first, adapter, controller = build_gateway(tmp_path, kernel=True)
        configure_fake_journal(first, adapter, journal)
        task = asyncio.create_task(first.invoke(value))
        await asyncio.wait_for(journal.entered.wait(), timeout=1)
        second, adapter, reopened = build_gateway(tmp_path, kernel=True)
        configure_fake_journal(second, adapter, journal)
        try:
            with pytest.raises(CostLimitExceeded, match="usage reconciliation"):
                await second.invoke(value)
            assert len(journal.operations) == journal.effects == 1
            assert reopened.summary()["reserved_tokens"] == 108
        finally:
            journal.hold.set()
            await task
        assert controller.summary()["requests"] == 1
        assert controller.summary()["reserved_tokens"] == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field",
    [
        "operation_id",
        "workload_id",
        "input_digest",
        "snapshot_digest",
        "provider_revision",
        "output_digest",
        "result",
    ],
)
def test_initial_kernel_receipt_must_bind_usage_to_its_original_operation(
    tmp_path, field
):
    async def scenario():
        gateway, adapter, controller = build_gateway(tmp_path, kernel=True, retries=1)
        journal = FakeKernelJournal(lost_ack=False, damage="initial_" + field)
        configure_fake_journal(gateway, adapter, journal)
        with pytest.raises(CostLimitExceeded, match="bound receipt"):
            await gateway.invoke(request())
        summary = controller.summary()
        assert journal.effects == len(journal.operations) == 1
        assert journal.queries == []
        assert summary["requests"] == summary["uncertain_calls"] == 1
        assert summary["reserved_tokens"] == 108 and summary["total_cost_usd"] is None

    asyncio.run(scenario())


def test_kernel_without_accounting_cannot_blindly_retry_uncertain_dispatch(tmp_path):
    async def scenario():
        gateway, adapter, _ = build_gateway(tmp_path, kernel=True, retries=1)
        gateway._cost_controller = None
        journal = FakeKernelJournal(committed=False)
        configure_fake_journal(gateway, adapter, journal)
        with pytest.raises(ModelInvocationError):
            await gateway.invoke(request())
        assert journal.effects == len(journal.operations) == 1
        assert journal.queries == []

    asyncio.run(scenario())


class BillableEffectAdapter(RecordingAdapter):
    """A call incurs a known fake charge before any response can be lost."""

    def __init__(self, *, lost_response=False, hold=None):
        super().__init__()
        self.effects = 0
        self.lost_response = lost_response
        self.hold = hold
        self.entered = asyncio.Event()

    async def invoke(self, value, descriptor, instance):
        self.effects += 1
        self.entered.set()
        if self.hold is not None and self.effects == 1:
            await self.hold.wait()
        if self.lost_response:
            if self.lost_response == "timeout":
                raise asyncio.TimeoutError
            raise ConnectionError("FAKE-PRIVATE-BILLABLE-RESPONSE-LOST")
        return await super().invoke(value, descriptor, instance)


@pytest.mark.parametrize("accounting", [True, False])
@pytest.mark.parametrize("loss", ["connection", "timeout"])
def test_lost_direct_response_never_automatically_repeats_billable_effect(
    tmp_path, accounting, loss
):
    async def scenario():
        adapter = BillableEffectAdapter(lost_response=loss)
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter, retries=1)
        if not accounting:
            gateway._cost_controller = None
        with pytest.raises(ModelInvocationError) as caught:
            await gateway.invoke(request())
        assert "FAKE-PRIVATE-BILLABLE-RESPONSE-LOST" not in str(caught.value)
        assert adapter.effects == 1
        if accounting:
            summary = controller.summary()
            assert summary["requests"] == summary["uncertain_calls"] == 1
            assert summary["reserved_tokens"] == 108
            assert summary["reserved_cost_usd"] == pytest.approx(0.000116)
            assert summary["total_cost_usd"] is None
            assert summary["receipts"][0]["attempt"] == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("lost_response", [True, False])
def test_original_direct_request_is_fenced_across_repeated_calls_and_restart(
    tmp_path, lost_response
):
    async def scenario():
        value = request()
        adapter = BillableEffectAdapter(lost_response=lost_response)
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter)
        if lost_response:
            with pytest.raises(ModelInvocationError):
                await gateway.invoke(value)
        else:
            await gateway.invoke(value)
        original = controller.summary()
        for restarted in (False, True):
            if restarted:
                gateway, _, controller = build_gateway(tmp_path, adapter=adapter)
            with pytest.raises(CostLimitExceeded, match="original.*reconciliation"):
                await gateway.invoke(value)
            assert adapter.effects == 1
            summary = controller.summary()
            assert summary["receipts"] == original["receipts"]
            assert summary["reserved_tokens"] == original["reserved_tokens"]
            assert summary["reserved_cost_usd"] == original["reserved_cost_usd"]
        adapter.lost_response = False
        await gateway.invoke(replace(value, request_id="new-explicit-user-intent"))
        assert adapter.effects == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("during_setup", [False, True])
@pytest.mark.parametrize("same_gateway", [False, True])
def test_concurrent_original_direct_request_cannot_dispatch_or_release_first(
    tmp_path, during_setup, same_gateway
):
    async def scenario():
        value = request()
        hold = asyncio.Event()
        adapter = BillableEffectAdapter(hold=None if during_setup else hold)
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter)
        entered = adapter.entered
        if during_setup:
            entered = asyncio.Event()

            async def setup(instance, selected):
                entered.set()
                await hold.wait()

            gateway._ensure_loaded = setup
        task = asyncio.create_task(gateway.invoke(value))
        await asyncio.wait_for(entered.wait(), timeout=1)
        if same_gateway:
            second, reopened = gateway, controller
        else:
            second, _, reopened = build_gateway(tmp_path, adapter=adapter)
        try:
            with pytest.raises(CostLimitExceeded, match="original.*reconciliation"):
                await second.invoke(value)
            assert adapter.effects == (0 if during_setup else 1)
            assert gateway.active_request_ids() == (
                () if during_setup else (value.request_id,)
            )
            assert reopened.summary()["reserved_tokens"] == 108
            assert reopened.summary()["reserved_cost_usd"] == pytest.approx(0.000116)
        finally:
            hold.set()
            await task
        assert adapter.effects == controller.summary()["requests"] == 1
        assert controller.summary()["reserved_tokens"] == 0

    asyncio.run(scenario())


def test_direct_setup_failure_retries_without_a_second_billable_effect(tmp_path):
    async def scenario():
        adapter = BillableEffectAdapter()
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter, retries=1)
        setup_calls = 0

        async def setup(instance, selected):
            nonlocal setup_calls
            setup_calls += 1
            if setup_calls == 1:
                raise ConnectionError("fake setup failed before provider dispatch")

        gateway._ensure_loaded = setup
        await gateway.invoke(request())
        assert setup_calls == 2 and adapter.effects == 1
        summary = controller.summary()
        assert summary["reserved_tokens"] == summary["uncertain_calls"] == 0
        assert {item["status"] for item in summary["receipts"]} == {
            "not_dispatched",
            "completed",
        }

    asyncio.run(scenario())


def test_direct_stream_original_request_cannot_be_reopened(tmp_path):
    async def scenario():
        value = request()
        gateway, adapter, controller = build_gateway(tmp_path)
        assert [item async for item in gateway.stream(value)] == ["one", "two"]
        reopened, _, _ = build_gateway(tmp_path, adapter=adapter)
        with pytest.raises(CostLimitExceeded, match="original.*reconciliation"):
            await anext(reopened.stream(value))
        assert len(adapter.requests) == 1
        assert controller.summary()["reserved_tokens"] == 108

    asyncio.run(scenario())


def test_direct_stream_factory_response_loss_retains_original_charge(tmp_path):
    async def scenario():
        class BillableStreamFactory(RecordingAdapter):
            def stream(self, value, descriptor, instance):
                self.requests.append(value)
                raise ConnectionError("fake response lost during stream setup")

        gateway, adapter, controller = build_gateway(
            tmp_path, adapter=BillableStreamFactory()
        )
        value = request()
        with pytest.raises(ModelInvocationError, match="usage remains uncertain"):
            await anext(gateway.stream(value))
        with pytest.raises(CostLimitExceeded, match="original.*reconciliation"):
            await anext(gateway.stream(value))
        summary = controller.summary()
        assert len(adapter.requests) == summary["uncertain_calls"] == 1
        assert summary["reserved_tokens"] == 108
        assert summary["reserved_cost_usd"] == pytest.approx(0.000116)
        assert summary["total_cost_usd"] is None

    asyncio.run(scenario())


def test_legacy_unbound_direct_original_requires_evidence_after_upgrade(tmp_path):
    async def scenario():
        adapter = BillableEffectAdapter(lost_response=True)
        gateway, _, controller = build_gateway(tmp_path, adapter=adapter)
        value = request()
        with pytest.raises(ModelInvocationError):
            await gateway.invoke(value)
        # Model the pre-fence ledger schema: an exposure and receipt exist,
        # but neither records the additive original execution binding.
        with controller._session() as connection:
            connection.execute(
                "UPDATE usage_reservations SET execution_key='', reservation_json=''"
            )
            connection.execute("UPDATE usage_receipts SET execution_key=''")
        reopened, _, _ = build_gateway(tmp_path, adapter=adapter)
        with pytest.raises(CostLimitExceeded, match="no execution binding"):
            await reopened.invoke(value)
        assert adapter.effects == 1
        assert controller.summary()["reserved_tokens"] == 108

    asyncio.run(scenario())

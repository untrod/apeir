"""Saved input admission at real Runtime/Gateway and isolated HTTP boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import urllib.request
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from nous_runtime.context.selected_input import (
    ProviderRecipient,
    SelectedInputAdmission,
    SelectedInputError,
)
from nous_runtime.governance.permission import PermissionRule
from nous_runtime.model_runtime import (
    GatewayChatHandler,
    ModelAdapterRegistry,
    ModelGateway,
    ModelGatewayFacade,
    ModelRequest,
    OpenAICompatibleAdapter,
)
from nous_runtime.runtime.pipeline import RuntimePipeline
from nous_runtime.runtime.request import RuntimeRequest
from tests.context.test_selected_input import (
    admitted_context as context_fixture,
    base_admission as base_admission,
    reference,
    reader,
    build,
    requires_safe_read,
    RECIPIENT_A,
)
from tests.model_runtime.test_gateway import add_model

admitted_context = context_fixture


@pytest.fixture
def endpoint():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            body = json.dumps(
                {
                    "choices": [
                        {
                            "message": {"content": "grounded response"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 3,
                        "total_tokens": 23,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1/chat/completions", received
    server.shutdown()
    server.server_close()
    thread.join(2)


def gateway_for(adapter, *, retries=0):
    from nous_runtime.model_runtime.registry import ModelRuntimeRegistry

    registry = ModelRuntimeRegistry()
    add_model(registry, "selected-model", adapter.backend_id)
    registry.register(
        replace(
            registry.get("selected-model").descriptor,
            capabilities=frozenset({"chat", "reasoning"}),
        ),
        replace_existing=True,
        state=registry.get("selected-model").state,
    )
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    return ModelGateway(registry, adapters, max_retries_per_model=retries)


def permit_transfer(gate, root, endpoint, transport, provider="selected-http"):
    recipient = ProviderRecipient(provider, endpoint, transport)
    resource = (
        "workspace:"
        + hashlib.sha256(str(root).encode()).hexdigest()
        + ":provider:"
        + recipient.digest
    )
    gate.permission_engine.add(PermissionRule("*", "context.transfer", resource))


def pipeline_fixture(admitted_context, endpoint, *, transfer=True):
    from nous_runtime.compat.capability import register_capability

    guard, gate, actor = admitted_context
    register_capability(
        "product.chat",
        category="software",
        executor_type="runtime",
        side_effect_class="read_only",
        reversibility="reversible",
        idempotent=True,
        model_uncertainty=0.0,
    )
    gate.permission_engine.add(PermissionRule("*", "product.chat", "*"))
    gate.permission_engine.add(PermissionRule("*", "workspace.read", "*"))
    adapter = OpenAICompatibleAdapter(
        backend_id="selected-http", endpoint=endpoint, model="fake-selected-model"
    )
    gateway = gateway_for(adapter)
    if transfer:
        permit_transfer(gate, guard._workspace, endpoint, adapter.backend_id)
    pipeline = RuntimePipeline(
        workspace_root=guard._workspace,
        gate=gate,
        product_handlers={"chat": GatewayChatHandler(ModelGatewayFacade(gateway))},
    )
    return pipeline, gateway, adapter, actor


@requires_safe_read
def test_saved_reference_crosses_real_api_and_http_provider(
    admitted_context, endpoint, monkeypatch
):
    from nous_runtime.api.server import create_server
    from nous_runtime.chat.runtime import ChatRuntime

    url, received = endpoint
    pipeline, gateway, _, _ = pipeline_fixture(admitted_context, url)
    root = pipeline.workspace_root
    ref = reference(Path(root))
    chat = ChatRuntime(root, orchestrator=SimpleNamespace(run=pipeline.run))
    monkeypatch.setattr("nous_runtime.chat.ChatRuntime", lambda *_: chat)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", root)
    service_session = "fake.input.service"
    monkeypatch.setenv("NOUS_API_TOKEN", service_session)
    monkeypatch.setenv("NOUS_LLM_API_KEY", "")
    server = create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/chat",
            data=json.dumps(
                {
                    "text": "Explain these notes",
                    "agent_mode": "chat",
                    "workspace_file_refs": [{"path": ref.path, "sha256": ref.sha256}],
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {service_session}",
                "Content-Type": "application/json",
            },
        )
        result = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert result["ok"], result
        assert result["data"]["status"] == "ok", result
        assert len(received) == 1
        assert "exact saved middle constraint" in json.dumps(received)
        assert "notes.txt" not in json.dumps(received)
        events = pipeline.events.load_events(result["data"]["run_id"])
        dispatch = [
            e.payload for e in events if e.event_type == "context.input.dispatched"
        ]
        assert dispatch and dispatch[0]["sources"][0]["status"] == "sent"
        assert dispatch[0]["provider_receipt_confirmed"] is False
        assert "middle constraint" not in json.dumps(dispatch)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        gateway.close_sync_bridge()


@requires_safe_read
@pytest.mark.parametrize("revoke_after_setup", [False, True])
def test_explicit_host_policy_bootstraps_real_api_without_engine_injection(
    admitted_context, endpoint, monkeypatch, revoke_after_setup
):
    from nous_runtime.api.server import create_server
    from nous_runtime.chat.runtime import ChatRuntime
    from nous_runtime.compat.capability import register_capability
    from nous_runtime.governance import GovernanceStore, get_gate

    register_capability(
        "product.chat",
        category="software",
        executor_type="runtime",
        side_effect_class="read_only",
        reversibility="reversible",
        idempotent=True,
        model_uncertainty=0.0,
    )
    guard, _, _ = admitted_context
    root = Path(guard._workspace)
    url, received = endpoint
    adapter = OpenAICompatibleAdapter(
        backend_id="selected-http", endpoint=url, model="fake-selected-model"
    )
    recipient = ProviderRecipient("selected-http", url, adapter.backend_id)
    workspace = "workspace:" + hashlib.sha256(str(root).encode()).hexdigest()
    path = root / ".nous" / "permission-policy.json"
    document = {
        "rules": [
            {"subject": "api-service", "action": action, "resource": resource}
            for action, resource in (
                ("context.read", "*"),
                ("product.chat", "*"),
                ("workspace.read", workspace),
                ("context.transfer", workspace + ":provider:" + recipient.digest),
            )
        ]
    }
    path.write_text(json.dumps(document))
    path.chmod(0o600)
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(root))
    monkeypatch.setenv("NOUS_PERMISSION_POLICY", str(path))
    monkeypatch.setattr("nous_runtime.governance.gate._gate_instance", None)
    gate = get_gate(store=GovernanceStore(root / ".nous"))
    assert gate.permission_engine.configuration_status()["source"] == "owner-file"
    gateway = gateway_for(adapter)
    pipeline = RuntimePipeline(
        workspace_root=str(root),
        gate=gate,
        product_handlers={"chat": GatewayChatHandler(ModelGatewayFacade(gateway))},
    )
    if revoke_after_setup:

        async def load_and_revoke(instance):
            path.write_text(json.dumps({"rules": []}))

        adapter.load = load_and_revoke
    chat = ChatRuntime(str(root), orchestrator=SimpleNamespace(run=pipeline.run))
    monkeypatch.setattr("nous_runtime.chat.ChatRuntime", lambda *_: chat)
    service_session = "fake.input.host-policy"
    monkeypatch.setenv("NOUS_API_TOKEN", service_session)
    monkeypatch.setenv("NOUS_API_SUBJECT", "api-service")
    server = create_server(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ref = reference(root)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/v1/chat",
            data=json.dumps(
                {
                    "text": "Explain these notes",
                    "agent_mode": "chat",
                    "workspace_file_refs": [{"path": ref.path, "sha256": ref.sha256}],
                }
            ).encode(),
            headers={
                "Authorization": f"Bearer {service_session}",
                "Content-Type": "application/json",
            },
        )
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        if revoke_after_setup:
            assert received == []
            assert response["data"]["status"] != "ok"
        else:
            assert response["data"]["status"] == "ok", response
            assert len(received) == 1
            assert "exact saved middle constraint" in json.dumps(received)
        assert "permission-policy.json" not in json.dumps(received)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        gateway.close_sync_bridge()


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "version",
        "read",
        "transfer",
        "retarget",
        "cancel",
        "run_binding",
        "profile",
        "provider_id",
        "transport",
        "run_missing",
        "transfer_revoked",
    ],
)
@requires_safe_read
def test_changes_after_setup_never_dispatch(admitted_context, endpoint, change):
    url, received = endpoint
    pipeline, gateway, adapter, actor = pipeline_fixture(
        admitted_context, url, transfer=change != "transfer"
    )
    ref = reference(Path(pipeline.workspace_root))

    async def setup(_):
        if change == "missing":
            (Path(pipeline.workspace_root) / ref.path).unlink()
        if change == "version":
            (Path(pipeline.workspace_root) / ref.path).write_text("changed source")
        if change == "read":
            pipeline.gate.permission_engine.add(
                PermissionRule("*", "workspace.read", "*", effect="deny")
            )
        if change == "retarget":
            adapter.provider.capability_endpoints["model.reason"] = url.replace(
                "/v1/", "/changed/"
            )
        if change == "provider_id":
            adapter.provider.provider_id = "retargeted-provider"
        if change == "transport":
            adapter.backend_id = "changed-transport"
        if change == "run_missing":
            (
                Path(pipeline.workspace_root)
                / ".nous"
                / "events"
                / "selected-negative.jsonl"
            ).unlink()
        if change == "transfer_revoked":
            pipeline.gate.permission_engine.add(
                PermissionRule("*", "context.transfer", "*", effect="deny")
            )
        if change == "cancel":
            from nous_runtime.events import EventStream
            from nous_runtime.events.models import RunState

            EventStream(pipeline.workspace_root).emit_state_change(
                "selected-negative", RunState.CANCELLED, task_id="selected-negative"
            )
        if change == "run_binding":
            pipeline.events.emit(SimpleNamespace())
        if change == "profile":
            from nous_runtime.agent.registry import AgentRegistry

            registry = AgentRegistry(pipeline.workspace_root)
            profile = registry.get(actor.subject_id)
            registry.register(replace(profile.manifest, metadata={"role": "unknown"}))

    if change == "run_binding":

        async def setup(_):
            from nous_runtime.events.models import RunEvent

            pipeline.events.emit(
                RunEvent(
                    run_id="selected-negative",
                    task_id="selected-negative",
                    event_type="runtime.input.bound",
                    payload={"request_binding_sha256": "changed"},
                )
            )

    adapter.load = setup
    try:
        response = pipeline.run(
            RuntimeRequest(
                "Explain these notes",
                request_id="selected-negative",
                user_id=actor.subject_id,
                authenticated_context=actor,
                constraints={"product_capability": "chat", "agent_mode": "chat"},
                workspace_file_refs=(ref,),
            )
        )
        assert response.status != "ok", response.to_dict()
        assert received == []
        assert gateway.scheduler.active_leases() == ()
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
def test_private_admission_is_retained_by_copy_and_refused_after_serialization(
    admitted_context,
):
    guard, _, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))], transfer=True)
    snapshot = build(value)
    messages = ({"role": "system", "content": snapshot.items[0].content},)
    hook = SelectedInputAdmission(value, snapshot, lambda: True, messages, ())
    request = ModelRequest(
        task_id="original",
        messages=messages,
        _input_admission=hook,
        metadata={"requires_selected_input_admission": True},
    )
    assert replace(request, metadata=dict(request.metadata))._input_admission is hook
    assert "_input_admission" not in request.to_dict()
    assert "SelectedInputAdmission" not in repr(request)
    from nous_runtime.model_runtime.adapters import MockModelAdapter

    adapter = MockModelAdapter()
    adapter.endpoint = RECIPIENT_A.endpoint
    adapter.backend_id = RECIPIENT_A.provider_id
    gateway = gateway_for(adapter)

    async def scenario():
        with pytest.raises(Exception, match="Selected saved input admission failed"):
            await gateway.invoke(ModelRequest.from_dict(request.to_dict()))
        assert adapter.invocations == []

    asyncio.run(scenario())


@requires_safe_read
@pytest.mark.parametrize("path", ["invoke_retry", "fallback", "stream", "nki"])
def test_each_actual_boundary_rechecks_after_setup_or_first_attempt(
    admitted_context, path
):
    from nous_runtime.model_runtime.adapters import MockModelAdapter
    from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
    from tests.model_runtime.test_kernel_execution_gateway import FakeKernelClient

    guard, gate, _ = admitted_context
    ref = reference(Path(guard._workspace))
    value = reader(admitted_context, [ref])
    snapshot = build(value)
    messages = ({"role": "system", "content": snapshot.items[0].content},)
    endpoint = (
        "http://127.0.0.1:8080/v1/chat/completions"
        if path == "nki"
        else RECIPIENT_A.endpoint
    )
    adapter = (
        OpenAICompatibleAdapter(
            backend_id="selected-http", endpoint=endpoint, model="fake"
        )
        if path == "nki"
        else MockModelAdapter()
    )
    if path != "nki":
        adapter.backend_id = RECIPIENT_A.provider_id
        adapter.endpoint = endpoint
    registry = ModelRuntimeRegistry()
    add_model(registry, "a", adapter.backend_id)
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    gateway = ModelGateway(
        registry,
        adapters,
        max_attempts=2,
        max_retries_per_model=1 if path == "invoke_retry" else 0,
    )
    recipient = (
        ProviderRecipient(
            adapter.backend_id,
            gateway._kernel_endpoint(adapter.provider),
            "nki:edge-openai-compatible",
        )
        if path == "nki"
        else ProviderRecipient(adapter.backend_id, endpoint, adapter.backend_id)
    )
    gate.permission_engine.add(
        PermissionRule("*", "context.transfer", value.transfer_resource(recipient))
    )
    checks = []

    def current():
        checks.append(len(gateway.scheduler.active_leases()))
        return True

    hook = SelectedInputAdmission(value, snapshot, current, messages, ())
    request = ModelRequest(
        task_id="original-runtime-boundary",
        required_capabilities=frozenset({"reasoning"}),
        messages=messages,
        _input_admission=hook,
        metadata={"requires_selected_input_admission": True},
    )
    client = FakeKernelClient()
    if path == "nki":
        gateway._use_nki = True

        async def ready():
            return True

        async def setup():
            (Path(guard._workspace) / ref.path).write_text(
                "changed after NKI connection"
            )
            return client

        gateway._ensure_nki_available = ready
        gateway._new_nki_client = setup
    elif path == "stream":

        async def setup(_):
            (Path(guard._workspace) / ref.path).write_text("changed after model load")

        adapter.load = setup
    else:
        from nous_runtime.model_runtime.errors import ModelResourceError

        acquire = gateway.scheduler.acquire
        preparations = []

        async def first(**kwargs):
            preparations.append(True)
            if len(preparations) == 1:
                (Path(guard._workspace) / ref.path).write_text(
                    "changed after failed preparation before provider dispatch"
                )
                raise ModelResourceError("controlled pre-dispatch preparation failure")
            return await acquire(**kwargs)

        gateway.scheduler.acquire = first
        if path == "fallback":
            other = MockModelAdapter()
            other.backend_id = "fallback-provider"
            other.endpoint = "mock://fallback/chat"
            adapters.register(other)
            add_model(registry, "b", other.backend_id)
            other_recipient = ProviderRecipient(
                other.backend_id, other.endpoint, other.backend_id
            )
            gate.permission_engine.add(
                PermissionRule(
                    "*", "context.transfer", value.transfer_resource(other_recipient)
                )
            )

    async def scenario():
        with pytest.raises(Exception):
            if path == "stream":
                async for _ in gateway.stream(request):
                    pass
            else:
                await gateway.invoke(request)
        assert checks and all(count == 1 for count in checks)
        assert gateway.scheduler.active_leases() == ()
        if path == "nki":
            assert client.operation is None and client.closed
        else:
            assert adapter.invocations == []
            if path == "fallback":
                assert other.invocations == []

    asyncio.run(scenario())


@requires_safe_read
def test_budget_omitted_selected_source_is_reported_without_transfer(
    admitted_context, endpoint
):
    url, received = endpoint
    pipeline, gateway, _, actor = pipeline_fixture(
        admitted_context, url, transfer=False
    )
    ref = reference(Path(pipeline.workspace_root))
    try:
        response = pipeline.run(
            RuntimeRequest(
                "Explain these notes",
                request_id="selected-budget",
                user_id=actor.subject_id,
                authenticated_context=actor,
                constraints={
                    "product_capability": "chat",
                    "agent_mode": "chat",
                    "context_token_budgets": {"workspace_facts": 0},
                },
                workspace_file_refs=(ref,),
            )
        )
        assert response.status == "ok", response.to_dict()
        assert len(received) == 1 and "middle constraint" not in json.dumps(received)
        evidence = [
            e.payload
            for e in pipeline.events.load_events("selected-budget")
            if e.event_type == "context.input.dispatched"
        ]
        assert evidence[0]["sources"][0]["status"] == "budget_limited"
        assert evidence[0]["sources"][0]["was_read"] is True
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
def test_completed_original_request_cannot_be_restarted_for_new_input(
    admitted_context, endpoint
):
    url, received = endpoint
    pipeline, gateway, _, actor = pipeline_fixture(admitted_context, url)
    ref = reference(Path(pipeline.workspace_root))
    request = RuntimeRequest(
        "Explain these notes",
        request_id="original-complete",
        user_id=actor.subject_id,
        authenticated_context=actor,
        constraints={"product_capability": "chat", "agent_mode": "chat"},
        workspace_file_refs=(ref,),
    )
    try:
        assert pipeline.run(request).status == "ok"
        assert len(received) == 1
        with pytest.raises(SelectedInputError, match="original_request_already_exists"):
            pipeline.run(request)
        assert len(received) == 1
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
@pytest.mark.parametrize("boundary", ["stream", "nki"])
def test_admitted_stream_and_nki_preserve_exact_input_and_lease(
    admitted_context, boundary
):
    from nous_runtime.model_runtime.adapters import MockModelAdapter
    from tests.model_runtime.test_kernel_execution_gateway import FakeKernelClient

    guard, gate, _ = admitted_context
    ref = reference(Path(guard._workspace))
    value = reader(admitted_context, [ref])
    snapshot = build(value)
    messages = ({"role": "system", "content": snapshot.items[0].content},)
    if boundary == "nki":
        adapter = OpenAICompatibleAdapter(
            backend_id="selected-http",
            endpoint="http://127.0.0.1:8080/v1/chat/completions",
            model="fake",
        )
        recipient = ProviderRecipient(
            "selected-http", "http://127.0.0.1:8080/v1", "nki:edge-openai-compatible"
        )
    else:
        adapter = MockModelAdapter(content="stream result")
        adapter.backend_id = RECIPIENT_A.provider_id
        adapter.endpoint = RECIPIENT_A.endpoint
        recipient = ProviderRecipient(
            adapter.backend_id, adapter.endpoint, adapter.backend_id
        )
    gate.permission_engine.add(
        PermissionRule("*", "context.transfer", value.transfer_resource(recipient))
    )
    gateway = gateway_for(adapter)
    seen = []

    def original():
        seen.append(len(gateway.scheduler.active_leases()))
        return True

    hook = SelectedInputAdmission(value, snapshot, original, messages, ())
    request = ModelRequest(
        task_id="actual-boundary",
        messages=messages,
        required_capabilities=frozenset({"reasoning"}),
        _input_admission=hook,
    )
    client = FakeKernelClient()

    async def scenario():
        if boundary == "nki":
            gateway._use_nki = True

            async def ready():
                return True

            async def setup():
                return client

            gateway._ensure_nki_available = ready
            gateway._new_nki_client = setup
            response = await gateway.invoke(request)
            assert response.content == "kernel response"
            assert json.loads(client.operation["input"])["messages"] == list(messages)
            assert client.closed
        else:
            assert (
                " ".join([chunk async for chunk in gateway.stream(request)])
                == "stream result"
            )
        assert seen == [1]
        assert value.provenance()[0]["status"] == "sent"
        assert gateway.scheduler.active_leases() == ()
        assert hook.last_evidence["input_sha256"] == hook.input_sha256
        assert "selected_input" not in request.metadata

    asyncio.run(scenario())


@requires_safe_read
def test_actual_input_and_accounting_metadata_share_digest_without_serializing_authority(
    admitted_context, endpoint
):
    from nous_runtime.model_runtime.cost_control import (
        CostController,
        Pricing,
        PricingCatalog,
    )

    url, received = endpoint
    pipeline, gateway, _, actor = pipeline_fixture(admitted_context, url)
    gateway._cost_controller = CostController(
        Path(pipeline.workspace_root) / ".nous" / "usage.sqlite3",
        pricing=PricingCatalog({"selected-http/fake-selected-model": Pricing(1, 2)}),
    )
    ref = reference(Path(pipeline.workspace_root))
    try:
        response = pipeline.run(
            RuntimeRequest(
                "Explain these notes",
                request_id="selected-accounting",
                user_id=actor.subject_id,
                authenticated_context=actor,
                constraints={"product_capability": "chat", "agent_mode": "chat"},
                workspace_file_refs=(ref,),
            )
        )
        assert response.status == "ok", response.to_dict()
        assert len(received) == 1
        result = response.result["execution"]["result"]["gateway"]
        events = pipeline.events.load_events("selected-accounting")
        manifest = next(
            e.payload["input_manifest"]
            for e in events
            if e.event_type == "model.invocation.started"
        )
        selected = result["raw_metadata"]["selected_input"]
        assert selected["input_sha256"] == manifest["input_sha256"]
        assert selected["sources"][0]["status"] == "sent"
        assert result["raw_metadata"]["usage_receipt"]["status"] == "completed"
        assert "SelectedInputAdmission" not in json.dumps(result)
        assert "middle constraint" not in json.dumps(result["raw_metadata"])
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
@pytest.mark.parametrize("failure", ["collection", "authority", "identity"])
def test_explicit_selection_failure_cannot_dispatch_without_source(
    admitted_context, endpoint, failure
):
    url, received = endpoint
    pipeline, gateway, _, actor = pipeline_fixture(admitted_context, url)
    ref = reference(Path(pipeline.workspace_root))
    if failure == "collection":
        (Path(pipeline.workspace_root) / ref.path).unlink()
    if failure == "authority":
        pipeline.gate.permission_engine = None
    try:
        response = pipeline.run(
            RuntimeRequest(
                "Explain these notes",
                request_id="selected-early-denied",
                user_id=actor.subject_id,
                authenticated_context=None if failure == "identity" else actor,
                constraints={"product_capability": "chat", "agent_mode": "chat"},
                workspace_file_refs=(ref,),
            )
        )
        assert response.status == "selected_input_rejected"
        assert not received
        assert not any(
            e.event_type == "model.invocation.started"
            for e in pipeline.events.load_events("selected-early-denied")
        )
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
@pytest.mark.parametrize(
    "change", ["admitted", "transfer_revoked", "recipient", "version", "cancel"]
)
def test_selected_source_derived_review_reuses_live_admission_and_accounting(
    admitted_context, monkeypatch, change
):
    from nous_runtime.events import EventStream
    from nous_runtime.events.models import RunState
    from nous_runtime.model_runtime.cost_control import (
        CostController,
        Pricing,
        PricingCatalog,
    )
    from nous_runtime.model_runtime.models import ModelResponse

    monkeypatch.setenv("NOUS_LLM_API_KEY", "")
    pipeline, gateway, adapter, actor = pipeline_fixture(
        admitted_context, "mock://selected/main"
    )
    descriptor = gateway.registry.get("selected-model").descriptor
    gateway.registry.register(
        replace(
            descriptor,
            capabilities=frozenset({"chat", "planning", "review", "reasoning"}),
        ),
        replace_existing=True,
        state=gateway.registry.get("selected-model").state,
    )
    gateway._cost_controller = CostController(
        Path(pipeline.workspace_root) / ".nous" / "usage.sqlite3",
        pricing=PricingCatalog({"selected-http/fake-selected-model": Pricing(1, 2)}),
    )
    ref = reference(Path(pipeline.workspace_root))
    observed = []
    main_requests = []

    async def fake_invoke(request, descriptor, instance):
        observed.append(request)
        if request.metadata.get(
            "requires_selected_input_admission"
        ) and not request.metadata.get("collaboration_role"):
            main_requests.append(request)
            content = "The saved constraint is: exact saved middle constraint"
            if change == "transfer_revoked":
                pipeline.gate.permission_engine.add(
                    PermissionRule("*", "context.transfer", "*", effect="deny")
                )
            elif change == "recipient":
                adapter.provider.endpoint = "mock://selected/unapproved-review"
            elif change == "version":
                (Path(pipeline.workspace_root) / ref.path).write_text("changed source")
            elif change == "cancel":
                EventStream(pipeline.workspace_root).emit_state_change(
                    "selected-derived-review",
                    RunState.CANCELLED,
                    task_id="selected-derived-review",
                )
        else:
            content = "APPROVED bounded fake brief"
        return ModelResponse(
            request_id=request.request_id,
            model_id=descriptor.model_id,
            instance_id=instance.instance_id,
            content=content,
            usage={"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        )

    adapter.invoke = fake_invoke
    try:
        response = pipeline.run(
            RuntimeRequest(
                "Explain these notes in parallel",
                request_id="selected-derived-review",
                user_id=actor.subject_id,
                authenticated_context=actor,
                constraints={"product_capability": "chat", "agent_mode": "chat"},
                workspace_file_refs=(ref,),
            )
        )
        result = response.result["execution"]["result"]
        review = result["collaboration"]["review"]
        reviews = [
            request
            for request in observed
            if request.metadata.get("collaboration_role") == "nous.reviewer"
        ]
        assert len(main_requests) == 1
        assert gateway.scheduler.active_leases() == ()
        events = pipeline.events.load_events("selected-derived-review")
        dispatches = [
            event.payload
            for event in events
            if event.event_type == "context.input.dispatched"
        ]
        assert len(dispatches) == (2 if change == "admitted" else 1)
        assert all(item["provider_receipt_confirmed"] is False for item in dispatches)
        assert "middle constraint" not in json.dumps(dispatches)
        assert all(item["sources"][0]["status"] == "sent" for item in dispatches)
        accounting = gateway._cost_controller.summary()
        review_receipts = [
            receipt
            for receipt in accounting["receipts"]
            if receipt["task_id"] == "selected-derived-review.review"
        ]
        assert len(review_receipts) == 1
        assert accounting["pending_requests"] == 0
        assert accounting["reserved_tokens"] == 0
        if change == "admitted":
            assert len(observed) == 5 and len(reviews) == 1
            request = reviews[0]
            assert "exact saved middle constraint" in json.dumps(request.messages)
            assert request.metadata["requires_selected_input_admission"] is True
            assert (
                request.metadata["context_input_kind"]
                == "selected_source_derived_review"
            )
            assert all(item._input_admission is None for item in observed)
            assert dispatches[0]["input_sha256"] != dispatches[1]["input_sha256"]
            assert (
                SelectedInputAdmission._digest(request.messages, ())
                == dispatches[1]["input_sha256"]
            )
            assert not review["error"]
            assert review["usage_receipt_ref"]
            assert review_receipts[0]["status"] == "completed"
            assert review_receipts[0]["usage"]["total_tokens"] == 3
        else:
            assert len(observed) == 4 and reviews == []
            assert review["approved"] is False
            assert review["error"]
            assert any(event.event_type == "context.input.rejected" for event in events)
            assert review_receipts[0]["status"] == "not_dispatched"
            assert review_receipts[0]["usage"]["total_tokens"] == 0
            assert review_receipts[0]["cost_usd"] == 0
            assert review_receipts[0]["dispatch_uncertain"] is False
    finally:
        gateway.close_sync_bridge()


@requires_safe_read
@pytest.mark.parametrize("boundary", ["invoke", "stream"])
@pytest.mark.parametrize("allowed", [True, False])
def test_private_selected_authority_stays_with_gateway_at_adapter_boundary(
    admitted_context, boundary, allowed
):
    from nous_runtime.model_runtime.adapters import MockModelAdapter

    guard, gate, _ = admitted_context
    value = reader(admitted_context, [reference(Path(guard._workspace))])
    snapshot = build(value)
    messages = ({"role": "system", "content": snapshot.items[0].content},)
    adapter = MockModelAdapter(content="bounded fake result")
    adapter.backend_id = RECIPIENT_A.provider_id
    adapter.endpoint = RECIPIENT_A.endpoint
    recipient = ProviderRecipient(
        adapter.backend_id, adapter.endpoint, adapter.backend_id
    )
    gate.permission_engine.add(
        PermissionRule(
            "*",
            "context.transfer",
            value.transfer_resource(recipient),
            effect="allow" if allowed else "deny",
        )
    )
    gateway = gateway_for(adapter)
    checks = []

    def original_active():
        checks.append(len(gateway.scheduler.active_leases()))
        return True

    hook = SelectedInputAdmission(value, snapshot, original_active, messages, ())
    request = ModelRequest(
        task_id="private-boundary",
        messages=messages,
        required_capabilities=frozenset({"reasoning"}),
        _input_admission=hook,
        metadata={"requires_selected_input_admission": True},
    )
    received = []
    invoke = adapter.invoke
    stream = adapter.stream

    async def inspect_invoke(provider_request, descriptor, instance):
        received.append(provider_request)
        return await invoke(provider_request, descriptor, instance)

    async def inspect_stream(provider_request, descriptor, instance):
        received.append(provider_request)
        async for item in stream(provider_request, descriptor, instance):
            yield item

    if boundary == "invoke":
        adapter.invoke = inspect_invoke
    else:
        adapter.stream = inspect_stream

    async def scenario():
        async def call():
            if boundary == "stream":
                return [chunk async for chunk in gateway.stream(request)]
            return await gateway.invoke(request)

        if not allowed:
            with pytest.raises(Exception):
                await call()
            assert received == [] and adapter.invocations == []
        else:
            await call()
            assert len(received) == 1
            provider_request = received[0]
            assert provider_request._input_admission is None
            assert provider_request.to_dict() == request.to_dict()
            assert request._input_admission is hook
            assert hook.last_evidence["input_sha256"] == SelectedInputAdmission._digest(
                provider_request.messages, ()
            )
            assert hook.last_evidence["provider_receipt_confirmed"] is False
            assert hook.last_evidence["sources"][0]["status"] == "sent"
        assert checks == [1]
        assert gateway.scheduler.active_leases() == ()

    asyncio.run(scenario())

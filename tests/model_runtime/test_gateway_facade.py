from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from nous_runtime.model_runtime.adapters import (
    MockModelAdapter,
    ModelAdapterRegistry,
)
from nous_runtime.model_runtime.bridges import (
    GatewayChatHandler,
    GatewayPlanningService,
    GatewayReviewHandler,
    GatewayVerificationHandler,
)
from nous_runtime.model_runtime.facade import (
    GatewayExecutionContext,
    GatewayFallbackPolicy,
    GatewayOperation,
    GatewayRequest,
    GatewayResponse,
    GatewayTraceContext,
    ModelGatewayFacade,
    ReasoningEffort,
    ReasoningMode,
)
from nous_runtime.model_runtime.gateway import ModelGateway
from nous_runtime.model_runtime.models import (
    ModelDescriptor,
    ModelEndpointType,
    ModelInstance,
    ModelInstanceState,
    ModelModality,
)
from nous_runtime.model_runtime.registry import ModelRuntimeRegistry
from nous_runtime.retrieval.gateway_embeddings import (
    GatewayEmbeddingProvider,
)
from nous_runtime.verification.models import VerificationCandidate
from nous_runtime.verification.verifiers import ModelReviewer

ALL_CAPABILITIES = frozenset(
    {
        "chat",
        "completion",
        "structured_output",
        "tool_calling",
        "reasoning",
        "embedding",
        "vision",
        "planning",
        "review",
        "verification",
    }
)

_BUILT_FACADES: list[ModelGatewayFacade] = []


@pytest.fixture(autouse=True)
def close_built_gateway_bridges():
    """Do not leak one synchronous gateway thread per facade test."""
    yield
    while _BUILT_FACADES:
        _BUILT_FACADES.pop().gateway.close_sync_bridge()


def build_facade(
    content,
    *,
    failures_before_success: int = 0,
) -> tuple[ModelGatewayFacade, MockModelAdapter]:
    registry = ModelRuntimeRegistry()
    descriptor = ModelDescriptor(
        model_id="local/unified",
        display_name="Unified",
        provider_id="mock-provider",
        endpoint_type=ModelEndpointType.LOCAL_SERVICE,
        modalities=frozenset(
            {
                ModelModality.TEXT,
                ModelModality.IMAGE,
                ModelModality.EMBEDDING,
            }
        ),
        capabilities=ALL_CAPABILITIES,
        tool_calling=True,
        structured_output=True,
    )
    registry.register(descriptor)
    registry.enable(descriptor.model_id)
    registry.register_instance(
        ModelInstance(
            instance_id="unified-0",
            model_id=descriptor.model_id,
            node_id="local",
            backend="mock",
            state=ModelInstanceState.READY,
        )
    )
    adapter = MockModelAdapter(
        content=content,
        failures_before_success=failures_before_success,
        total_tokens=12,
    )
    adapters = ModelAdapterRegistry()
    adapters.register(adapter)
    facade = ModelGatewayFacade(ModelGateway(registry, adapters))
    _BUILT_FACADES.append(facade)
    return facade, adapter


def request(
    operation: GatewayOperation,
    **kwargs,
) -> GatewayRequest:
    return GatewayRequest(
        operation=operation,
        execution=GatewayExecutionContext(task_id="task"),
        trace=GatewayTraceContext(
            trace_id="trace",
            correlation_id="task",
        ),
        **kwargs,
    )


def test_facade_normalizes_structured_tools_route_usage_and_trace() -> None:
    facade, _adapter = build_facade(
        {
            "content": "done",
            "structured_output": {"answer": 42},
            "tool_calls": [{"name": "lookup", "arguments": {}}],
        }
    )
    response = facade.invoke_sync(
        request(
            GatewayOperation.STRUCTURED_OUTPUT,
            response_schema={"type": "object"},
        )
    )

    assert response.ok
    assert response.content == "done"
    assert response.structured_output == {"answer": 42}
    assert response.tool_calls[0]["name"] == "lookup"
    assert response.provider_id == "mock-provider"
    assert response.route["selected_model_id"] == "local/unified"
    assert response.usage["total_tokens"] == 12
    assert response.usage["reasoning_tokens"] is None
    assert response.usage["counter_measurements"]["reasoning_tokens"] == "unknown"
    assert (
        response.cost_usd is None
        and response.to_dict()["cost_measurement"] == "unknown"
    )
    assert response.trace_context["trace_id"] == "trace"


def test_facade_normalizes_provider_usage_and_finish_reason() -> None:
    facade, adapter = build_facade(None)
    adapter.total_tokens = 0
    original_invoke = adapter.invoke

    async def invoke_with_provider_telemetry(request, descriptor, instance):
        response = await original_invoke(request, descriptor, instance)
        return response.__class__(
            request_id=response.request_id,
            model_id=response.model_id,
            instance_id=response.instance_id,
            content=None,
            usage={
                "prompt_tokens": 4096,
                "completion_tokens": 1024,
                "prompt_cache_hit_tokens": 3072,
                "prompt_cache_miss_tokens": 1024,
                "completion_tokens_details": {"reasoning_tokens": 1024},
                "total_tokens": 5120,
            },
            finish_reason="max_tokens",
        )

    adapter.invoke = invoke_with_provider_telemetry
    response = facade.invoke_sync(request(GatewayOperation.STRUCTURED_OUTPUT))

    assert response.finish_reason == "length"
    assert response.usage == {
        "input_tokens": 4096,
        "output_tokens": 1024,
        "cached_input_tokens": 3072,
        "cache_miss_input_tokens": 1024,
        "reasoning_tokens": 1024,
        "total_tokens": 5120,
        "cache_creation_input_tokens": None,
        "counter_measurements": {
            "input_tokens": "reported",
            "output_tokens": "reported",
            "cached_input_tokens": "reported",
            "cache_miss_input_tokens": "reported",
            "reasoning_tokens": "reported",
            "total_tokens": "reported",
            "cache_creation_input_tokens": "unknown",
        },
    }


def test_facade_reports_retry_and_rejects_secret_metadata() -> None:
    facade, adapter = build_facade("recovered")
    prepare = facade.gateway._ensure_loaded
    preparation_calls = 0

    async def fail_first_preparation(instance, selected):
        nonlocal preparation_calls
        preparation_calls += 1
        if preparation_calls == 1:
            raise ConnectionError("fake setup failed before dispatch")
        await prepare(instance, selected)

    facade.gateway._ensure_loaded = fail_first_preparation
    response = facade.invoke_sync(request(GatewayOperation.REASONING))
    assert response.retry_count == 1
    assert response.fallback_history == ("local/unified",)
    assert preparation_calls == 2 and len(adapter.invocations) == 1

    with pytest.raises(Exception, match="credential reference"):
        request(
            GatewayOperation.CHAT,
            metadata={"api_key": "do-not-store"},
        )


def test_facade_disables_fallback_by_locking_selected_route() -> None:
    facade, _adapter = build_facade("locked")
    response = facade.invoke_sync(
        request(
            GatewayOperation.CHAT,
            fallback=GatewayFallbackPolicy(allowed=False),
        )
    )
    assert response.ok
    assert response.route["fallback_model_ids"] == []


def test_facade_preserves_explicit_reasoning_policy() -> None:
    gateway_request = request(
        GatewayOperation.STRUCTURED_OUTPUT,
        reasoning_mode=ReasoningMode.DISABLED,
        reasoning_effort=ReasoningEffort.NONE,
    )

    model_request = gateway_request.to_model_request()

    assert model_request.metadata["thinking"] == {"type": "disabled"}
    assert model_request.metadata["reasoning_effort"] == "none"

    with pytest.raises(Exception, match="disabled reasoning mode"):
        request(
            GatewayOperation.STRUCTURED_OUTPUT,
            reasoning_mode=ReasoningMode.DISABLED,
            reasoning_effort=ReasoningEffort.HIGH,
        )


def test_chat_planner_reviewer_and_verification_use_facade() -> None:
    facade, adapter = build_facade("chat response")
    chat = GatewayChatHandler(facade)
    result = chat(
        SimpleNamespace(
            request_id="chat-task",
            user_input="hello",
            constraints={"model_id": "local/unified"},
        ),
        {
            "request_id": "chat-task",
            "workspace": "workspace",
            "session": "session",
        },
    )
    assert result["content"] == "chat response"
    assert result["gateway"]["model_id"] == "local/unified"

    adapter.content = {"steps": [{"id": "one"}]}
    plan = GatewayPlanningService(facade).plan(
        "plan this",
        task_id="plan-task",
    )
    assert plan.structured_output["steps"][0]["id"] == "one"

    adapter.content = {"accepted": True, "score": 0.9}
    reviewer = ModelReviewer(GatewayReviewHandler(facade))
    review = reviewer.verify(
        VerificationCandidate({"value": "safe"}),
        {"task_id": "review-task"},
    )
    assert review.accepted is True
    assert review.evidence["gateway"]["provider_id"] == "mock-provider"

    verified = GatewayVerificationHandler(facade).verify(
        {"value": "safe"},
        task_id="verify-task",
    )
    assert verified.structured_output["accepted"] is True


def test_chat_handler_runs_a_bounded_workspace_tool_loop(tmp_path) -> None:
    (tmp_path / "workspace.txt").write_text("ready", encoding="utf-8")

    class QueueFacade:
        def __init__(self) -> None:
            self.requests = []
            self.responses = [
                GatewayResponse(
                    request_id="one",
                    tool_calls=(
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"workspace.txt"}',
                            },
                        },
                    ),
                ),
                GatewayResponse(request_id="two", content="Nous verified the file."),
            ]

        def try_invoke_sync(self, gateway_request):
            self.requests.append(gateway_request)
            return self.responses.pop(0)

    facade = QueueFacade()
    result = GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="agent-task",
            user_input="Read workspace.txt and verify it.",
            constraints={
                "workspace_path": str(tmp_path),
                "agent_mode": "read_only",
            },
        ),
        {"request_id": "agent-task", "workspace": "default"},
    )

    assert result["ok"] is True
    assert result["content"] == "Nous verified the file."
    assert result["agent_steps"][0]["result"]["content"] == "ready"
    assert facade.requests[0].messages[0]["role"] == "system"
    assert any(
        (item.get("function") or {}).get("name") == "read_file"
        for item in facade.requests[0].tools
    )
    assert "read_file" in facade.requests[0].messages[1]["content"]
    assert facade.requests[1].messages[-1]["role"] == "tool"


def test_archived_conversation_reaches_adapter_and_content_free_manifest(tmp_path):
    from nous_runtime.conversation import ConversationMessage, ConversationStore
    from nous_runtime.events import EventStream

    store = ConversationStore(tmp_path, active_window=2)
    conversation = store.create("workspace", "owner")
    archived = "ARCHIVED_ONLY_REQUIREMENT: preserve the original protocol"
    for text in (archived, "Recent context", "Continue the project"):
        store.append(ConversationMessage(conversation.conversation_id, "user", text))
    window = store.context_window(conversation.conversation_id)
    assert archived in window["summary"]
    assert all(archived not in item["content"] for item in window["messages"])
    facade, adapter = build_facade("Review complete")
    requests = []
    original = adapter.invoke

    async def capture(request, descriptor, instance):
        requests.append(request)
        return await original(request, descriptor, instance)

    adapter.invoke = capture
    stream = EventStream(str(tmp_path))
    result = GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="archived-input",
            user_input="Continue the project",
            constraints={
                "agent_mode": "chat",
                "conversation_summary": window["summary"],
                "conversation_messages": window["messages"],
            },
        ),
        {"event_stream": stream},
    )
    assert result["ok"] and len(requests) == 1
    messages = requests[0].messages
    matches = [item for item in messages if archived in item.get("content", "")]
    assert len(matches) == 1 and matches[0]["role"] == "user"
    assert "untrusted" in matches[0]["content"]
    assert messages[-1]["content"] == "Continue the project"
    assert sum(item["content"] == "Continue the project" for item in messages) == 1
    replay = EventStream(str(tmp_path)).load_events("archived-input")
    manifest = next(
        event.payload["input_manifest"]
        for event in replay
        if event.event_type == "model.invocation.started"
    )
    summaries = [
        item
        for item in manifest["messages"]
        if item["source"]["kind"] == "conversation_summary"
    ]
    assert len(summaries) == 1
    assert summaries[0]["source"]["complete_history"] is False
    assert archived not in json.dumps(manifest)
    assert manifest["estimated_input_tokens"] > 0


def test_chat_handler_injects_context_as_untrusted_evidence() -> None:
    class Facade:
        def __init__(self) -> None:
            self.request = None

        def try_invoke_sync(self, request):
            self.request = request
            return GatewayResponse(request_id="context", content="Grounded answer.")

    facade = Facade()
    result = GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="context-task",
            user_input="Continue the project.",
            constraints={"agent_mode": "chat"},
        ),
        {
            "request_id": "context-task",
            "workspace": "default",
            "context_snapshot": {
                "snapshot_id": "snapshot-1",
                "items": [
                    {
                        "item_id": "item-1",
                        "source_id": "fact-1",
                        "source_type": "memory",
                        "content": "Use the NKI execution path.",
                    }
                ],
            },
        },
    )

    assert "untrusted evidence" in facade.request.messages[1]["content"]
    assert result["context_snapshot_id"] == "snapshot-1"
    assert result["citations"][0]["source_id"] == "fact-1"


@pytest.mark.parametrize("path", ["workspace.txt", ".nous/private.txt"])
def test_input_manifest_matches_each_real_gateway_turn_and_replays(
    tmp_path, monkeypatch, path
):
    from nous_runtime.api.routes import route_server
    from nous_runtime.events import EventStream
    from nous_runtime.model_runtime.cost_control import (
        CostController,
        Pricing,
        PricingCatalog,
    )

    (tmp_path / "workspace.txt").write_text("PRIVATE-CONTEXT-CONTENT", encoding="utf-8")
    (tmp_path / ".nous").mkdir(exist_ok=True)
    (tmp_path / ".nous" / "private.txt").write_text("NEVER-READ-PRIVATE-STATE")
    facade, adapter = build_facade(None)
    accounting = CostController(
        tmp_path / "usage.sqlite3",
        pricing=PricingCatalog({"mock-provider/local/unified": Pricing(1, 2)}),
    )
    facade.gateway._cost_controller = accounting
    requests = []
    original = adapter.invoke

    async def capture(request, descriptor, instance):
        requests.append(request)
        adapter.content = (
            {
                "tool_calls": [
                    {
                        "id": "read-1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": path}),
                        },
                    }
                ]
            }
            if len(requests) == 1
            else "Read result reviewed"
        )
        return await original(request, descriptor, instance)

    adapter.invoke = capture
    stream = EventStream(str(tmp_path))
    result = GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="input-evidence",
            user_input="Read the selected file",
            constraints={"workspace_path": str(tmp_path), "agent_mode": "read_only"},
        ),
        {"event_stream": stream},
    )
    assert result["ok"] and len(requests) == 2
    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.input.service")
    page = route_server(
        "GET",
        "/api/v1/runtime/runs/input-evidence/events",
        auth={"headers": {"Authorization": "Bearer fake.input.service"}},
    )
    assert page["ok"], page
    usage_events = [
        event["payload"]
        for event in page["data"]["events"]
        if event["event_type"] == "model.invocation.completed"
    ]
    assert len(usage_events) == 2
    assert all(
        event["cost_usd"] is None and event["cost_measurement"] == "unknown"
        for event in usage_events
    )
    assert all(event["usage"]["reasoning_tokens"] is None for event in usage_events)
    receipts = {
        receipt["receipt_id"]: receipt for receipt in accounting.summary()["receipts"]
    }
    assert len(receipts) == 2
    for event in usage_events:
        receipt = receipts[event["usage_receipt_ref"]]
        assert event["usage_request_id"] == receipt["request_id"]
        assert event["usage_attempt"] == receipt["attempt"] == 1
    manifests = [
        event["payload"]["input_manifest"]
        for event in page["data"]["events"]
        if event["event_type"] == "model.invocation.started"
    ]
    assert len(manifests) == 2
    for index, manifest in enumerate(manifests):
        expected = hashlib.sha256(
            json.dumps(
                {
                    "messages": requests[index].messages,
                    "tools": requests[index].metadata["tools"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        assert manifest["input_sha256"] == expected
        assert {tool["name"] for tool in manifest["tools"]}.isdisjoint(
            {"write_file", "write_files", "run_command"}
        )
    assert not any(
        message["source"]["kind"] == "tool_result"
        for message in manifests[0]["messages"]
    )
    source = manifests[1]["messages"][-1]["source"]
    assert source["kind"] == "tool_result" and source["tool"] == "read_file"
    if path == "workspace.txt":
        assert (
            source["ok"]
            and source["path"] == path
            and source["start_line"] == source["end_line"] == 1
        )
    else:
        assert not source["ok"] and "path" not in source
    persisted = (tmp_path / ".nous" / "events" / "input-evidence.jsonl").read_text()
    assert (
        "PRIVATE-CONTEXT-CONTENT" not in persisted
        and "NEVER-READ-PRIVATE-STATE" not in persisted
    )
    assert (tmp_path / "workspace.txt").read_text() == "PRIVATE-CONTEXT-CONTENT"


def test_chat_handler_uses_bounded_text_tool_protocol_fallback(tmp_path) -> None:
    (tmp_path / "workspace.txt").write_text("ready", encoding="utf-8")

    class ProtocolFacade:
        def __init__(self) -> None:
            self.requests = []
            self.responses = [
                GatewayResponse(
                    request_id="one",
                    content=(
                        'NOUS_TOOL_CALL {"name":"read_file",'
                        '"arguments":{"path":"workspace.txt"}}'
                    ),
                ),
                GatewayResponse(request_id="two", content="Nous verified the file."),
            ]

        def try_invoke_sync(self, gateway_request):
            self.requests.append(gateway_request)
            return self.responses.pop(0)

    facade = ProtocolFacade()
    result = GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="protocol-task",
            user_input="Read workspace.txt.",
            constraints={
                "workspace_path": str(tmp_path),
                "agent_mode": "read_only",
            },
        ),
        {"request_id": "protocol-task", "workspace": "default"},
    )

    assert result["ok"] is True
    assert result["content"] == "Nous verified the file."
    assert result["agent_steps"][0]["tool"] == "read_file"
    assert facade.requests[1].messages[-1]["role"] == "user"
    assert "NOUS_TOOL_RESULT" in facade.requests[1].messages[-1]["content"]


def test_chat_handler_retries_prose_when_governed_effect_is_required(tmp_path) -> None:
    class ProseThenToolFacade:
        def __init__(self) -> None:
            self.requests = []
            self.responses = [
                GatewayResponse(request_id="one", content="I will create the file."),
                GatewayResponse(
                    request_id="two",
                    tool_calls=(
                        {
                            "id": "call-write",
                            "type": "function",
                            "function": {
                                "name": "write_file",
                                "arguments": '{"path":"result.txt","content":"done"}',
                            },
                        },
                    ),
                ),
                GatewayResponse(request_id="three", content="The file was created."),
            ]

        def try_invoke_sync(self, gateway_request):
            self.requests.append(gateway_request)
            return self.responses.pop(0)

    from nous_runtime.governance import ExecutionAuthorizationGate, GovernanceStore
    from nous_runtime.governance.cli import _build_context
    from nous_runtime.workspace.proposals import WorkspaceProposalService

    service = WorkspaceProposalService(
        tmp_path,
        gate=ExecutionAuthorizationGate(store=GovernanceStore(tmp_path / ".nous")),
    )
    facade = ProseThenToolFacade()
    result = GatewayChatHandler(facade, proposal_service=service)(
        SimpleNamespace(
            request_id="effect-task",
            user_input="Create result.txt.",
            constraints={
                "workspace_path": str(tmp_path),
                "agent_mode": "agent",
                "mutation_authorized": True,
            },
        ),
        {"request_id": "effect-task", "workspace": "default"},
    )

    assert not result["ok"] and result["status"] == "waiting_approval"
    assert not (tmp_path / "result.txt").exists()
    original = service.read(result["proposal_id"])
    assert original["subject_id"] == "agent.nous.workspace"
    assert original["source_request_id"] == "effect-task"
    service.broker.respond_operation(
        result["approval_request_id"], "approve", _build_context(), gate=service.gate
    )
    applied = service.apply(result["proposal_id"])
    assert applied["applied"] and applied["verification"]["verdict"] == "MATCH"
    assert (tmp_path / "result.txt").read_text() == "done"
    assert result["agent_steps"][0]["tool"] == "write_file"
    assert len(facade.requests) == 2
    assert len(facade.responses) == 1
    assert (
        "rejected the prose-only response" in facade.requests[1].messages[-1]["content"]
    )


def test_create_intent_receives_extended_bounded_execution_budget(tmp_path) -> None:
    class EventStream:
        def __init__(self) -> None:
            self.events = []

        def emit(self, event) -> None:
            self.events.append(event)

    class Facade:
        def try_invoke_sync(self, request):
            return GatewayResponse(
                request_id=request.execution.task_id, content="Ready."
            )

    stream = EventStream()
    result = GatewayChatHandler(Facade())(  # type: ignore[arg-type]
        SimpleNamespace(
            request_id="create-budget",
            user_input="Create a project.",
            constraints={
                "workspace_path": str(tmp_path),
                "agent_mode": "agent",
                "mutation_authorized": True,
            },
        ),
        {
            "request_id": "create-budget",
            "workspace": "default",
            "intent": "CREATE",
            "event_stream": stream,
        },
    )

    budget = next(
        event
        for event in stream.events
        if event.event_type == "execution.budget.configured"
    )
    assert result["ok"] is False  # A required workspace effect was not fabricated.
    assert budget.payload["max_model_iterations"] == 16


def test_embedding_uses_gateway_and_validates_dimension() -> None:
    facade, adapter = build_facade([[0.1, 0.2], [0.3, 0.4]])
    provider = GatewayEmbeddingProvider(
        facade,
        model_id="gateway-embedding",
        dimension=2,
    )
    assert provider.embed(["one", "two"]) == [
        [0.1, 0.2],
        [0.3, 0.4],
    ]

    adapter.content = [[0.1]]
    with pytest.raises(Exception, match="dimension mismatch"):
        provider.embed(["one"])

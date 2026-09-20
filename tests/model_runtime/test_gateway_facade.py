from __future__ import annotations

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
    return ModelGatewayFacade(ModelGateway(registry, adapters)), adapter


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
    assert response.trace_context["trace_id"] == "trace"


def test_facade_reports_retry_and_rejects_secret_metadata() -> None:
    facade, _adapter = build_facade(
        "recovered",
        failures_before_success=1,
    )
    response = facade.invoke_sync(
        request(GatewayOperation.REASONING)
    )
    assert response.retry_count == 1
    assert response.fallback_history == ("local/unified",)

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

    facade = ProseThenToolFacade()
    result = GatewayChatHandler(facade)(
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

    assert result["ok"] is True
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "done"
    assert result["agent_steps"][0]["tool"] == "write_file"
    assert len(facade.requests) == 3
    assert "rejected the prose-only response" in facade.requests[1].messages[-1]["content"]


def test_create_intent_receives_extended_bounded_execution_budget(tmp_path) -> None:
    class EventStream:
        def __init__(self) -> None:
            self.events = []

        def emit(self, event) -> None:
            self.events.append(event)

    class Facade:
        def try_invoke_sync(self, request):
            return GatewayResponse(request_id=request.execution.task_id, content="Ready.")

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
        event for event in stream.events
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

from __future__ import annotations

import json
from types import SimpleNamespace

from nous_runtime.context.explain import explain_model_input
from nous_runtime.events import EventStream
from nous_runtime.model_runtime.bridges import GatewayChatHandler
from nous_runtime.model_runtime.facade import GatewayResponse


def test_manifest_hash_covers_tool_calls_without_persisting_raw_material():
    sensitive = "FAKE-PRIVATE-INPUT-DO-NOT-PERSIST"
    messages = [
        {
            "role": "assistant",
            "content": sensitive,
            "tool_calls": [{"arguments": sensitive}],
        }
    ]
    tools = [
        {"function": {"name": "read_file", "parameters": {"description": sensitive}}}
    ]
    manifest = explain_model_input(messages, tools, {})
    assert sensitive not in json.dumps(manifest)
    assert manifest["raw_content_recorded"] is False
    assert manifest["execution_authority"] is False
    assert manifest["estimated_input_tokens"] > 0
    different = explain_model_input([{**messages[0], "tool_calls": []}], tools, {})
    assert different["input_sha256"] != manifest["input_sha256"]
    assert manifest == explain_model_input(messages, tools, {})


def test_manifest_bounds_details_but_hashes_the_entire_input():
    messages = [{"role": "user", "content": str(index)} for index in range(300)]
    tools = [{"function": {"name": f"tool{index}"}} for index in range(70)]
    manifest = explain_model_input(messages, tools, {})
    assert len(manifest["messages"]) == 256
    assert len(manifest["tools"]) == 64
    assert manifest["message_count"] == 300 and manifest["messages_truncated"]
    assert manifest["tool_count"] == 70 and manifest["tools_truncated"]
    messages[-1]["content"] = "different tail"
    assert (
        manifest["input_sha256"]
        != explain_model_input(messages, tools, {})["input_sha256"]
    )


def test_context_manifest_reports_actual_truncation_and_no_raw_source_ids(tmp_path):
    class Facade:
        def try_invoke_sync(self, request):
            self.request = request
            return GatewayResponse(request_id="answer", content="Ready")

    stream = EventStream(str(tmp_path))
    facade = Facade()
    items = [
        {
            "source_type": "memory",
            "source_id": "FAKE-PRIVATE-SOURCE",
            "content": "a" * 30_000,
        },
        {"source_type": "device", "source_id": "omitted-device", "content": "not-sent"},
    ]
    GatewayChatHandler(facade)(
        SimpleNamespace(
            request_id="truncated-input",
            user_input="Continue",
            constraints={"agent_mode": "chat"},
        ),
        {
            "context_snapshot": {"id": "snapshot", "items": items},
            "event_stream": stream,
        },
    )
    events = list(EventStream(str(tmp_path)).iter_persisted_events("truncated-input"))
    manifest = next(
        event.payload["input_manifest"]
        for event in events
        if event.event_type == "model.invocation.started"
    )
    context = next(
        message
        for message in manifest["messages"]
        if message["source"]["kind"] == "selected_context"
    )
    assert (
        context["content_characters"]
        == len(facade.request.messages[1]["content"])
        == 28_000
    )
    sources = context["source"]["items"]
    assert sources[0]["status"] == "partial" and sources[1]["status"] == "omitted"
    assert sources[1]["included_characters"] == 0
    persisted = (tmp_path / ".nous" / "events" / "truncated-input.jsonl").read_text()
    assert "FAKE-PRIVATE-SOURCE" not in persisted and "not-sent" not in persisted


def test_input_event_is_emitted_only_after_agent_model_admission(tmp_path, monkeypatch):
    from nous_runtime.chat.agent_execution import ChatAgentExecution

    class Facade:
        def try_invoke_sync(self, request):
            raise AssertionError("An unadmitted model must not run")

    monkeypatch.setattr(
        ChatAgentExecution, "invoke_model", lambda *_: (None, {"status": "blocked"})
    )
    stream = EventStream(str(tmp_path))
    result = GatewayChatHandler(Facade())(
        SimpleNamespace(
            request_id="blocked-input",
            user_input="Continue",
            constraints={"agent_mode": "chat"},
        ),
        {"event_stream": stream},
    )
    assert not result["ok"]
    assert not any(
        event.event_type.startswith("model.invocation.")
        for event in stream.iter_persisted_events("blocked-input")
    )


def test_conversation_api_preserves_canonical_run_binding_after_restart(
    tmp_path, monkeypatch
):
    from nous_runtime.api.routes import route_server
    from nous_runtime.conversation import ConversationMessage, ConversationStore

    monkeypatch.setenv("NOUS_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("NOUS_RUNTIME_MODE", "production")
    monkeypatch.setenv("NOUS_API_TOKEN", "fake.context")
    store = ConversationStore(str(tmp_path))
    conversation = store.create("default", "local", title="Input evidence")
    store.append(
        ConversationMessage(
            conversation.conversation_id,
            "assistant",
            "Answer",
            run_id="original-run",
            task_id="original-task",
            metadata={"trace_id": "different-trace"},
        )
    )
    result = route_server(
        "GET",
        f"/api/v1/conversations/{conversation.conversation_id}",
        auth={"headers": {"Authorization": "Bearer fake.context"}},
    )
    assert result["ok"], result
    message = result["data"]["messages"][0]
    assert message["run_id"] == "original-run"
    assert message["task_id"] == "original-task"
    assert message["trace_id"] == "different-trace"
